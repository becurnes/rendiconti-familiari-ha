"""Prepare the Supervisor volume, then irrevocably drop filesystem privileges."""
import base64
import hashlib
import ipaddress
import json
import re
import os
import stat
import subprocess
import sys

APP_UID = 10001
APP_GID = 10001
DATA_FILES = (
    "rendiconti.sqlite3", "rendiconti.sqlite3-wal", "rendiconti.sqlite3-shm",
    "rendiconti.sqlite3-journal", "enablebanking-private.pem",
    "enablebanking-public.crt", "enablebanking.json",
)
SAFE_OPEN = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def open_regular(directory, name):
    try:
        fd = os.open(name, SAFE_OPEN, dir_fd=directory)
    except FileNotFoundError:
        return None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise RuntimeError(f"File dati non valido: {name}")
    return fd


def prepare_volume(path):
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        settings = {}
        options = open_regular(directory, "options.json")
        if options is not None:
            with os.fdopen(options, "rb") as file:
                raw = file.read(65_537)
                os.fchmod(file.fileno(), 0o600)
            if len(raw) > 65_536:
                raise RuntimeError("Configurazione Home Assistant troppo grande.")
            settings = json.loads(raw)
            user = settings.get("utente_autorizzato") or ""
            if not isinstance(user, str):
                raise RuntimeError("Nome utente Home Assistant non valido.")
        for name in DATA_FILES:
            fd = open_regular(directory, name)
            if fd is not None:
                try:
                    os.fchmod(fd, 0o600)
                    os.fchown(fd, APP_UID, APP_GID)
                finally:
                    os.close(fd)
        os.fchmod(directory, 0o700)
        os.fchown(directory, APP_UID, APP_GID)
        return settings
    finally:
        os.close(directory)


def http_environment(settings):
    if settings.get("lan_http") is not True:
        return {}
    from lan_https import private_network

    network = private_network(settings.get("lan_ipv4"))
    try:
        address = ipaddress.IPv4Address(settings.get("lan_http_ip") or "")
    except ValueError:
        raise ValueError("Inserisci l’IPv4 locale di Home Assistant.") from None
    if address not in network:
        raise ValueError("L’IPv4 di Home Assistant deve essere nella sottorete LAN autorizzata.")
    password = settings.get("lan_http_password")
    if not isinstance(password, str) or not re.fullmatch(r"[!-~]{24,128}", password):
        raise ValueError("Usa una password dedicata di 24–128 caratteri ASCII senza spazi.")
    credentials = base64.b64encode(("rendiconti:" + password).encode("ascii"))
    return {
        "RENDICONTI_HTTP_ADDRESS": str(address),
        "RENDICONTI_HTTP_NETWORK": str(network),
        "RENDICONTI_HTTP_CREDENTIAL_DIGEST": hashlib.sha256(credentials).hexdigest(),
    }


def main():
    os.umask(0o077)
    sys.path.insert(0, "/app")
    from lan_https import prepare_gateway
    settings = prepare_volume("/data")
    runtime = ""
    try:
        runtime = prepare_gateway(settings, APP_UID, APP_GID)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Accesso HTTPS LAN disattivato: {error}", file=sys.stderr)
    try:
        http = http_environment(settings)
    except ValueError as error:
        print(f"Accesso HTTP LAN disattivato: {error}", file=sys.stderr)
        http = {}
    # Pass only selected settings, including a digest rather than the HTTP password.
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)
    if os.getresuid() != (APP_UID,) * 3 or os.getresgid() != (APP_GID,) * 3:
        raise RuntimeError("Impossibile ridurre i privilegi del server.")
    os.execve(sys.executable, [sys.executable, "-B", "-u", "/app/server.py"], {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "RENDICONTI_ALLOWED_USER": settings.get("utente_autorizzato") or "",
        "RENDICONTI_HTTPS_RUNTIME": runtime,
        **http,
    })


if __name__ == "__main__":
    main()

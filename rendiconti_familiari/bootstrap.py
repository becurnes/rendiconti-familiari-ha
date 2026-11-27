"""Prepare the Supervisor volume, then irrevocably drop filesystem privileges."""
import json
import os
import stat
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
        user = ""
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
        return user
    finally:
        os.close(directory)


def main():
    os.umask(0o077)
    allowed_user = prepare_volume("/data")
    # Supervisor options and environment are never exposed to the HTTP process.
    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)
    if os.getresuid() != (APP_UID,) * 3 or os.getresgid() != (APP_GID,) * 3:
        raise RuntimeError("Impossibile ridurre i privilegi del server.")
    os.execve(sys.executable, [sys.executable, "-B", "-u", "/app/server.py"], {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "RENDICONTI_ALLOWED_USER": allowed_user,
    })


if __name__ == "__main__":
    main()

"""Optional LAN TLS gateway. It never shares Ingress authentication."""
import ipaddress
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

NGINX = "/usr/sbin/nginx"
PORT = 8443
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
BCRYPT_RECORD = re.compile(rb"[A-Za-z0-9_.@-]{1,64}:\$2[aby]\$(?:10|11|12)\$[A-Za-z0-9./]{53}")


def network_settings(options):
    hostname = options.get("lan_hostname") or ""
    if not isinstance(hostname, str) or len(hostname) > 253 or "." not in hostname:
        raise ValueError("Inserisci il nome DNS esatto coperto dal certificato.")
    labels = hostname.split(".")
    if not all(HOST_LABEL.fullmatch(label) for label in labels) or labels[-1].isdigit():
        raise ValueError("Il nome DNS deve usare lettere minuscole, numeri e trattini.")
    return hostname, private_network(options.get("lan_ipv4"))


def private_network(raw_network):
    if not isinstance(raw_network, str) or "/" not in raw_network:
        raise ValueError("Inserisci la sottorete IPv4 locale in formato CIDR.")
    try:
        network = ipaddress.IPv4Network(raw_network, strict=True)
    except ValueError:
        raise ValueError("Sottorete LAN IPv4 non valida.") from None
    if network.prefixlen < 16 or not any(network.subnet_of(private) for private in PRIVATE_NETWORKS):
        raise ValueError("È necessaria una sottorete LAN IPv4 privata con prefisso da /16 a /32.")
    return network


def read_asset(directory, name, limit):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError(f"File non valido: {name}.")
            data = stream.read(limit + 1)
    except OSError:
        raise ValueError(f"File mancante o illeggibile: {name}.") from None
    if not data or len(data) > limit:
        raise ValueError(f"File non valido: {name}.")
    return data


def prepare_gateway(options, uid, gid, config_path=Path("/config"),
                    runtime=Path("/run/rendiconti-https")):
    # The root-owned parent prevents replacement of the runtime path by the HTTP user.
    try:
        shutil.rmtree(runtime)
    except FileNotFoundError:
        pass
    if options.get("lan_https") is not True:
        return ""
    hostname, network = network_settings(options)
    try:
        directory = os.open(config_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("Cartella di configurazione TLS dell’app non disponibile.") from None
    try:
        cert = read_asset(directory, "lan-fullchain.pem", 128 * 1024)
        key = read_asset(directory, "lan-privkey.pem", 32 * 1024)
        users = read_asset(directory, "lan-users.htpasswd", 4096)
    finally:
        os.close(directory)
    records = users.splitlines()
    if (not 1 <= len(records) <= 20 or not all(BCRYPT_RECORD.fullmatch(record) for record in records)
            or len({record.split(b":", 1)[0] for record in records}) != len(records)):
        raise ValueError("Servono utenti univoci e hash htpasswd bcrypt con costo da 10 a 12.")
    for checks, expected in [
        (["-checkend", "0"], b"Certificate will not expire"),
        (["-checkhost", hostname], b"does match certificate"),
    ]:
        certificate = subprocess.run(
            ["/usr/bin/openssl", "x509", "-noout", *checks],
            input=cert, capture_output=True, timeout=5,
        )
        if certificate.returncode or expected not in certificate.stdout:
            raise ValueError("Certificato TLS scaduto o non corrispondente al nome DNS.")
    runtime.mkdir(mode=0o700)
    try:
        settings = (Path(__file__).with_name("lan-nginx.conf").read_text()
                    .replace("@HOSTNAME@", hostname).replace("@NETWORK@", str(network))
                    .replace("@PORT@", str(PORT)).replace("@RUNTIME@", str(runtime)))
        assets = {
            "nginx.conf": settings.encode(), "fullchain.pem": cert,
            "privkey.pem": key, "users.htpasswd": b"\n".join(records) + b"\n",
        }
        for name, content in assets.items():
            path = runtime / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                os.fchown(stream.fileno(), uid, gid)
        os.chown(runtime, uid, gid)
    except BaseException:
        shutil.rmtree(runtime)
        raise
    return str(runtime)


def start_gateway(runtime):
    args = [NGINX, "-p", runtime + "/", "-c", "nginx.conf"]
    verified = subprocess.run([*args, "-t"], capture_output=True, timeout=5)
    if verified.returncode:
        raise ValueError("Configurazione TLS non valida. Controlla certificato e chiave dedicati.")
    return subprocess.Popen(args)

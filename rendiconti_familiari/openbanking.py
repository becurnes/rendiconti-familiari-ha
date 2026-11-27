"""Enable Banking integration for read-only account information."""
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import threading
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

API = "https://api.enablebanking.com"
AUTHORIZATION_HOSTS = {"auth.enablebanking.com", "tilisy.enablebanking.com"}
CALLBACK = "https://localhost:28787/rendiconti-bper"
CALLBACK_ALTERNATIVE = "https://127.0.0.1:28787/rendiconti-bper"
MAX_CENTS = 99_999_999


class BankError(Exception):
    def __init__(self, message, expired=False):
        super().__init__(message)
        self.expired = expired


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def uuid_value(value):
    if not isinstance(value, str):
        raise ValueError("Identificativo non valido.")
    return str(UUID(value))


def encode_part(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def openssl(*args, data=None):
    try:
        result = subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError):
        raise BankError("Impossibile usare il certificato locale di Enable Banking.") from None
    return result.stdout


def private_write(path, content):
    fd, scratch = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def read_payload(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise BankError("La risposta della banca è troppo grande. Riprova scegliendo un altro mese.")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise BankError("Risposta di Enable Banking non riconosciuta.")
    return payload


def normalized_movement(row):
    if not isinstance(row, dict) or row.get("status") != "BOOK" or row.get("credit_debit_indicator") != "DBIT":
        return None
    amount = row.get("transaction_amount")
    if not isinstance(amount, dict) or amount.get("currency") != "EUR":
        return None
    raw = amount.get("amount", "")
    if not isinstance(raw, str) or not re.fullmatch(r"-?[0-9]{1,9}(\.[0-9]{1,2})?", raw):
        return None
    try:
        cents = int(abs(Decimal(raw)) * 100)
        day = date.fromisoformat(row.get("booking_date") or row.get("transaction_date")).isoformat()
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not 0 < cents <= MAX_CENTS:
        return None
    details = row.get("remittance_information")
    parts = [item.strip() for item in details if isinstance(item, str) and item.strip()] if isinstance(details, list) else []
    creditor = row.get("creditor")
    if not parts and isinstance(creditor, dict) and isinstance(creditor.get("name"), str):
        parts = [creditor["name"]]
    code = row.get("bank_transaction_code")
    if not parts and isinstance(code, dict) and isinstance(code.get("description"), str):
        parts = [code["description"]]
    description = " ".join(" · ".join(parts).split())[:500] or "Addebito BPER"
    ref = row.get("entry_reference")
    return day, description, cents, ref if isinstance(ref, str) else ""


class OpenBanking:
    def __init__(self, data):
        self.key = data / "enablebanking-private.pem"
        self.certificate = data / "enablebanking-public.crt"
        self.state = data / "enablebanking.json"
        self.lock = threading.Lock()
        self.opener = build_opener(NoRedirect)

    def load(self):
        return json.loads(self.state.read_bytes()) if self.state.exists() else {}

    def save(self, state):
        private_write(self.state, json.dumps(state, separators=(",", ":")).encode())

    def api(self, state, method, path, body=None):
        now = int(time.time())
        header = encode_part({"typ": "JWT", "alg": "RS256", "kid": state["application"]})
        claims = encode_part({"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                              "iat": now, "exp": now + 120})
        unsigned = header + b"." + claims
        signature = openssl("dgst", "-sha256", "-sign", str(self.key), data=unsigned)
        token = (unsigned + b"." + encode_part(signature)).decode()
        request = Request(API + path, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                   "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=12) as response:
                return {} if response.status == 204 else read_payload(response, 4_000_000)
        except HTTPError as error:
            try:
                with error:
                    code = read_payload(error, 30_000).get("code")
            except (ValueError, OSError, BankError):
                code = None
            if code in {"EXPIRED_SESSION", "CLOSED_SESSION", "REVOKED_SESSION", "SESSION_DOES_NOT_EXIST"}:
                raise BankError("Consenso scaduto o revocato. Ricollega il conto BPER.", expired=True) from None
            if code == "REDIRECT_URI_NOT_ALLOWED":
                raise BankError("Abilita in Enable Banking lo stesso URL di rientro selezionato in Rendiconti.") from None
            if code in {"EXPIRED_AUTHORIZATION_CODE", "WRONG_AUTHORIZATION_CODE"}:
                raise BankError("Il codice di rientro non è più valido. Avvia un nuovo collegamento.") from None
            hint = {
                400: "Verifica applicazione, URL di rientro e configurazione del consenso.",
                401: "Verifica ID applicazione e certificato registrato.",
                403: "Verifica che l’applicazione sia attiva e che il conto sia tra quelli collegati.",
                429: "Attendi prima di riprovare.",
            }.get(error.code, "Riprova più tardi.")
            raise BankError(f"Enable Banking ha risposto con errore {error.code}. {hint}") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise BankError("Enable Banking non risponde o ha restituito una risposta non valida.") from None

    def status(self, state):
        session = state.get("session") or {}
        return {"certificate": self.certificate.is_file() and self.key.is_file(),
                "application": state.get("application", ""),
                "redirect": state.get("redirect", CALLBACK),
                "pending": bool(state.get("pending", {}).get("expires", 0) > time.time()),
                "connected": bool(session.get("account")), "hasSession": bool(session),
                "account": (session.get("account") or {}).get("label", ""),
                "choices": [{"index": index, "label": item["label"]}
                            for index, item in enumerate(session.get("choices", []))],
                "expires": session.get("expires", "")}

    def prepare_certificate(self):
        if not self.key.is_file():
            key = openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:4096")
            private_write(self.key, key)
        if not self.certificate.is_file():
            certificate = openssl("req", "-new", "-x509", "-days", "730",
                                  "-key", str(self.key), "-subj", "/CN=Rendiconti familiari")
            private_write(self.certificate, certificate)
        return {"pem": self.certificate.read_text()}

    def start(self, state):
        if not state.get("application") or not self.key.is_file():
            raise BankError("Genera il certificato, registralo su Enable Banking e salva l’ID applicazione.")
        if state.get("session"):
            raise BankError("Scollega la sessione precedente prima di avviarne un’altra.")
        institutions = self.api(state, "GET", "/aspsps?" + urlencode(
            {"country": "IT", "psu_type": "personal"})).get("aspsps", [])
        bank = next((item for item in institutions
                     if item.get("country") == "IT" and item.get("name", "").casefold() == "bper banca"), None)
        if not bank:
            raise BankError("BPER Banca non è disponibile per questo tipo di applicazione Enable Banking.")
        ttl = bank.get("maximum_consent_validity")
        duration = min(30 * 86400, ttl) if type(ttl) is int and ttl > 0 else 30 * 86400
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat(timespec="seconds")
        nonce = secrets.token_urlsafe(32)
        response = self.api(state, "POST", "/auth", {
            "access": {"valid_until": expiry},
            "aspsp": {"name": bank["name"], "country": "IT"},
            "state": nonce, "redirect_url": state["redirect"], "psu_type": "personal", "language": "it",
        })
        url = response.get("url")
        try:
            parts = urlsplit(url if isinstance(url, str) else "")
        except ValueError:
            raise BankError("Indirizzo di autorizzazione di Enable Banking non riconosciuto.") from None
        if parts.scheme != "https" or parts.netloc not in AUTHORIZATION_HOSTS:
            raise BankError("Indirizzo di autorizzazione di Enable Banking non riconosciuto.")
        state["pending"] = {"nonce": nonce, "expires": time.time() + 1200, "consent_until": expiry}
        self.save(state)
        return {"url": url}

    def finish(self, state, data):
        pending = state.get("pending", {})
        if pending.get("expires", 0) <= time.time():
            raise BankError("Avvia di nuovo il collegamento. L’autorizzazione in corso è scaduta.")
        value = data.get("callback")
        if not isinstance(value, str) or not 0 < len(value) <= 12000:
            raise BankError("Incolla l’indirizzo completo ricevuto dopo l’autorizzazione.")
        parts = urlsplit(value.strip())
        if parts._replace(query="", fragment="").geturl() != state["redirect"] or parts.fragment:
            raise BankError("L’indirizzo incollato non corrisponde all’URL di rientro registrato.")
        fields = parse_qs(parts.query, max_num_fields=16)
        states = fields.get("state", [])
        if len(states) != 1 or not states[0].isascii() or not secrets.compare_digest(states[0], pending["nonce"]):
            raise BankError("Il rientro non corrisponde all’autorizzazione in corso.")
        if "error" in fields:
            state.pop("pending", None)
            self.save(state)
            raise BankError("L’autorizzazione BPER è stata annullata o non è andata a buon fine.")
        codes = fields.get("code", [])
        if len(codes) != 1 or not re.fullmatch(r"[\x21-\x7e]{1,6000}", codes[0]):
            raise BankError("Il rientro non contiene un codice di autorizzazione valido.")
        response = self.api(state, "POST", "/sessions", {"code": codes[0]})
        session_id = uuid_value(response.get("session_id"))
        choices = []
        for index, item in enumerate(response.get("accounts") or []):
            if not isinstance(item, dict):
                continue
            try:
                uid = uuid_value(item.get("uid"))
            except ValueError:
                continue
            identity = item.get("identification_hash")
            account_id = item.get("account_id")
            iban = account_id.get("iban") if isinstance(account_id, dict) else None
            identity = identity or (iban if isinstance(iban, str) else "")
            if not isinstance(identity, str) or not identity:
                continue
            label = f"Conto BPER •••• {iban[-4:]}" if isinstance(iban, str) and len(iban) >= 4 else f"Conto BPER {index + 1}"
            choices.append({"uid": uid, "identity": hashlib.sha256(identity.encode()).hexdigest(), "label": label})
        state.pop("pending", None)
        state["session"] = {"id": session_id, "expires": (response.get("access") or {}).get(
            "valid_until", pending["consent_until"])}
        if len(choices) == 1:
            state["session"]["account"] = choices[0]
        else:
            state["session"]["choices"] = choices
        self.save(state)
        return self.status(state)

    def movements(self, state, data):
        session = state.get("session", {})
        account = session.get("account")
        if not account:
            raise BankError("Collega e seleziona il conto BPER.")
        expiry = datetime.fromisoformat(session["expires"].replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise BankError("Consenso scaduto. Scollega e ricollega il conto BPER.")
        month = data.get("month")
        if not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            raise BankError("Mese non valido.")
        start = date.fromisoformat(month + "-01")
        end = min(date(start.year, start.month, monthrange(start.year, start.month)[1]), date.today())
        if end < start:
            raise BankError("Seleziona un mese già iniziato.")
        query = {"date_from": start.isoformat(), "date_to": end.isoformat(), "transaction_status": "BOOK"}
        path = "/accounts/" + account["uid"] + "/transactions?"
        rows, seen, repeats, cursors = [], set(), {}, set()
        for _ in range(12):
            payload = self.api(state, "GET", path + urlencode(query))
            for raw in payload.get("transactions", []):
                movement = normalized_movement(raw)
                if not movement:
                    continue
                day, description, cents, ref = movement
                if not start.isoformat() <= day <= end.isoformat():
                    continue
                if ref:
                    ref = "reference:" + ref
                else:
                    content = json.dumps([day, description, cents], ensure_ascii=False)
                    repeats[content] = repeats.get(content, 0) + 1
                    ref = f"fallback:{content}:{repeats[content]}"
                key = hashlib.sha256(f"enable-bper:{account['identity']}:{ref}".encode()).hexdigest()
                if key not in seen:
                    seen.add(key)
                    rows.append({"day": day, "description": description, "cents": cents, "key": key})
                if len(rows) > 2000:
                    raise BankError("Sono presenti più di 2.000 uscite. Usa l’importazione da file per questo mese.")
            cursor = payload.get("continuation_key")
            if not cursor:
                return {"movements": sorted(rows, key=lambda row: row["day"], reverse=True)}
            if not isinstance(cursor, str) or cursor in cursors or len(cursor) > 4000:
                break
            cursors.add(cursor)
            query["continuation_key"] = cursor
        raise BankError("Impossibile completare la lettura di tutte le pagine dei movimenti.")

    def dispatch(self, action, data):
        with self.lock:
            state = self.load()
            if action == "status":
                return self.status(state)
            if action == "certificate":
                return self.prepare_certificate()
            if action == "configure":
                if state.get("session"):
                    raise BankError("Scollega il conto prima di modificare l’applicazione.")
                redirect = data.get("redirect")
                if redirect not in (CALLBACK, CALLBACK_ALTERNATIVE):
                    raise BankError("Usa uno degli URL di rientro locali indicati nel pannello.")
                try:
                    application = uuid_value(data.get("application"))
                except ValueError:
                    raise BankError("Inserisci l’ID applicazione indicato da Enable Banking.") from None
                state = {"application": application, "redirect": redirect}
                self.save(state)
                return self.status(state)
            if action == "start":
                return self.start(state)
            if action == "finish":
                return self.finish(state, data)
            if action == "select":
                session = state.get("session", {})
                choices = session.get("choices") or []
                index = data.get("index")
                if type(index) is not int or not 0 <= index < len(choices):
                    raise BankError("Seleziona un conto valido.")
                session["account"] = choices[index]
                session.pop("choices")
                self.save(state)
                return self.status(state)
            if action == "disconnect":
                session = state.get("session")
                if session:
                    try:
                        self.api(state, "DELETE", "/sessions/" + session["id"])
                    except BankError as error:
                        if not error.expired:
                            raise
                state.pop("session", None)
                state.pop("pending", None)
                self.save(state)
                return self.status(state)
            if action == "movements":
                return self.movements(state, data)
            raise BankError("Operazione Open Banking non valida.")

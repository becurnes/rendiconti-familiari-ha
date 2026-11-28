import base64
import binascii
import csv
import hashlib
import hmac
import ipaddress
import io
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import xlrd
from waitress.server import create_server

from lan_https import start_gateway

ROOT = Path(__file__).resolve().parent
DEMO = os.environ.get("RENDICONTI_DEMO") == "1"
DATA = Path(os.environ.get("RENDICONTI_DATA", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "rendiconti.sqlite3"
MAX_CENTS = 99_999_999
ALLOWED_USER = os.environ.get("RENDICONTI_ALLOWED_USER", "").strip()
MAX_BANK_FILE = 1_000_000
MAX_BANK_ROWS = 2000
MAX_REQUEST_BODY = 2_500_000
LAN_HTTP_PORT = 8100


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=12)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    with database() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            day TEXT NOT NULL,
            description TEXT NOT NULL,
            source_key TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS shares (
            expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
            person_id INTEGER NOT NULL REFERENCES people(id),
            cents INTEGER NOT NULL CHECK(cents > 0),
            PRIMARY KEY(expense_id, person_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            day TEXT NOT NULL,
            person_id INTEGER NOT NULL REFERENCES people(id),
            cents INTEGER NOT NULL CHECK(cents > 0),
            note TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS expenses_month ON expenses(month);
        CREATE INDEX IF NOT EXISTS payments_month ON payments(month);
        """)
        db.execute("BEGIN IMMEDIATE")
        if not any(column["name"] == "arrears_target" for column in db.execute("PRAGMA table_info(payments)")):
            db.execute("ALTER TABLE payments ADD COLUMN arrears_target TEXT")
        db.execute("""
            CREATE TABLE IF NOT EXISTS payment_allocations (
                payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
                month TEXT NOT NULL,
                cents INTEGER NOT NULL CHECK(cents > 0),
                PRIMARY KEY(payment_id, month)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS payment_allocations_month ON payment_allocations(month)")
        db.execute("""
            CREATE VIEW IF NOT EXISTS payment_credits AS
            SELECT id AS payment_id, month, day, person_id, note, month AS recorded_month,
                cents - COALESCE(
                    (SELECT SUM(a.cents) FROM payment_allocations a WHERE a.payment_id = payments.id), 0
                ) AS cents
            FROM payments
            UNION ALL
            SELECT p.id, a.month, p.day, p.person_id, p.note, p.month, a.cents
            FROM payment_allocations a JOIN payments p ON p.id = a.payment_id
        """)
        db.executemany("INSERT OR IGNORE INTO people(id, name) VALUES (?, ?)",
                       [(1, "Mamma"), (2, "Papà")])


class InputError(Exception):
    pass


def valid_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise InputError("Data non valida.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise InputError("Data non valida.") from None
    return value


def valid_month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
        raise InputError("Mese non valido.")
    valid_day(value + "-01")
    return value


def positive_int(value, maximum=2**53 - 1):
    if type(value) is not int or not 1 <= value <= maximum:
        raise InputError("Numero o importo non valido.")
    return value


def clean_text(value, maximum, required=False):
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise InputError(f"Campo di testo non valido (massimo {maximum} caratteri).")
    value = value.strip()
    if required and not value:
        raise InputError("Compila tutti i campi obbligatori.")
    return value


def rows(db, query, params=()):
    return [dict(row) for row in db.execute(query, params)]


def month_data(db, month):
    people = rows(db, "SELECT id, name FROM people ORDER BY id")
    expenses = rows(db, """
        SELECT id, day, description, source_key FROM expenses
        WHERE month = ? ORDER BY day, id
    """, (month,))
    by_id = {expense["id"]: expense for expense in expenses}
    for expense in expenses:
        expense["shares"] = []
        expense["cents"] = 0
    for share in rows(db, """
        SELECT expense_id, person_id, cents FROM shares JOIN expenses ON expenses.id = expense_id
        WHERE month = ? ORDER BY person_id
    """, (month,)):
        expense = by_id[share.pop("expense_id")]
        expense["shares"].append(share)
        expense["cents"] += share["cents"]
    payments = rows(db, """
        SELECT id, day, person_id, cents, note, arrears_target FROM payments
        WHERE month = ? ORDER BY day, id
    """, (month,))
    by_payment = {payment["id"]: payment for payment in payments}
    for payment in payments:
        payment["allocations"] = []
    for allocation in rows(db, """
        SELECT payment_id, a.month, a.cents FROM payment_allocations a
        JOIN payments p ON p.id = a.payment_id WHERE p.month = ? ORDER BY a.month
    """, (month,)):
        by_payment[allocation.pop("payment_id")]["allocations"].append(allocation)
    credits = rows(db, """
        SELECT payment_id, day, person_id, cents, note, recorded_month FROM payment_credits
        WHERE month = ? AND cents > 0 ORDER BY day, payment_id
    """, (month,))
    months = [row["month"] for row in db.execute("""
        SELECT month FROM expenses UNION SELECT month FROM payments ORDER BY month DESC
    """)]
    return {"people": people, "expenses": expenses, "payments": payments, "credits": credits,
            "months": months, "arrears": prior_balances(db, month)}


def prior_balances(db, month, exclude_payment=None):
    balances = rows(db, """
        SELECT person_id, month, SUM(cents) AS cents
        FROM (
            SELECT person_id, month, SUM(cents) AS cents
            FROM shares JOIN expenses ON expenses.id = expense_id
            WHERE month < ? GROUP BY person_id, month
            UNION ALL
            SELECT person_id, month, -SUM(cents) AS cents
            FROM payment_credits WHERE month < ? AND payment_id IS NOT ?
            GROUP BY person_id, month
        )
        GROUP BY person_id, month
        HAVING SUM(cents) > 0
        ORDER BY month, person_id
    """, (month, month, exclude_payment))
    return balances


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if c.isalnum())


BANK_HEADERS = {
    "day": {"data", "datacontabile", "dataoperazione", "dataregistrazione", "datamovimento",
            "dataliquidazione", "date", "datacon"},
    "description": {"descrizione", "descrizionemovimento", "descrizioneoperazione", "movimento",
                    "causale", "descrizionecausale", "operazione", "dettaglio", "description"},
    "amount": {"importo", "importoeur", "importoeneuro", "ammontare", "amount", "importoeuro"},
    "debit": {"uscite", "uscita", "addebiti", "addebito", "dare", "debito", "importoaddebito",
              "usciteeur", "importouscita", "importouscite"},
    "category": {"categoria", "category"},
    "status": {"stato", "status"},
    "sign": {"segno", "segnomovimento", "segnoimporto", "dareaavere", "dareavere", "dsa"},
}


def bank_amount(value):
    value = re.sub(r"(?i)eur|euro|€|\s", "", value).replace("−", "-")
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    elif value.endswith("-"):
        value = "-" + value[:-1]
    if "," in value and "." in value:
        thousands, decimal = (".", ",") if value.rfind(",") > value.rfind(".") else (",", ".")
        value = value.replace(thousands, "").replace(decimal, ".")
    elif re.fullmatch(r"[+-]?\d{1,3}([.,]\d{3})+", value):
        value = value.replace(".", "").replace(",", "")
    else:
        value = value.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d{1,2})?", value):
        raise ValueError("Importo non riconosciuto")
    return int(Decimal(value) * 100)


ITALIAN_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def bank_date(value):
    value = value.strip()
    italian = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", value.lower())
    if italian:
        day, month, year = italian.groups()
        return date(int(year), ITALIAN_MONTHS.index(month) + 1, int(day)).isoformat()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Data non riconosciuta")


def movement_columns(record):
    headers = [normalized(cell) for cell in record]
    mapping = {
        field: next((i for i, cell in enumerate(headers) if cell in names), None)
        for field, names in BANK_HEADERS.items()
    }
    if (mapping["day"] is not None and mapping["description"] is not None
            and (mapping["amount"] is not None or mapping["debit"] is not None)):
        return mapping
    return None


def sheet_text(cell, datemode):
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, datemode).date().isoformat()
        except (ValueError, OverflowError):
            return ""
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return str(cell.value)
    return cell.value if cell.ctype == xlrd.XL_CELL_TEXT else ""


def xls_preview(db, encoded):
    try:
        raw = base64.b64decode(clean_text(encoded, 1_333_336, required=True), validate=True)
    except (binascii.Error, ValueError):
        raise InputError("Il file Excel non è leggibile.") from None
    if len(raw) > MAX_BANK_FILE:
        raise InputError("Il file supera 1 MB.")
    if not raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise InputError("Seleziona un file Excel .xls esportato dalla banca.")
    try:
        book = xlrd.open_workbook(file_contents=raw, logfile=io.StringIO(), on_demand=True,
                                  ragged_rows=True, use_mmap=False)
        try:
            for sheet_index in range(min(book.nsheets, 10)):
                sheet = book.sheet_by_index(sheet_index)
                if sheet.nrows > 10_000 or sheet.ncols > 64:
                    raise InputError("Il foglio Excel è troppo grande. Esporta un periodo più breve.")
                records = ([sheet_text(cell, book.datemode) for cell in record] for record in sheet.get_rows())
                for _, record in zip(range(35), records):
                    mapping = movement_columns(record)
                    if mapping:
                        return collect_movements(db, records, mapping)
        finally:
            book.release_resources()
    except (xlrd.XLRDError, xlrd.compdoc.CompDocError, struct.error, AssertionError,
            IndexError, KeyError, ValueError, OverflowError, TypeError):
        raise InputError("Il file Excel è danneggiato, protetto o in un formato non supportato.") from None
    raise InputError("Nel file Excel mancano le colonne di data, descrizione e importo.")


def bank_preview(db, raw):
    for delimiter in ("\t", ";", ","):
        records = csv.reader(io.StringIO(raw.lstrip("\ufeff")), delimiter=delimiter)
        for _, record in zip(range(35), records):
            mapping = movement_columns(record)
            if mapping:
                return collect_movements(db, records, mapping)
    raise InputError("Intestazioni non riconosciute. Usa Data, Descrizione, Importo (uscite con segno meno), oppure Data, Descrizione, Uscite.")


def collect_movements(db, records, mapping):
    movements, repeats = [], {}
    skipped = pending = 0
    for record in records:
        if not any(cell.strip() for cell in record):
            continue

        def field(name):
            index = mapping[name]
            return record[index].strip() if index is not None and index < len(record) else ""

        if not field("day") and normalized(field("description")) in {"totale", "totalemovimenti"}:
            continue
        raw_amount = field("debit" if mapping["debit"] is not None else "amount").strip('"').strip()
        if raw_amount in {"", "-", "–", "—"}:
            continue
        try:
            signed = bank_amount(raw_amount)
            sign = normalized(field("sign"))
            if mapping["debit"] is not None or sign in {"d", "dare", "debito", "uscita", "addebito"} or field("sign") == "-":
                signed = -abs(signed)
            if signed >= 0 or sign in {"a", "avere", "credito", "entrata", "accredito"}:
                continue
            if normalized(field("status")) in {"dacontabilizzare", "noncontabilizzato", "inattesa"}:
                pending += 1
                continue
            day = bank_date(field("day"))
            description = field("description")
            if not description or len(description) > 500 or abs(signed) > MAX_CENTS:
                raise ValueError("Movimento fuori dai limiti")
        except ValueError:
            skipped += 1
            continue
        identity = json.dumps([day, " ".join(description.casefold().split()), signed])
        repeats[identity] = repeats.get(identity, 0) + 1
        key = hashlib.sha256(f"{identity}:{repeats[identity]}".encode()).hexdigest()
        movements.append({"day": day, "description": description, "cents": -signed,
                          "category": field("category")[:80], "key": key})
        if len(movements) > MAX_BANK_ROWS:
            raise InputError("Il file contiene più di 2.000 uscite. Dividilo in più periodi.")
    mark_imported(db, movements)
    return {"movements": movements, "skipped": skipped, "pending": pending}


def mark_imported(db, movements):
    if not movements:
        return
    days = [row["day"] for row in movements]
    registered = rows(db, """
        SELECT source_key, day, SUM(cents) AS cents
        FROM expenses JOIN shares ON expenses.id = expense_id
        WHERE day BETWEEN ? AND ? OR source_key IS NOT NULL
        GROUP BY expenses.id
    """, (min(days), max(days)))
    exact = {row["source_key"] for row in registered}
    possible = {(row["day"], row["cents"]) for row in registered}
    for row in movements:
        row["imported"] = row["key"] in exact
        row["possible"] = not row["imported"] and (row["day"], row["cents"]) in possible


def save_expense(db, data):
    month, day = valid_month(data.get("month")), valid_day(data.get("day"))
    description = clean_text(data.get("description"), 500, required=True)
    cents = positive_int(data.get("cents"), MAX_CENTS)
    people = data.get("people")
    if not isinstance(people, list) or not people or len(people) > 50:
        raise InputError("Seleziona almeno una persona.")
    people = sorted({positive_int(person) for person in people})
    if cents < len(people):
        raise InputError("L'importo è troppo basso per dividerlo tra tutte le persone.")
    key = data.get("source_key")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key)):
        raise InputError("Riferimento bancario non valido.")
    expense_id = data.get("id")
    if expense_id is None:
        expense_id = db.execute(
            "INSERT INTO expenses(month, day, description, source_key) VALUES (?, ?, ?, ?)",
            (month, day, description, key)
        ).lastrowid
    else:
        result = db.execute("UPDATE expenses SET month=?, day=?, description=? WHERE id=?",
                            (month, day, description, positive_int(expense_id)))
        if result.rowcount == 0:
            raise InputError("La spesa non esiste più.")
        db.execute("DELETE FROM shares WHERE expense_id = ?", (expense_id,))
    share, remainder = divmod(cents, len(people))
    db.executemany("INSERT INTO shares VALUES (?, ?, ?)", [
        (expense_id, person, share + int(index < remainder)) for index, person in enumerate(people)
    ])


def import_movements(db, data):
    month = valid_month(data.get("month"))
    movements = data.get("movements")
    if not isinstance(movements, list) or not 1 <= len(movements) <= MAX_BANK_ROWS:
        raise InputError("Seleziona almeno una spesa da importare.")
    for movement in movements:
        if not isinstance(movement, dict) or not movement.get("key"):
            raise InputError("Movimento non valido.")
        day = valid_day(movement.get("day"))
        if day[:7] != month:
            raise InputError("Le spese devono appartenere al mese selezionato.")
        save_expense(db, {
            "month": month, "day": day, "description": movement.get("description"),
            "cents": movement.get("cents"), "people": movement.get("people"),
            "source_key": movement["key"],
        })
    return {"count": len(movements)}


def allocations_for(db, payment_id, month, person_id, amount, target):
    if not target:
        return []
    if target != "all" and valid_month(target) >= month:
        raise InputError("Scegli un mese precedente a quello del versamento.")
    allocations = []
    for row in prior_balances(db, month, exclude_payment=payment_id):
        if row["person_id"] != person_id or (target != "all" and row["month"] != target):
            continue
        cents = min(amount, row["cents"])
        allocations.append((row["month"], cents))
        amount -= cents
        if not amount:
            break
    if not allocations:
        raise InputError("Non ci sono più arretrati da saldare per la destinazione scelta.")
    return allocations


def save_payment(db, data):
    month, day = valid_month(data.get("month")), valid_day(data.get("day"))
    person_id, cents = positive_int(data.get("person_id")), positive_int(data.get("cents"), MAX_CENTS)
    note = clean_text(data.get("note", ""), 500)
    target = data.get("arrears_target") or None
    payment_id = data.get("id")
    previous = None
    if payment_id is not None:
        previous = db.execute("SELECT * FROM payments WHERE id = ?", (positive_int(payment_id),)).fetchone()
        if previous is None:
            raise InputError("Il versamento non esiste più.")
        if "arrears_target" not in data:
            target = previous["arrears_target"]
    values = (month, day, person_id, cents, note, target)
    # Editing the date or note must not reassign an already recorded settlement.
    keep_allocations = previous is not None and all(previous[key] == value for key, value in (
        ("month", month), ("person_id", person_id), ("cents", cents), ("arrears_target", target),
    ))
    allocations = [] if keep_allocations else allocations_for(db, payment_id, month, person_id, cents, target)
    if previous is None:
        payment_id = db.execute("""
            INSERT INTO payments(month, day, person_id, cents, note, arrears_target)
            VALUES (?, ?, ?, ?, ?, ?)
        """, values).lastrowid
    else:
        db.execute("""
            UPDATE payments SET month=?, day=?, person_id=?, cents=?, note=?, arrears_target=? WHERE id=?
        """, (*values, payment_id))
    if not keep_allocations:
        db.execute("DELETE FROM payment_allocations WHERE payment_id = ?", (payment_id,))
        db.executemany("INSERT INTO payment_allocations VALUES (?, ?, ?)",
                       [(payment_id, period, amount) for period, amount in allocations])


def save_person(db, data):
    name = clean_text(data.get("name"), 60, required=True)
    if data.get("id") is None:
        db.execute("INSERT INTO people(name) VALUES (?)", (name,))
    elif db.execute("UPDATE people SET name=? WHERE id=?",
                    (name, positive_int(data["id"]))).rowcount == 0:
        raise InputError("La persona non esiste più.")


def route(environ):
    method, path = environ["REQUEST_METHOD"], environ["PATH_INFO"]
    static = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
    }
    if method == "GET" and path in static:
        filename, mime = static[path]
        return "200 OK", mime, (ROOT / filename).read_bytes()
    if method == "GET" and path in {"/api/month", "/api/arrears"}:
        query = parse_qs(environ["QUERY_STRING"], max_num_fields=8)
        month = valid_month(query.get("month", [None])[0])
        with database() as db:
            db.execute("BEGIN")
            if path == "/api/arrears":
                payment_id = query.get("exclude", [None])[0]
                if payment_id is not None:
                    payment_id = positive_int(int(payment_id))
                return result(prior_balances(db, month, exclude_payment=payment_id))
            return result(month_data(db, month))
    if method != "POST" or path not in {
        "/api/expense", "/api/payment", "/api/person", "/api/remove", "/api/bank", "/api/bank/import"
    }:
        return result({"error": "Pagina non trovata."}, "404 Not Found")
    if (environ.get("HTTP_X_RENDICONTI") != "1"
            or environ.get("CONTENT_TYPE", "").partition(";")[0] != "application/json"):
        return result({"error": "Richiesta non autorizzata."}, "403 Forbidden")
    size = int(environ.get("CONTENT_LENGTH") or 0)
    if not 0 < size <= MAX_REQUEST_BODY:
        raise InputError("Richiesta vuota o file troppo grande.")
    data = json.loads(environ["wsgi.input"].read(size))
    if not isinstance(data, dict):
        raise InputError("Richiesta non valida.")
    with database() as db:
        if path == "/api/bank":
            db.execute("BEGIN")
            if "xls" in data:
                return result(xls_preview(db, data["xls"]))
            return result(bank_preview(db, clean_text(data.get("raw"), MAX_BANK_FILE, required=True)))
        db.execute("BEGIN IMMEDIATE")
        if path == "/api/bank/import":
            return result(import_movements(db, data))
        if path == "/api/expense":
            save_expense(db, data)
        elif path == "/api/payment":
            save_payment(db, data)
        elif path == "/api/person":
            save_person(db, data)
        else:
            table = {"expense": "expenses", "payment": "payments"}.get(str(data.get("kind")))
            if not table:
                raise InputError("Elemento non valido.")
            db.execute(f"DELETE FROM {table} WHERE id = ?", (positive_int(data.get("id")),))
        return result({"ok": True})


def result(payload, status="200 OK"):
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode()


def application(environ, start_response):
    allowed_ip = "127.0.0.1" if DEMO else "172.30.32.2"
    if environ.get("REMOTE_ADDR") != allowed_ip:
        status, mime, body = result({"error": "Accedi dal menu di Home Assistant."}, "403 Forbidden")
    elif ALLOWED_USER and not DEMO and environ.get("HTTP_X_REMOTE_USER_NAME") != ALLOWED_USER:
        status, mime, body = result({"error": "Utente Home Assistant non autorizzato."}, "403 Forbidden")
    else:
        return serve(environ, start_response)
    return send(start_response, status, mime, body)


def lan_application(environ, start_response):
    # This application is served exclusively over the gateway's private Unix socket.
    if environ["REQUEST_METHOD"] == "POST":
        expected = environ.get("HTTP_X_RENDICONTI_ORIGIN")
        if not expected or environ.get("HTTP_ORIGIN") != expected:
            return send(start_response, *result({"error": "Origine non autorizzata."}, "403 Forbidden"),
                        direct=True)
    return serve(environ, start_response, direct=True)


def http_application(network, address, credential_digest):
    host = f"{address}:{LAN_HTTP_PORT}"
    expected_origin = f"http://{host}"

    def application(environ, start_response):
        remote = environ.get("REMOTE_ADDR", "")
        try:
            client_allowed = ipaddress.IPv4Address(remote) in network
        except ValueError:
            client_allowed = False
        if not client_allowed or environ.get("HTTP_HOST") != host:
            return send(start_response, *result({"error": "Accesso LAN non autorizzato."}, "403 Forbidden"),
                        direct=True)
        scheme, _, credentials = environ.get("HTTP_AUTHORIZATION", "").partition(" ")
        supplied = hashlib.sha256(credentials.encode("latin-1")).hexdigest()
        if scheme.lower() != "basic" or not hmac.compare_digest(supplied, credential_digest):
            return send(start_response, *result({"error": "Accedi a Rendiconti."}, "401 Unauthorized"),
                        direct=True, extra_headers=[("WWW-Authenticate", 'Basic realm="Rendiconti familiari"')])
        environ["HTTP_X_RENDICONTI_ORIGIN"] = expected_origin
        return lan_application(environ, start_response)

    return application


def serve(environ, start_response, direct=False):
    try:
        status, mime, body = route(environ)
    except (InputError, csv.Error) as error:
        status, mime, body = result({"error": str(error)}, "400 Bad Request")
    except (ValueError, UnicodeError, RecursionError):
        status, mime, body = result({"error": "Formato della richiesta non valido."}, "400 Bad Request")
    except sqlite3.IntegrityError as error:
        message = {
            "UNIQUE constraint failed: expenses.source_key": "Questo movimento è già registrato.",
            "UNIQUE constraint failed: people.name": "Esiste già una persona con questo nome.",
            "FOREIGN KEY constraint failed": "La persona selezionata non è disponibile.",
        }.get(str(error), "Impossibile salvare. Controlla i valori inseriti.")
        status, mime, body = result({"error": message}, "409 Conflict")
    return send(start_response, status, mime, body, direct=direct)


def send(start_response, status, mime, body, direct=False, extra_headers=()):
    frame_ancestors = "'none'" if direct else "'self'"
    start_response(status, [
        *extra_headers,
        ("Content-Type", mime), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", f"default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors {frame_ancestors}; form-action 'self'"),
    ])
    return [body]



def main():
    init_db()
    bind = "127.0.0.1" if DEMO else "0.0.0.0"
    port = int(os.environ.get("RENDICONTI_PORT", "8099")) if DEMO else 8099
    socket_map = {}
    limits = {
        "channel_timeout": 20, "cleanup_interval": 5, "max_request_header_size": 16_384,
        "max_request_body_size": MAX_REQUEST_BODY, "expose_tracebacks": False,
        "clear_untrusted_proxy_headers": True,
    }
    ingress = create_server(application, map=socket_map, listen=f"{bind}:{port}",
                            threads=6, connection_limit=64, **limits)
    http_address = os.environ.get("RENDICONTI_HTTP_ADDRESS")
    if http_address and not DEMO:
        try:
            create_server(
                http_application(ipaddress.IPv4Network(os.environ["RENDICONTI_HTTP_NETWORK"]),
                                 http_address, os.environ["RENDICONTI_HTTP_CREDENTIAL_DIGEST"]),
                map=socket_map, listen=f"0.0.0.0:{LAN_HTTP_PORT}", threads=4,
                connection_limit=32, **limits,
            )
        except (KeyError, ValueError, OSError) as error:
            print(f"Accesso HTTP LAN disattivato: {error}", file=sys.stderr)
    gateway = None
    runtime = os.environ.get("RENDICONTI_HTTPS_RUNTIME")
    if runtime and not DEMO:
        try:
            gateway = start_gateway(runtime)
            create_server(
                lan_application, map=socket_map, unix_socket=runtime + "/backend.sock",
                unix_socket_perms="600", threads=4, connection_limit=64, **limits,
            )
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            if gateway is not None:
                gateway.terminate()
                gateway.wait(timeout=5)
                gateway = None
            print(f"Accesso HTTPS LAN disattivato: {error}", file=sys.stderr)
    try:
        ingress.run()
    finally:
        if gateway is not None and gateway.poll() is None:
            gateway.terminate()
            gateway.wait(timeout=5)


if __name__ == "__main__":
    main()

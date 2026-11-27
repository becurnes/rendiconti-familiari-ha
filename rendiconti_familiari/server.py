import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIServer, make_server

ROOT = Path(__file__).resolve().parent
DEMO = os.environ.get("RENDICONTI_DEMO") == "1"
DATA = Path(os.environ.get("RENDICONTI_DATA", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "rendiconti.sqlite3"
MAX_CENTS = 99_999_999
OPTIONS = DATA / "options.json"
ALLOWED_USER = json.loads(OPTIONS.read_text()).get("utente_autorizzato", "").strip() if OPTIONS.exists() else ""


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
        SELECT id, day, person_id, cents, note FROM payments
        WHERE month = ? ORDER BY day, id
    """, (month,))
    months = [row["month"] for row in db.execute("""
        SELECT month FROM expenses UNION SELECT month FROM payments ORDER BY month DESC
    """)]
    return {"people": people, "expenses": expenses, "payments": payments, "months": months}


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


def bank_date(value):
    value = value.strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Data non riconosciuta")


def bank_preview(db, raw):
    for delimiter in ("\t", ";", ","):
        records = csv.reader(io.StringIO(raw.lstrip("\ufeff")), delimiter=delimiter)
        for _, record in zip(range(35), records):
            headers = [normalized(cell) for cell in record]
            mapping = {
                field: next((i for i, cell in enumerate(headers) if cell in names), None)
                for field, names in BANK_HEADERS.items()
            }
            if (mapping["day"] is not None and mapping["description"] is not None
                    and (mapping["amount"] is not None or mapping["debit"] is not None)):
                return collect_movements(db, records, mapping)
    raise InputError("Intestazioni non riconosciute. Usa Data, Descrizione, Importo (uscite con segno meno), oppure Data, Descrizione, Uscite.")


def collect_movements(db, records, mapping):
    already_imported = {row[0] for row in db.execute(
        "SELECT source_key FROM expenses WHERE source_key IS NOT NULL"
    )}
    movements, repeats = [], {}
    skipped = 0
    for record in records:
        if not any(cell.strip() for cell in record):
            continue
        def field(name):
            index = mapping[name]
            return record[index].strip() if index is not None and index < len(record) else ""
        raw_amount = field("debit" if mapping["debit"] is not None else "amount")
        if not raw_amount and mapping["debit"] is not None:
            continue
        try:
            signed = bank_amount(raw_amount)
            sign = normalized(field("sign"))
            if mapping["debit"] is not None or sign in {"d", "dare", "debito", "uscita", "addebito"} or field("sign") == "-":
                signed = -abs(signed)
            if signed >= 0 or sign in {"a", "avere", "credito", "entrata", "accredito"}:
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
                          "key": key, "imported": key in already_imported})
        if len(movements) > 2000:
            raise InputError("Il file contiene più di 2.000 uscite. Dividilo in più periodi.")
    return {"movements": movements, "skipped": skipped}


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


def save_payment(db, data):
    values = (valid_month(data.get("month")), valid_day(data.get("day")),
              positive_int(data.get("person_id")), positive_int(data.get("cents"), MAX_CENTS),
              clean_text(data.get("note", ""), 500))
    payment_id = data.get("id")
    if payment_id is None:
        db.execute("INSERT INTO payments(month, day, person_id, cents, note) VALUES (?, ?, ?, ?, ?)", values)
    elif db.execute("UPDATE payments SET month=?, day=?, person_id=?, cents=?, note=? WHERE id=?",
                    (*values, positive_int(payment_id))).rowcount == 0:
        raise InputError("Il versamento non esiste più.")


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
    with database() as db:
        if method == "GET" and path == "/api/month":
            month = parse_qs(environ["QUERY_STRING"]).get("month", [None])[0]
            db.execute("BEGIN")
            return result(month_data(db, valid_month(month)))
        if method == "POST" and path in {
            "/api/expense", "/api/payment", "/api/person", "/api/remove", "/api/bank"
        }:
            if (environ.get("HTTP_X_RENDICONTI") != "1"
                    or environ.get("CONTENT_TYPE", "").partition(";")[0] != "application/json"):
                return result({"error": "Richiesta non autorizzata."}, "403 Forbidden")
            size = int(environ.get("CONTENT_LENGTH") or 0)
            if not 0 < size <= 2_500_000:
                raise InputError("Richiesta vuota o file troppo grande.")
            data = json.loads(environ["wsgi.input"].read(size))
            if not isinstance(data, dict):
                raise InputError("Richiesta non valida.")
            if path == "/api/bank":
                return result(bank_preview(db, clean_text(data.get("raw"), 1_000_000, required=True)))
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
    return result({"error": "Pagina non trovata."}, "404 Not Found")


def result(payload, status="200 OK"):
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode()


def application(environ, start_response):
    allowed_ip = "127.0.0.1" if DEMO else "172.30.32.2"
    if environ.get("REMOTE_ADDR") != allowed_ip:
        status, mime, body = result({"error": "Accedi dal menu di Home Assistant."}, "403 Forbidden")
    elif ALLOWED_USER and not DEMO and environ.get("HTTP_X_REMOTE_USER_NAME") != ALLOWED_USER:
        status, mime, body = result({"error": "Utente Home Assistant non autorizzato."}, "403 Forbidden")
    else:
        try:
            status, mime, body = route(environ)
        except (InputError, csv.Error) as error:
            status, mime, body = result({"error": str(error)}, "400 Bad Request")
        except (ValueError, UnicodeError):
            status, mime, body = result({"error": "Formato della richiesta non valido."}, "400 Bad Request")
        except sqlite3.IntegrityError as error:
            message = {
                "UNIQUE constraint failed: expenses.source_key": "Questo movimento è già registrato.",
                "UNIQUE constraint failed: people.name": "Esiste già una persona con questo nome.",
                "FOREIGN KEY constraint failed": "La persona selezionata non è disponibile.",
            }.get(str(error), "Impossibile salvare. Controlla i valori inseriti.")
            status, mime, body = result({"error": message}, "409 Conflict")
    start_response(status, [
        ("Content-Type", mime), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'"),
    ])
    return [body]


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


if __name__ == "__main__":
    init_db()
    bind = "127.0.0.1" if DEMO else "0.0.0.0"
    port = int(os.environ.get("RENDICONTI_PORT", "8099")) if DEMO else 8099
    with make_server(bind, port, application, server_class=ThreadedServer) as server:
        print(f"Rendiconti in ascolto sulla porta {port}")
        server.serve_forever()

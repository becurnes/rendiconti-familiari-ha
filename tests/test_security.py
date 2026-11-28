import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "rendiconti_familiari"
sys.path.insert(0, str(SOURCE))
sandbox = tempfile.TemporaryDirectory()
os.environ["RENDICONTI_DATA"] = sandbox.name

import bootstrap
import lan_https
import server


class IngressTest(unittest.TestCase):
    def request(self, address="172.30.32.2", user="titolare", path="/api/month"):
        result = []
        reply = server.application({
            "REMOTE_ADDR": address, "HTTP_X_REMOTE_USER_NAME": user,
            "REQUEST_METHOD": "GET", "PATH_INFO": path,
            "QUERY_STRING": "month=2026-10", "wsgi.input": io.BytesIO(),
        }, lambda status, headers: result.append((status, dict(headers))))
        return *result[0], b"".join(reply)

    def test_only_supervisor_and_configured_user(self):
        server.init_db()
        with patch.object(server, "ALLOWED_USER", "titolare"):
            status, headers, body = self.request()
            self.assertEqual(status, "200 OK")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(len(json.loads(body)["people"]), 2)
            self.assertEqual(self.request(address="192.0.2.1")[0], "403 Forbidden")
            self.assertEqual(self.request(user="")[0], "403 Forbidden")
            self.assertEqual(self.request(path="/api/session")[0], "404 Not Found")

    def test_transport_body_limit(self):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        with tempfile.TemporaryDirectory() as data, subprocess.Popen(
            [sys.executable, "-B", str(SOURCE / "server.py")],
            env={**os.environ, "RENDICONTI_DATA": data,
                 "RENDICONTI_DEMO": "1", "RENDICONTI_PORT": str(port)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                for _ in range(60):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except ConnectionRefusedError:
                        self.assertIsNone(process.poll())
                        time.sleep(0.05)
                else:
                    self.fail("Waitress non ha avviato il listener di prova.")
                client = HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    client.request("GET", "/api/month?month=2026-10")
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    client.request("POST", "/api/bank",
                                   body=iter([b'{"raw":"Data;', b'Descrizione;Importo"}']),
                                   headers={"Content-Type": "application/json", "X-Rendiconti": "1"},
                                   encode_chunked=True)
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    client.request("POST", "/api/bank", headers={
                        "Content-Length": str(server.MAX_REQUEST_BODY + 1),
                        "Content-Type": "application/json", "X-Rendiconti": "1",
                    })
                    self.assertEqual(client.getresponse().status, 413)
                finally:
                    client.close()
            finally:
                process.terminate()


class LanTest(unittest.TestCase):
    def test_optional_explicit_private_network(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            runtime.mkdir()
            (runtime / "previous-key").write_text("fixture")
            self.assertEqual(lan_https.prepare_gateway({}, 0, 0, Path(directory), runtime), "")
            self.assertFalse(runtime.exists())
            valid = {"lan_https": True, "lan_hostname": "rendiconti.example.test", "lan_ipv4": "192.168.1.0/24"}
            self.assertEqual(lan_https.network_settings(valid)[0], "rendiconti.example.test")
            for network in ("0.0.0.0/0", "10.0.0.0/8", "192.168.1.2/24", "192.0.2.0/24", "fd00::/64"):
                with self.subTest(network=network), self.assertRaises(ValueError):
                    lan_https.network_settings({**valid, "lan_ipv4": network})
            with self.assertRaisesRegex(ValueError, "lan-fullchain.pem"):
                lan_https.prepare_gateway(valid, 0, 0, Path(directory), runtime)

    def test_lan_rejects_old_banking_route_and_checks_post_origin(self):
        server.init_db()
        metadata = {
            "HTTP_X_RENDICONTI_ORIGIN": "https://rendiconti.example.test:8443",
            "QUERY_STRING": "month=2026-10", "CONTENT_TYPE": "application/json", "HTTP_X_RENDICONTI": "1",
        }

        def request(path, method, origin="", payload=b""):
            headers = []
            response = server.lan_application({
                **metadata, "PATH_INFO": path, "REQUEST_METHOD": method,
                "HTTP_ORIGIN": origin, "CONTENT_LENGTH": str(len(payload)), "wsgi.input": io.BytesIO(payload),
            }, lambda status, fields: headers.append((status, dict(fields))))
            return *headers[0], json.loads(b"".join(response))

        status, headers, payload = request("/api/month", "GET")
        self.assertEqual(status, "200 OK")
        self.assertNotIn("openBanking", payload)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        valid_origin = metadata["HTTP_X_RENDICONTI_ORIGIN"]
        self.assertEqual(request("/api/open-banking", "POST", valid_origin,
                                 b'{"action":"status"}')[0], "404 Not Found")
        csv_body = b'{"raw":"Data;Descrizione;Importo"}'
        self.assertEqual(request("/api/bank", "POST", "https://other.example.test", csv_body)[0], "403 Forbidden")
        self.assertEqual(request("/api/bank", "POST", valid_origin, csv_body)[0], "200 OK")


class LedgerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = patch.object(server, "DB", Path(temporary.name) / "test.sqlite3")
        database.start()
        self.addCleanup(database.stop)
        server.init_db()

    def test_preview_and_batch_import(self):
        sample = (
            "Data operazione;Descrizione;Entrate;Uscite;Stato\n"
            "10 novembre 2026;Spesa;;-2,01;Contabilizzato\n"
            "10 novembre 2026;Spesa;;-2,01;Contabilizzato\n"
            "11 novembre 2026;In arrivo;;-3,20;Da contabilizzare\n"
            "12 novembre 2026;Bonifico;30,00;-;Contabilizzato\n"
            ";Totale;;-7,22;"
        )
        with server.database() as db:
            server.save_person(db, {"name": "Persona esterna"})
            preview = server.bank_preview(db, sample)
            self.assertEqual((preview["pending"], preview["skipped"]), (1, 0))
            first, second = preview["movements"]
            self.assertNotEqual(first["key"], second["key"])
            self.assertEqual(server.month_data(db, "2026-11")["expenses"], [])
            server.import_movements(db, {"month": "2026-11", "movements": [
                {**first, "people": [3]}, {**second, "people": [1, 3]},
            ]})
            expenses = server.month_data(db, "2026-11")["expenses"]
            self.assertEqual(expenses[0]["shares"], [{"person_id": 3, "cents": 201}])
            self.assertEqual(expenses[1]["shares"], [
                {"person_id": 1, "cents": 101}, {"person_id": 3, "cents": 100},
            ])
            self.assertTrue(all(item["imported"] for item in server.bank_preview(db, sample)["movements"]))

    def test_payment_allocation_preserves_the_month_of_collection(self):
        with server.database() as db:
            for month, cents in (("2026-09", 1250), ("2026-10", 1000)):
                server.save_expense(db, {
                    "month": month, "day": month + "-01", "description": "Utenza",
                    "cents": cents, "people": [1],
                })
            server.save_payment(db, {
                "month": "2026-11", "day": "2026-11-20", "person_id": 1,
                "cents": 3000, "arrears_target": "all",
            })
            current = server.month_data(db, "2026-11")
            self.assertEqual(current["arrears"], [])
            self.assertEqual(current["payments"][0]["cents"], 3000)
            self.assertEqual(current["credits"][0]["cents"], 750)
            self.assertEqual(current["payments"][0]["allocations"], [
                {"month": "2026-09", "cents": 1250}, {"month": "2026-10", "cents": 1000},
            ])
            old_credit = server.month_data(db, "2026-10")["credits"][0]
            self.assertEqual((old_credit["recorded_month"], old_credit["day"]), ("2026-11", "2026-11-20"))
            db.execute("DELETE FROM payments WHERE id = ?", (current["payments"][0]["id"],))
            self.assertEqual([row["cents"] for row in server.prior_balances(db, "2026-11")], [1250, 1000])


class VolumeTest(unittest.TestCase):
    def test_preserves_existing_content_and_hardens_modes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(os, "fchown") as chown:
            path = Path(directory)
            (path / "options.json").write_text('{"utente_autorizzato":"titolare"}')
            (path / "rendiconti.sqlite3").write_bytes(b"volume di prova")
            for name in bootstrap.LEGACY_BANK_FILES:
                (path / name).write_text("dati di prova")
            self.assertEqual(bootstrap.prepare_volume(path)["utente_autorizzato"], "titolare")
            self.assertTrue(all(not (path / name).exists() for name in bootstrap.LEGACY_BANK_FILES))
            self.assertEqual((path / "rendiconti.sqlite3").read_bytes(), b"volume di prova")
            self.assertEqual((path / "rendiconti.sqlite3").stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            self.assertEqual(chown.call_count, 2)


if __name__ == "__main__":
    unittest.main()

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
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
import openbanking
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


class BankTest(unittest.TestCase):
    def test_busy_connection_keeps_status_available(self):
        with tempfile.TemporaryDirectory() as directory:
            bank = openbanking.OpenBanking(Path(directory))
            started = threading.Event()
            release = threading.Event()

            def busy(*args):
                started.set()
                release.wait(3)
                return "completed"

            with patch.object(bank, "run_action", side_effect=busy):
                worker = threading.Thread(target=bank.dispatch, args=("movements", {}))
                worker.start()
                try:
                    self.assertTrue(started.wait(2))
                    self.assertFalse(bank.dispatch("status", {})["connected"])
                    with self.assertRaises(openbanking.BankBusy):
                        bank.dispatch("disconnect", {})
                finally:
                    release.set()
                    worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_bank_transport_deadline_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            bank = openbanking.OpenBanking(Path(directory))
            with patch.object(openbanking, "openssl", return_value=b"signature"), \
                 patch.object(openbanking.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess(
                    [], 0, b'{"code":"REVOKED_SESSION"}\n403', b'')
                with self.assertRaises(openbanking.BankError) as error:
                    bank.api({"application": "demo"}, "POST", "/sessions", {"code": "test-code"},
                             deadline=time.monotonic() + 2)
                self.assertTrue(error.exception.expired)
                self.assertLessEqual(run.call_args.kwargs["timeout"], 2)
                self.assertIn(b"test-code", run.call_args.kwargs["input"])
                self.assertNotIn("test-code", " ".join(run.call_args.args[0]))
                with self.assertRaises(openbanking.BankError):
                    bank.api({"application": "demo"}, "GET", "/aspsps",
                             deadline=time.monotonic() - 1)
                self.assertEqual(run.call_count, 1)


class VolumeTest(unittest.TestCase):
    def test_preserves_existing_content_and_hardens_modes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(os, "fchown") as chown:
            path = Path(directory)
            (path / "options.json").write_text('{"utente_autorizzato":"titolare"}')
            (path / "rendiconti.sqlite3").write_bytes(b"volume di prova")
            self.assertEqual(bootstrap.prepare_volume(path), "titolare")
            self.assertEqual((path / "rendiconti.sqlite3").read_bytes(), b"volume di prova")
            self.assertEqual((path / "rendiconti.sqlite3").stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            self.assertEqual(chown.call_count, 2)


if __name__ == "__main__":
    unittest.main()

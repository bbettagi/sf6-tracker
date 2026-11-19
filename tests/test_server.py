import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from sf6tracker import demo
from sf6tracker.db import Store
from sf6tracker.server import Tracker, make_handler


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(cls.tmp.name)
        cls.store.insert_matches(demo.generate(150, seed=11))
        cls.tracker = Tracker(cls.store, 0)
        handler = make_handler(cls.tracker)
        handler.log_message = lambda *args: None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.tracker.port = cls.port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": host or f"localhost:{self.port}", **(headers or {})}
        data = body if isinstance(body, (bytes, str)) or body is None else json.dumps(body)
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw
        return resp.status, dict(resp.getheaders()), payload

    def test_static_and_meta(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"SF6 Tracker", body)
        status, _, meta = self.request("GET", "/api/meta")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(meta["match_count"], 150)
        self.assertIn("Ken", meta["my_characters"])

    def test_path_traversal_blocked(self):
        status, _, _ = self.request("GET", "/../sf6tracker/server.py")
        self.assertEqual(status, 404)
        status, _, _ = self.request("GET", "/%2e%2e/data/config.json")
        self.assertEqual(status, 404)

    def test_stats_endpoint(self):
        status, _, data = self.request("GET", "/api/stats?tz=0&character=Ken")
        self.assertEqual(status, 200)
        self.assertEqual(data["rank"]["character"], "Ken")
        self.assertGreater(data["overview"]["summary"]["matches"], 0)

    def test_foreign_host_rejected(self):
        status, _, _ = self.request("GET", "/api/meta", host="evil.example:80")
        self.assertEqual(status, 403)

    def test_writes_need_app_header(self):
        body = {"my_character": "Ken", "opp_character": "Ryu", "result": "W"}
        status, _, _ = self.request("POST", "/api/matches", body)
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/matches", body, {"X-SF6-Tracker": "1"})
        self.assertEqual(status, 201)
        _, _, data = self.request("GET", "/api/matches")
        manual = [m for m in data["matches"] if m["source"] == "manual"]
        self.assertTrue(manual)
        status, _, _ = self.request("DELETE", f"/api/matches/{manual[0]['id']}", headers={"X-SF6-Tracker": "1"})
        self.assertEqual(status, 200)

    def test_bad_manual_match(self):
        status, _, data = self.request("POST", "/api/matches", {"my_character": "Ken", "result": "X"},
                                       {"X-SF6-Tracker": "1"})
        self.assertEqual(status, 400)
        self.assertIn("result", data["error"])

    def test_cookie_never_returned(self):
        self.request("POST", "/api/config", {"cookie": "buckler_id=secret", "sid": "https://www.streetfighter.com/6/buckler/profile/1000000001"},
                     {"X-SF6-Tracker": "1"})
        _, _, cfg = self.request("GET", "/api/config")
        self.assertTrue(cfg["cookie_set"])
        self.assertEqual(cfg["sid"], "1000000001")
        self.assertNotIn("cookie", cfg)
        self.assertNotIn("import_token", cfg)
        _, _, meta = self.request("GET", "/api/meta")
        self.assertNotIn("secret", json.dumps(meta))

    def test_collector_import_requires_token(self):
        payload = {"sid": demo.DEMO_SID, "replay_list": demo.generate_replays(5, seed=99)}
        for r in payload["replay_list"]:
            r["replay_id"] = "X" + r["replay_id"]
        origin = {"Origin": "https://www.streetfighter.com", "Content-Type": "text/plain"}
        status, headers, _ = self.request("POST", "/api/import", {**payload, "token": "wrong"}, origin)
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/import", payload, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        token = self.store.config()["import_token"]
        status, headers, rep = self.request("POST", "/api/import", {**payload, "token": token}, origin)
        self.assertEqual(status, 200)
        self.assertEqual(rep["added"], 5)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "https://www.streetfighter.com")
        status, headers, _ = self.request("OPTIONS", "/api/import", headers={
            "Origin": "https://www.streetfighter.com", "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")

    def test_collector_script_is_filled_in(self):
        status, _, data = self.request("GET", "/api/collector")
        self.assertEqual(status, 200)
        self.assertNotIn("__PORT__", data["script"])
        self.assertNotIn("__TOKEN__", data["script"])
        self.assertIn(str(self.port), data["script"])

    def test_sync_without_cookie_reports_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tracker = Tracker(Store(tmp.name), 0)
        tracker.store.update_config({"sid": "123456789"})
        from sf6tracker import buckler
        with self.assertRaises(buckler.AuthError):
            tracker.run_sync()
        self.assertEqual(tracker.store.recent_syncs()[0]["status"], "error")


if __name__ == "__main__":
    unittest.main()

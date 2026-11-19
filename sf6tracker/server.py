"""Local web server: JSON API plus the static dashboard."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import buckler, ranks, stats
from .db import Store

STATIC = Path(__file__).resolve().parent.parent / "static"
BUCKLER_ORIGIN = "https://www.streetfighter.com"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
APP_HEADER = "X-SF6-Tracker"
MAX_BODY = 50 * 1024 * 1024


class Tracker:
    """Shared state for the request handlers and the auto-sync thread."""

    def __init__(self, store: Store, port: int):
        self.store = store
        self.port = port
        self.sync_lock = threading.Lock()
        self.auto_sync_paused = ""

    def run_sync(self, source: str = "manual") -> dict:
        cfg = self.store.config()
        sid = buckler._int(cfg.get("sid"))
        if not sid:
            raise buckler.BucklerError("Set your Buckler user code first (the number in your "
                                       "Buckler profile URL).")
        if not self.sync_lock.acquire(blocking=False):
            raise buckler.BucklerError("A sync is already running.")
        try:
            rows, report = buckler.sync(sid, cfg.get("cookie", ""), self.store.known_replay_ids())
            report["added"] = self.store.insert_matches(rows)
            self.store.log_sync(f"sync ({source})", "ok", report["added"],
                                f"{report['pages']} page(s), {report['ranked']} ranked matches read")
            self.auto_sync_paused = ""
            return report
        except buckler.BucklerError as e:
            self.store.log_sync(f"sync ({source})", "error", 0, str(e))
            if isinstance(e, (buckler.AuthError, buckler.BlockedError)):
                self.auto_sync_paused = str(e)
            raise
        finally:
            self.sync_lock.release()

    def run_import(self, data, source: str) -> dict:
        cfg = self.store.config()
        sid = buckler._int(cfg.get("sid"))
        rows, report = buckler.parse_import(data, sid)
        report["added"] = self.store.insert_matches(rows)
        if not sid and report.get("sid"):
            self.store.update_config({"sid": str(report["sid"])})
        self.store.log_sync(source, "ok", report["added"],
                            f"{report['found']} matches in file, {report['ranked']} ranked")
        return report

    def auto_sync_loop(self):
        last = 0.0
        while True:
            time.sleep(30)
            cfg = self.store.config()
            minutes = int(cfg.get("auto_sync_minutes") or 0)
            if minutes <= 0 or self.auto_sync_paused or not cfg.get("cookie") or not cfg.get("sid"):
                continue
            if time.time() - last < minutes * 60:
                continue
            last = time.time()
            try:
                self.run_sync("auto")
            except buckler.BucklerError:
                pass
            except Exception:  # keep the thread alive no matter what
                traceback.print_exc()


def _int_param(q: dict, key: str) -> int | None:
    try:
        return int(q[key][0])
    except (KeyError, ValueError, IndexError):
        return None


def make_handler(tracker: Tracker):
    store = tracker.store

    class Handler(BaseHTTPRequestHandler):
        server_version = "SF6Tracker/1.0"

        def log_message(self, fmt, *args):
            if self.path.startswith("/api/"):
                super().log_message(fmt, *args)

        # ---- plumbing ----------------------------------------------------------
        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status: int = 200, extra: dict | None = None):
            self._send(status, json.dumps(obj).encode(), "application/json", extra)

        def _error(self, status: int, message: str, extra: dict | None = None):
            self._json({"error": message}, status, extra)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("Request body too large.")
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").strip()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            return name in LOCAL_HOSTS

        def _cors(self) -> dict:
            if self.headers.get("Origin") == BUCKLER_ORIGIN:
                return {"Access-Control-Allow-Origin": BUCKLER_ORIGIN, "Vary": "Origin"}
            return {}

        # ---- verbs -------------------------------------------------------------
        def do_OPTIONS(self):
            if self.headers.get("Origin") == BUCKLER_ORIGIN and self.path.startswith("/api/import"):
                self._send(204, b"", "text/plain", {
                    **self._cors(),
                    "Access-Control-Allow-Methods": "POST",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Max-Age": "600",
                })
            else:
                self._send(403, b"", "text/plain")

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def _dispatch(self, method: str):
            if not self._host_ok():
                return self._error(403, "This tracker only answers on localhost.")
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            try:
                if method == "GET" and not path.startswith("/api/"):
                    return self._static(path)
                if method != "GET" and not (path == "/api/import" and method == "POST"):
                    if self.headers.get(APP_HEADER) != "1":
                        return self._error(403, "Missing app header.")
                route = ROUTES.get((method, re.sub(r"/\d+$", "/:id", path)))
                if route is None:
                    return self._error(404, "Not found.")
                return route(self, path, query)
            except buckler.BucklerError as e:
                return self._error(400, str(e), self._cors())
            except (ValueError, KeyError, TypeError) as e:
                return self._error(400, f"Bad request: {e}", self._cors())
            except Exception as e:  # pragma: no cover - surface unexpected errors to the UI
                traceback.print_exc()
                return self._error(500, f"Server error: {e}")

        def _static(self, path: str):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (STATIC / rel).resolve()
            if STATIC not in target.parents or not target.is_file():
                return self._error(404, "Not found.")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        # ---- API -----------------------------------------------------------------
        def api_meta(self, path, query):
            cfg = store.config()
            matches = store.all_matches()
            return self._json({
                "match_count": len(matches),
                "first": matches[0]["played_at"] if matches else None,
                "last": matches[-1]["played_at"] if matches else None,
                "my_characters": sorted({m["my_character"] for m in matches}),
                "all_characters": sorted(set(ranks.CHARACTERS)
                                         | {m["my_character"] for m in matches}
                                         | {m["opp_character"] for m in matches}),
                "sources": {s: sum(1 for m in matches if m["source"] == s) for s in ("buckler", "manual")},
                "config": _public_config(cfg),
                "auto_sync_paused": tracker.auto_sync_paused,
                "syncs": store.recent_syncs(),
                "port": tracker.port,
            })

        def api_stats(self, path, query):
            data = stats.compute(
                store.all_matches(), store.config(),
                start=_int_param(query, "from"), end=_int_param(query, "to"),
                character=(query.get("character") or [None])[0] or None,
                tz_offset=_int_param(query, "tz") or 0,
            )
            return self._json(data)

        def api_matches(self, path, query):
            cfg = store.config()
            matches = store.all_matches()
            detection = stats.detect_timing(matches)
            timing = cfg["lp_timing"] if cfg.get("lp_timing") in ("pre", "post") else detection["timing"]
            stats.annotate(matches, timing)
            start, end = _int_param(query, "from"), _int_param(query, "to")
            character = (query.get("character") or [None])[0] or None
            rows = [m for m in matches
                    if (start is None or m["played_at"] >= start)
                    and (end is None or m["played_at"] < end)
                    and (character is None or m["my_character"] == character)]
            rows.reverse()
            return self._json({"matches": rows})

        def api_add_match(self, path, query):
            body = self._body()
            result = str(body.get("result", "")).upper()
            if result not in ("W", "L", "D"):
                raise ValueError("result must be W, L or D")
            mine = str(body.get("my_character") or "").strip()
            theirs = str(body.get("opp_character") or "").strip()
            if not mine or not theirs:
                raise ValueError("Both characters are required.")

            def num(key):
                v = body.get(key)
                return None if v in (None, "") else int(v)

            row = {
                "source": "manual", "replay_id": None,
                "played_at": num("played_at") or int(time.time()),
                "my_character": mine, "opp_character": theirs, "result": result,
                "my_lp": num("my_lp"), "my_mr": num("my_mr"),
                "opp_lp": num("opp_lp"), "opp_mr": num("opp_mr"),
                "rounds_won": num("rounds_won"), "rounds_lost": num("rounds_lost"),
                "opp_name": (body.get("opp_name") or "").strip() or None,
                "notes": (body.get("notes") or "").strip() or None,
                "rating_timing": "post",
            }
            store.insert_matches([row])
            return self._json({"ok": True}, 201)

        def api_delete_match(self, path, query):
            match_id = int(path.rsplit("/", 1)[1])
            if not store.delete_match(match_id):
                return self._error(404, "No such match.")
            return self._json({"ok": True})

        def api_get_config(self, path, query):
            return self._json(_public_config(store.config()))

        def api_set_config(self, path, query):
            body = self._body()
            changes = {}
            if "sid" in body:
                sid = str(body["sid"]).strip()
                m = re.search(r"(\d{6,})", sid)   # accept a pasted profile URL too
                changes["sid"] = m.group(1) if m else ""
            if "cookie" in body:
                changes["cookie"] = str(body["cookie"]).strip()
            if "auto_sync_minutes" in body:
                changes["auto_sync_minutes"] = max(0, int(body["auto_sync_minutes"]))
            if "lp_timing" in body:
                if body["lp_timing"] not in ("auto", "pre", "post"):
                    raise ValueError("lp_timing must be auto, pre or post")
                changes["lp_timing"] = body["lp_timing"]
            if "session_gap_minutes" in body:
                changes["session_gap_minutes"] = min(600, max(5, int(body["session_gap_minutes"])))
            tracker.auto_sync_paused = ""
            return self._json(_public_config(store.update_config(changes)))

        def api_sync(self, path, query):
            return self._json(tracker.run_sync("button"))

        def api_import(self, path, query):
            body = self._body()
            origin = self.headers.get("Origin")
            from_app = self.headers.get(APP_HEADER) == "1" and origin in (None, f"http://{self.headers.get('Host')}")
            if not from_app:
                token = body.get("token") if isinstance(body, dict) else None
                if origin != BUCKLER_ORIGIN or token != store.config()["import_token"]:
                    return self._error(403, "Import refused: run the collector copied from this "
                                            "tracker's Sync tab.", self._cors())
            report = tracker.run_import(body, "browser collector" if not from_app else "file import")
            return self._json(report, extra=self._cors())

        def api_collector(self, path, query):
            cfg = store.config()
            source = (STATIC / "collector.js").read_text()
            source = (source.replace("__PORT__", str(tracker.port))
                            .replace("__TOKEN__", cfg["import_token"])
                            .replace("__SID__", json.dumps(cfg.get("sid") or "")))
            return self._json({"script": source})

    ROUTES = {
        ("GET", "/api/meta"): Handler.api_meta,
        ("GET", "/api/stats"): Handler.api_stats,
        ("GET", "/api/matches"): Handler.api_matches,
        ("POST", "/api/matches"): Handler.api_add_match,
        ("DELETE", "/api/matches/:id"): Handler.api_delete_match,
        ("GET", "/api/config"): Handler.api_get_config,
        ("POST", "/api/config"): Handler.api_set_config,
        ("POST", "/api/sync"): Handler.api_sync,
        ("POST", "/api/import"): Handler.api_import,
        ("GET", "/api/collector"): Handler.api_collector,
    }
    return Handler


def _public_config(cfg: dict) -> dict:
    """Config for the browser. The cookie itself never leaves the server."""
    out = {k: v for k, v in cfg.items() if k not in ("cookie", "import_token")}
    out["cookie_set"] = bool(cfg.get("cookie"))
    return out


def serve(data_dir: str, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False):
    store = Store(data_dir)
    tracker = Tracker(store, port)
    httpd = ThreadingHTTPServer((host, port), make_handler(tracker))
    threading.Thread(target=tracker.auto_sync_loop, daemon=True).start()
    url = f"http://localhost:{port}/"
    print(f"SF6 Tracker running at {url}  (data in {store.data_dir})")
    print("Press Ctrl+C to stop.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()

"""Command line: serve the dashboard, sync from Buckler, import a file, or load demo data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import buckler
from .db import Store

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sf6tracker", description="Street Fighter 6 ranked tracker")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="data folder (default: ./data)")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the dashboard (default)")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--open", action="store_true", help="open the dashboard in a browser")

    sub.add_parser("sync", help="pull new ranked matches from Buckler using the saved cookie")

    p_import = sub.add_parser("import", help="import a Buckler battle log JSON file")
    p_import.add_argument("file")

    p_demo = sub.add_parser("demo", help="fill a data folder with generated demo matches")
    p_demo.add_argument("--matches", type=int, default=600)

    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        from .server import serve
        serve(args.data, getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8765),
              getattr(args, "open", False))
    elif command == "sync":
        from .server import Tracker
        tracker = Tracker(Store(args.data), 0)
        try:
            report = tracker.run_sync("cli")
        except buckler.BucklerError as e:
            sys.exit(f"Sync failed: {e}")
        print(f"Read {report['pages']} page(s): {report['added']} new ranked match(es) added.")
    elif command == "import":
        from .server import Tracker
        tracker = Tracker(Store(args.data), 0)
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        try:
            report = tracker.run_import(data, "file import (cli)")
        except buckler.BucklerError as e:
            sys.exit(f"Import failed: {e}")
        print(f"{report['found']} matches in file, {report['ranked']} ranked, "
              f"{report['added']} new added.")
    elif command == "demo":
        from .demo import generate
        store = Store(args.data)
        if store.match_count():
            sys.exit(f"{store.data_dir} already has matches; pick an empty folder with --data.")
        rows = generate(args.matches)
        store.insert_matches(rows)
        store.update_config({"sid": "1000000001"})
        store.log_sync("demo data", "ok", len(rows), "Generated demo matches")
        print(f"Added {len(rows)} demo matches to {store.data_dir}.")


if __name__ == "__main__":
    main()

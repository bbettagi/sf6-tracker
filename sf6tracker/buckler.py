"""Reading ranked matches from Capcom's Buckler's Boot Camp battle log.

Buckler has no public API. Its pages are a Next.js app whose data sits in a
``__NEXT_DATA__`` script tag; the battle log lives at
``props.pageProps.replay_list``. Each entry looks like::

    {"replay_id": "...", "uploaded_at": 1700000000, "replay_battle_type": 1,
     "replay_battle_type_name": "Ranked Match",
     "player1_info": {"player": {"short_id": 123, "fighter_id": "Name", ...},
                      "playing_character_name": "Ryu", "battle_input_type": 0,
                      "league_point": 12000, "master_rating": 0,
                      "league_rank": 24, "round_results": [1, 0, 6]},
     "player2_info": {...}}
"""

from __future__ import annotations

import gzip
import json
import random
import re
import time
import urllib.error
import urllib.request

from .ranks import DRAW_CODE

BUCKLER = "https://www.streetfighter.com/6/buckler"
RANKED_TYPE = 1
MAX_PAGES = 10
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class BucklerError(Exception):
    """A sync problem worth showing to the user as-is."""


class AuthError(BucklerError):
    pass


class BlockedError(BucklerError):
    pass


# ---- parsing ------------------------------------------------------------------

def find_replays(data) -> list[dict]:
    """Collect every replay object from any JSON shape we accept.

    Accepts a raw ``__NEXT_DATA__`` blob, a ``_next/data`` page, the collector's
    payload, a list of pages, or a plain list of replays.
    """
    found: dict[str, dict] = {}

    def walk(node):
        if isinstance(node, dict):
            if "replay_id" in node and "player1_info" in node and "player2_info" in node:
                found.setdefault(str(node["replay_id"]), node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return list(found.values())


def guess_sid(replays: list[dict]) -> int | None:
    """The short ID present in every replay is the owner of the battle log."""
    counts: dict[int, int] = {}
    for r in replays:
        seen = set()
        for side in ("player1_info", "player2_info"):
            sid = _int((r.get(side) or {}).get("player", {}).get("short_id"))
            if sid is not None and sid not in seen:
                seen.add(sid)
                counts[sid] = counts.get(sid, 0) + 1
    full = [sid for sid, n in counts.items() if n == len(replays)]
    return full[0] if len(full) == 1 else None


def is_ranked(replay: dict) -> bool:
    if _int(replay.get("replay_battle_type")) == RANKED_TYPE:
        return True
    name = str(replay.get("replay_battle_type_name") or "").upper()
    return "RANK" in name


def parse_replay(replay: dict, my_sid: int) -> dict | None:
    """Turn one Buckler replay into a match row from my point of view."""
    p1, p2 = replay.get("player1_info") or {}, replay.get("player2_info") or {}
    if _int(p1.get("player", {}).get("short_id")) == my_sid:
        me, opp = p1, p2
    elif _int(p2.get("player", {}).get("short_id")) == my_sid:
        me, opp = p2, p1
    else:
        return None

    my_rounds = [_int(c) or 0 for c in (me.get("round_results") or [])]
    opp_rounds = [_int(c) or 0 for c in (opp.get("round_results") or [])]
    won = sum(1 for c in my_rounds if c not in (0, DRAW_CODE))
    lost = sum(1 for c in opp_rounds if c not in (0, DRAW_CODE))
    result = "W" if won > lost else "L" if lost > won else "D"

    played_at = _int(replay.get("uploaded_at")) or 0
    if played_at > 10**12:   # milliseconds
        played_at //= 1000

    return {
        "source": "buckler",
        "replay_id": str(replay["replay_id"]),
        "played_at": played_at,
        "my_character": _character(me),
        "my_input_type": _int(me.get("battle_input_type")),
        "my_lp": _rating(me.get("league_point")),
        "my_mr": _rating(me.get("master_rating")),
        "my_league_rank": _int(me.get("league_rank")),
        "rating_timing": "buckler",
        "opp_name": (opp.get("player") or {}).get("fighter_id"),
        "opp_sid": _int((opp.get("player") or {}).get("short_id")),
        "opp_platform": (opp.get("player") or {}).get("platform_name"),
        "opp_character": _character(opp),
        "opp_input_type": _int(opp.get("battle_input_type")),
        "opp_lp": _rating(opp.get("league_point")),
        "opp_mr": _rating(opp.get("master_rating")),
        "result": result,
        "my_rounds": my_rounds,
        "opp_rounds": opp_rounds,
        "rounds_won": won,
        "rounds_lost": lost,
        "notes": None,
        "raw": json.dumps(replay, separators=(",", ":")),
    }


def parse_import(data, sid: int | None) -> tuple[list[dict], dict]:
    """Parse any accepted JSON into ranked match rows. Returns (rows, report)."""
    if sid is None and isinstance(data, dict):
        sid = _int(data.get("sid")) or _int((data.get("props") or {}).get("pageProps", {}).get("sid"))
    replays = find_replays(data)
    if sid is None:
        sid = guess_sid(replays)
    report = {"found": len(replays), "ranked": 0, "skipped_other_modes": 0,
              "skipped_unmatched": 0, "sid": sid}
    if not replays:
        return [], report
    if sid is None:
        raise BucklerError("Couldn't tell which player you are in this file. "
                           "Set your Buckler user code on the Sync tab and import again.")
    rows = []
    for r in replays:
        if not is_ranked(r):
            report["skipped_other_modes"] += 1
            continue
        row = parse_replay(r, sid)
        if row is None:
            report["skipped_unmatched"] += 1
            continue
        rows.append(row)
    report["ranked"] = len(rows)
    return rows, report


def _character(info: dict) -> str:
    return (info.get("playing_character_name") or info.get("character_name")
            or info.get("playing_character_tool_name") or "Unknown")


def _rating(v) -> int | None:
    n = _int(v)
    return n if n is not None and n > 0 else None


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---- fetching -----------------------------------------------------------------

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S)


def _get(url: str, cookie: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Cookie": cookie,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return resp.geturl(), body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise BlockedError(
                f"Capcom refused the request (HTTP {e.code}). Either the cookie has expired, "
                "or Buckler's bot protection blocked this app. Copy a fresh cookie, or use the "
                "browser collector on the Sync tab instead.") from e
        if e.code == 429:
            raise BucklerError("Buckler is rate-limiting requests (HTTP 429). Try again later.") from e
        raise BucklerError(f"Buckler returned HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise BucklerError(f"Couldn't reach Buckler: {e.reason}") from e


def fetch_page(sid: int, page: int, cookie: str) -> dict:
    """Fetch one page of the ranked battle log and return its pageProps."""
    url, html = _get(f"{BUCKLER}/profile/{sid}/battlelog/rank?page={page}", cookie)
    if "/auth/" in url or "login" in url.lower():
        raise AuthError("Buckler sent us to the login page: the cookie is missing or has "
                        "expired. Copy a fresh one from your browser.")
    if "Just a moment" in html or "cf-chl" in html:
        raise BlockedError("Buckler showed a bot-check page. Use the browser collector on "
                           "the Sync tab instead.")
    m = _NEXT_DATA.search(html)
    if not m:
        raise BucklerError("Buckler's page format has changed: no __NEXT_DATA__ found.")
    data = json.loads(m.group(1))
    props = (data.get("props") or {}).get("pageProps") or {}
    if "replay_list" not in props:
        if not props or props.get("__N_REDIRECT"):
            raise AuthError("Buckler didn't return a battle log: the cookie has probably expired.")
        raise BucklerError("Buckler's page had no battle log. Check your user code.")
    return props


def sync(sid: int, cookie: str, known_ids: set[str], delay: float = 1.0,
         progress=None) -> tuple[list[dict], dict]:
    """Fetch ranked pages newest-first until we reach matches we already have."""
    if not cookie.strip():
        raise AuthError("No Buckler cookie saved yet. Paste one on the Sync tab.")
    cookie = cookie.strip()
    if "=" not in cookie:
        cookie = f"buckler_id={cookie}"
    replays: list[dict] = []
    pages = 0
    total = 1
    page = 1
    while page <= min(total, MAX_PAGES):
        props = fetch_page(sid, page, cookie)
        pages += 1
        total = _int(props.get("total_page")) or 1
        batch = props.get("replay_list") or []
        replays.extend(batch)
        if progress:
            progress(page, total)
        if not batch or any(str(r.get("replay_id")) in known_ids for r in batch):
            break
        page += 1
        time.sleep(delay + random.random() * delay)
    rows, report = parse_import(replays, sid)
    report["pages"] = pages
    return rows, report

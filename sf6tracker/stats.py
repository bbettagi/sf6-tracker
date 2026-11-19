"""All dashboard numbers, computed from the stored ranked matches."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import ranks

# A single ranked match never moves LP or MR by more than this; a bigger jump between
# two stored matches means games are missing in between (or MR was reset for a new season).
LP_DELTA_CAP = 600
MR_DELTA_CAP = 120
ROLLING_WINDOW = 20


# ---- rating timeline ----------------------------------------------------------------

def detect_timing(matches: list[dict]) -> dict:
    """Work out whether Buckler's LP/MR are recorded before or after each match.

    If values are pre-match, the change from match A to the next match B follows A's
    result; if post-match, it follows B's result. Whichever agrees more often wins.
    """
    votes = {"pre": 0, "post": 0}
    pairs = 0
    for seq in _by_character(m for m in matches if m["rating_timing"] == "buckler").values():
        for a, b in zip(seq, seq[1:]):
            for key in ("my_lp", "my_mr"):
                va, vb = a[key], b[key]
                if va is None or vb is None or va == vb:
                    continue
                pairs += 1
                up = vb > va
                if a["result"] != "D" and up == (a["result"] == "W"):
                    votes["pre"] += 1
                if b["result"] != "D" and up == (b["result"] == "W"):
                    votes["post"] += 1
    timing = "post" if votes["post"] > votes["pre"] else "pre"
    return {
        "timing": timing,
        "pairs": pairs,
        "agreement": round(votes[timing] / pairs, 3) if pairs else None,
    }


def annotate(matches: list[dict], buckler_timing: str) -> list[dict]:
    """Add lp/mr before, after and delta to every match (in place), per character."""
    for seq in _by_character(matches).values():
        for key, cap in (("lp", LP_DELTA_CAP), ("mr", MR_DELTA_CAP)):
            pre, post = [], []
            for m in seq:
                value = m[f"my_{key}"]
                timing = buckler_timing if m["rating_timing"] == "buckler" else m["rating_timing"]
                pre.append(value if timing == "pre" else None)
                post.append(value if timing == "post" else None)
            n = len(seq)
            after = [post[i] if post[i] is not None else (pre[i + 1] if i + 1 < n else None)
                     for i in range(n)]
            before = [pre[i] if pre[i] is not None else (after[i - 1] if i else None)
                      for i in range(n)]
            for i, m in enumerate(seq):
                delta = None
                if before[i] is not None and after[i] is not None:
                    delta = after[i] - before[i]
                    if abs(delta) > cap:
                        delta = None
                m[f"{key}_before"], m[f"{key}_after"], m[f"{key}_delta"] = before[i], after[i], delta
        for i, m in enumerate(seq):
            m["char_game"] = i + 1
    return matches


def _by_character(matches) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in sorted(matches, key=lambda m: (m["played_at"], m["id"])):
        groups[m["my_character"]].append(m)
    return groups


def _rating_now(m: dict, key: str) -> int | None:
    after = m.get(f"{key}_after")
    return after if after is not None else m.get(f"{key}_before")


# ---- helpers ------------------------------------------------------------------------

def summarize(ms: list[dict]) -> dict:
    w = sum(1 for m in ms if m["result"] == "W")
    l = sum(1 for m in ms if m["result"] == "L")
    rw = sum(m["rounds_won"] or 0 for m in ms)
    rl = sum(m["rounds_lost"] or 0 for m in ms)
    lp = [m["lp_delta"] for m in ms if m.get("lp_delta") is not None]
    mr = [m["mr_delta"] for m in ms if m.get("mr_delta") is not None]
    return {
        "matches": len(ms),
        "wins": w,
        "losses": l,
        "draws": len(ms) - w - l,
        "win_rate": _rate(w, w + l),
        "rounds_won": rw,
        "rounds_lost": rl,
        "round_win_rate": _rate(rw, rw + rl),
        "net_lp": sum(lp) if lp else None,
        "avg_lp": round(sum(lp) / len(lp), 1) if lp else None,
        "net_mr": sum(mr) if mr else None,
        "avg_mr": round(sum(mr) / len(mr), 1) if mr else None,
    }


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def _local(t: int, tz_offset: int) -> datetime:
    """tz_offset is JavaScript's getTimezoneOffset(): minutes behind UTC."""
    return datetime.fromtimestamp(t - tz_offset * 60, tz=timezone.utc)


def rank_info(lp: int | None, mr: int | None) -> dict:
    info = {"lp": lp, "division": ranks.division_name(lp), "league": ranks.league_name(lp),
            "mr": mr, "master_tier": None, "next": None, "to_next": None, "progress": None}
    idx = ranks.division_index(lp)
    if mr and (idx == ranks.MASTER_INDEX or idx is None):
        info["master_tier"] = ranks.master_tier(mr)
        nxt = ranks.next_master_tier(mr)
        if nxt:
            floor = max(f for _, f in ranks.MASTER_TIERS if f <= mr) or 1500
            info["next"], info["to_next"] = nxt[0], nxt[1] - mr
            info["progress"] = round(min(1, max(0, (mr - floor) / (nxt[1] - floor))), 3)
    elif idx is not None:
        nxt = ranks.next_division(lp)
        if nxt:
            floor = ranks.DIVISIONS[idx][1]
            info["next"], info["to_next"] = nxt[0], nxt[1] - lp
            info["progress"] = round((lp - floor) / (nxt[1] - floor), 3)
    return info


# ---- sections -------------------------------------------------------------------------

def streaks(ms: list[dict]) -> dict:
    best = {"W": {"length": 0}, "L": {"length": 0}}
    cur_type, cur_len, cur_start = None, 0, None
    for m in ms:
        r = m["result"]
        if r == "D":
            cur_type, cur_len = None, 0
            continue
        if r == cur_type:
            cur_len += 1
        else:
            cur_type, cur_len, cur_start = r, 1, m["played_at"]
        if cur_len > best[r]["length"]:
            best[r] = {"length": cur_len, "start": cur_start, "end": m["played_at"]}
    return {"current": {"type": cur_type, "length": cur_len},
            "longest_win": best["W"], "longest_loss": best["L"]}


def rolling_win_rate(ms: list[dict], window: int = ROLLING_WINDOW) -> list[dict]:
    out = []
    results = []
    for i, m in enumerate(ms):
        if m["result"] != "D":
            results.append(m["result"] == "W")
        recent = results[-window:]
        if len(recent) >= min(window, 10):
            out.append({"n": i + 1, "t": m["played_at"], "win_rate": round(sum(recent) / len(recent), 4),
                        "window": len(recent)})
    return out


def my_characters(ms: list[dict], everything: list[dict]) -> list[dict]:
    rows = []
    latest = {}
    for m in everything:
        latest[m["my_character"]] = m
    for char, games in _group(ms, "my_character").items():
        last = latest[char]
        lps = [v for m in games for v in (m.get("lp_before"), m.get("lp_after")) if v is not None]
        mrs = [v for m in games for v in (m.get("mr_before"), m.get("mr_after")) if v is not None]
        rows.append({
            "character": char,
            **summarize(games),
            "current": rank_info(_rating_now(last, "lp"), _rating_now(last, "mr")),
            "peak_lp": max(lps) if lps else None,
            "peak_mr": max(mrs) if mrs else None,
            "last_played": games[-1]["played_at"],
        })
    rows.sort(key=lambda r: -r["matches"])
    return rows


def matchups(ms: list[dict]) -> list[dict]:
    rows = []
    for char, games in _group(ms, "opp_character").items():
        rows.append({"character": char, **summarize(games), "last_played": games[-1]["played_at"]})
    rows.sort(key=lambda r: (-r["matches"], r["character"]))
    return rows


def rank_section(ms: list[dict], character: str | None, tz_offset: int, gap_minutes: int) -> dict:
    if not ms:
        return {"character": None, "points": []}
    if character is None:
        character = Counter(m["my_character"] for m in ms).most_common(1)[0][0]
    games = [m for m in ms if m["my_character"] == character]
    points = [{
        "id": m["id"], "t": m["played_at"], "game": m["char_game"], "result": m["result"],
        "opp": m["opp_character"], "lp": m["lp_after"], "mr": m["mr_after"],
        "lp_before": m["lp_before"], "mr_before": m["mr_before"],
        "lp_delta": m["lp_delta"], "mr_delta": m["mr_delta"],
    } for m in games]

    events = []
    prev_div = prev_tier = None
    for m in games:
        for value in (m["lp_before"], m["lp_after"]):
            div = ranks.division_index(value)
            if div is not None:
                if prev_div is not None and div != prev_div:
                    events.append({"t": m["played_at"], "kind": "division",
                                   "from": ranks.DIVISIONS[prev_div][0], "to": ranks.DIVISIONS[div][0],
                                   "up": div > prev_div})
                prev_div = div
        for value in (m["mr_before"], m["mr_after"]):
            tier = ranks.master_tier(value)
            if tier is not None:
                if prev_tier is not None and tier != prev_tier:
                    order = [t for t, _ in ranks.MASTER_TIERS]
                    events.append({"t": m["played_at"], "kind": "tier", "from": prev_tier, "to": tier,
                                   "up": order.index(tier) > order.index(prev_tier)})
                prev_tier = tier

    days: dict[str, list[dict]] = defaultdict(list)
    for m in games:
        days[_local(m["played_at"], tz_offset).date().isoformat()].append(m)
    by_day = [{"day": d, **summarize(g)} for d, g in sorted(days.items())]
    by_session = [{"start": s[0]["played_at"], "end": s[-1]["played_at"], **summarize(s)}
                  for s in _split_sessions(games, gap_minutes)]

    last = games[-1]
    return {
        "character": character,
        "characters": sorted({m["my_character"] for m in ms}),
        "points": points,
        "events": events,
        "by_day": by_day,
        "by_session": by_session,
        "current": rank_info(_rating_now(last, "lp"), _rating_now(last, "mr")),
        "summary": summarize(games),
    }


def _split_sessions(ms: list[dict], gap_minutes: int) -> list[list[dict]]:
    out: list[list[dict]] = []
    for m in ms:
        if out and m["played_at"] - out[-1][-1]["played_at"] <= gap_minutes * 60:
            out[-1].append(m)
        else:
            out.append([m])
    return out


def sessions_section(ms: list[dict], tz_offset: int, gap_minutes: int) -> dict:
    sessions = _split_sessions(ms, gap_minutes)
    rows = []
    for s in sessions:
        rows.append({
            "start": s[0]["played_at"], "end": s[-1]["played_at"],
            "minutes": round((s[-1]["played_at"] - s[0]["played_at"]) / 60),
            "characters": [c for c, _ in Counter(m["my_character"] for m in s).most_common()],
            "results": "".join(m["result"] for m in s),
            **summarize(s),
            "streaks": streaks(s),
        })
    rows.reverse()

    after = {"after_win": [], "after_loss": [], "after_2_losses": [], "after_3_losses": []}
    positions = {"1–3": [], "4–6": [], "7–10": [], "11–15": [], "16+": []}
    for s in sessions:
        for i, m in enumerate(s):
            prev = [p["result"] for p in s[max(0, i - 3):i]]
            if prev and prev[-1] == "W":
                after["after_win"].append(m)
            if prev and prev[-1] == "L":
                after["after_loss"].append(m)
            if prev[-2:] == ["L", "L"]:
                after["after_2_losses"].append(m)
            if prev[-3:] == ["L", "L", "L"]:
                after["after_3_losses"].append(m)
            n = i + 1
            key = "1–3" if n <= 3 else "4–6" if n <= 6 else "7–10" if n <= 10 else "11–15" if n <= 15 else "16+"
            positions[key].append(m)

    hours = {"Night (0–6)": [], "Morning (6–12)": [], "Afternoon (12–18)": [], "Evening (18–24)": []}
    labels = list(hours)
    for m in ms:
        hours[labels[_local(m["played_at"], tz_offset).hour // 6]].append(m)

    lengths = [len(s) for s in sessions]
    return {
        "gap_minutes": gap_minutes,
        "count": len(sessions),
        "avg_matches": round(sum(lengths) / len(lengths), 1) if lengths else None,
        "sessions": rows,
        "streaks": streaks(ms),
        "tilt": {k: summarize(v) for k, v in after.items()},
        "by_position": [{"label": k, **summarize(v)} for k, v in positions.items()],
        "by_time_of_day": [{"label": k, **summarize(v)} for k, v in hours.items()],
    }


def _bucket_mr(diff: int) -> str:
    if diff <= -100:
        return "100+ MR below"
    if diff <= -30:
        return "30–99 MR below"
    if diff < 30:
        return "Within 30 MR"
    if diff < 100:
        return "30–99 MR above"
    return "100+ MR above"


def _bucket_div(diff: int) -> str:
    if diff <= -2:
        return "2+ divisions below"
    if diff == -1:
        return "1 division below"
    if diff == 0:
        return "Same division"
    if diff == 1:
        return "1 division above"
    return "2+ divisions above"


MR_BUCKETS = ["100+ MR below", "30–99 MR below", "Within 30 MR", "30–99 MR above", "100+ MR above"]
DIV_BUCKETS = ["2+ divisions below", "1 division below", "Same division", "1 division above",
               "2+ divisions above"]
LEAGUES = ["Rookie", "Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master"]


def opponents_section(ms: list[dict]) -> dict:
    by_mr: dict[str, list] = defaultdict(list)
    by_div: dict[str, list] = defaultdict(list)
    by_league: dict[str, list] = defaultdict(list)
    diffs = []
    for m in ms:
        if m["my_mr"] and m["opp_mr"]:
            diff = m["opp_mr"] - m["my_mr"]
            by_mr[_bucket_mr(diff)].append(m)
            diffs.append(("mr", diff, m["result"]))
        elif m["my_lp"] is not None and m["opp_lp"] is not None:
            diff = ranks.division_index(m["opp_lp"]) - ranks.division_index(m["my_lp"])
            by_div[_bucket_div(diff)].append(m)
        league = ranks.league_name(m["opp_lp"])
        if league:
            by_league[league].append(m)

    rivals = []
    by_player: dict[int, list] = defaultdict(list)
    for m in ms:
        if m["opp_sid"]:
            by_player[m["opp_sid"]].append(m)
    for sid, games in by_player.items():
        if len(games) >= 2:
            rivals.append({"sid": sid, "name": games[-1]["opp_name"],
                           "characters": sorted({g["opp_character"] for g in games}),
                           "last_played": games[-1]["played_at"], **summarize(games)})
    rivals.sort(key=lambda r: (-r["matches"], -(r["last_played"])))

    def rows(groups, order):
        return [{"label": k, **summarize(groups[k])} for k in order if groups.get(k)]

    return {
        "by_mr_gap": rows(by_mr, MR_BUCKETS),
        "by_division_gap": rows(by_div, DIV_BUCKETS),
        "by_league": rows(by_league, LEAGUES),
        "rivals": rivals[:20],
        "unique_opponents": len(by_player),
    }


def rounds_section(ms: list[dict]) -> dict:
    scores = Counter()
    for m in ms:
        if m["rounds_won"] is not None and m["rounds_lost"] is not None:
            scores[f"{m['rounds_won']}-{m['rounds_lost']}"] += 1
    order = ["2-0", "2-1", "1-2", "0-2"]
    score_rows = [{"score": s, "matches": scores[s]} for s in order if scores[s]]
    score_rows += [{"score": s, "matches": n} for s, n in sorted(scores.items()) if s not in order]

    detailed = [m for m in ms if m["my_rounds"] is not None and m["opp_rounds"] is not None]
    per_round: dict[int, Counter] = defaultdict(Counter)
    my_finishes, opp_finishes = Counter(), Counter()
    r1_won, r1_lost, deciding = [], [], []
    perfects_for = perfects_against = 0
    for m in detailed:
        mine, theirs = m["my_rounds"], m["opp_rounds"]
        for i in range(max(len(mine), len(theirs))):
            a = mine[i] if i < len(mine) else 0
            b = theirs[i] if i < len(theirs) else 0
            if a == ranks.DRAW_CODE or b == ranks.DRAW_CODE:
                per_round[i + 1]["draws"] += 1
            elif a:
                per_round[i + 1]["won"] += 1
                my_finishes[a] += 1
                perfects_for += a == 8
            elif b:
                per_round[i + 1]["lost"] += 1
                opp_finishes[b] += 1
                perfects_against += b == 8
        first_a = mine[0] if mine else 0
        first_b = theirs[0] if theirs else 0
        if first_a and first_a != ranks.DRAW_CODE:
            r1_won.append(m)
        elif first_b and first_b != ranks.DRAW_CODE:
            r1_lost.append(m)
        if (m["rounds_won"] or 0) >= 1 and (m["rounds_lost"] or 0) >= 1:
            deciding.append(m)

    def finish_rows(counter):
        total = sum(counter.values())
        return [{"code": code, "short": ranks.FINISHES.get(code, (f"#{code}",))[0],
                 "label": ranks.finish_label(code), "rounds": n, "share": _rate(n, total)}
                for code, n in counter.most_common()]

    return {
        "summary": summarize(ms),
        "scores": score_rows,
        "detailed_matches": len(detailed),
        "per_round": [{"round": r, "won": c["won"], "lost": c["lost"], "draws": c["draws"],
                       "win_rate": _rate(c["won"], c["won"] + c["lost"])}
                      for r, c in sorted(per_round.items())],
        "after_round1_win": summarize(r1_won),
        "after_round1_loss": summarize(r1_lost),
        "deciding_round": summarize(deciding),
        "my_finishes": finish_rows(my_finishes),
        "opp_finishes": finish_rows(opp_finishes),
        "perfects_for": perfects_for,
        "perfects_against": perfects_against,
    }


def _group(ms: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in ms:
        groups[m[key]].append(m)
    return groups


# ---- entry point ----------------------------------------------------------------------

def compute(matches: list[dict], config: dict, start: int | None = None, end: int | None = None,
            character: str | None = None, tz_offset: int = 0) -> dict:
    detection = detect_timing(matches)
    timing = config.get("lp_timing", "auto")
    timing = detection["timing"] if timing not in ("pre", "post") else timing
    annotate(matches, timing)
    gap = int(config.get("session_gap_minutes") or 30)

    in_range = [m for m in matches
                if (start is None or m["played_at"] >= start) and (end is None or m["played_at"] < end)]
    ms = [m for m in in_range if character is None or m["my_character"] == character]

    return {
        "timing": {**detection, "used": timing, "setting": config.get("lp_timing", "auto")},
        "filters": {"start": start, "end": end, "character": character},
        "overview": {
            "summary": summarize(ms),
            "streaks": streaks(ms),
            "form": [{"id": m["id"], "result": m["result"], "opp": m["opp_character"],
                      "t": m["played_at"]} for m in ms[-20:]],
            "rolling": rolling_win_rate(ms),
            "characters": my_characters(in_range if character is None else ms, matches),
        },
        "rank": rank_section(ms, character, tz_offset, gap),
        "matchups": matchups(ms),
        "sessions": sessions_section(ms, tz_offset, gap),
        "opponents": opponents_section(ms),
        "rounds": rounds_section(ms),
    }

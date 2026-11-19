"""Generated demo data in Buckler's battle log format, for trying the dashboard out."""

from __future__ import annotations

import random
import time

from . import buckler, ranks

DEMO_SID = 1000000001
_NAMES = ["Kairo", "MadHops", "TigerUpper", "Shinku", "ParryKing", "Mochi", "Raijin", "DriveRushDan",
          "Zeta", "Hadoken99", "OkiBunny", "Vortex", "PunishCounter", "LowForward", "Saltmine",
          "Gief4Life", "Nomad", "Kiko", "Burnout", "Tatsu", "Lariat", "Haze", "FrameTrap", "Sonic"]
_POPULAR = {"Ken": 9, "Ryu": 7, "Luke": 7, "Akuma": 6, "Cammy": 6, "Juri": 6, "M. Bison": 5,
            "Chun-Li": 5, "Guile": 5, "JP": 5, "Ed": 4, "Terry": 4, "Mai": 4}
_FINISHES = [(1, 52), (6, 12), (7, 9), (5, 9), (2, 8), (3, 4), (8, 3)]


def generate_replays(n: int = 600, seed: int = 7, end: int | None = None,
                     timing: str = "pre") -> list[dict]:
    rng = random.Random(seed)
    end = end or int(time.time()) - 3600
    chars = ranks.CHARACTERS
    weights = [_POPULAR.get(c, 2) for c in chars]
    matchup_bias = {c: rng.uniform(-0.12, 0.12) for c in chars}
    pool = [(1100000000 + i, f"{rng.choice(_NAMES)}{rng.randint(1, 999)}") for i in range(90)]
    mine = {"Ken": {"lp": 19400, "mr": None, "skill": 0.01}, "Juri": {"lp": 9200, "mr": None, "skill": -0.02}}

    # Lay out sessions backwards from `end`.
    starts, t, remaining = [], end, n
    while remaining > 0:
        size = min(remaining, rng.randint(4, 22))
        t -= size * 260 + rng.choice([rng.randint(3, 10) * 3600, rng.randint(20, 60) * 3600])
        starts.append((t, size))
        remaining -= size
    starts.reverse()

    replays = []
    for start, size in starts:
        main = "Ken" if rng.random() < 0.72 else "Juri"
        t = start
        recent = []
        for pos in range(size):
            if rng.random() < 0.08:
                main = "Juri" if main == "Ken" else "Ken"
            me = mine[main]
            opp_char = rng.choices(chars, weights)[0]
            opp_sid, opp_name = rng.choice(pool[:30] if rng.random() < 0.25 else pool)
            in_master = me["lp"] >= ranks.MASTER_LP
            opp_lp = max(0, int(me["lp"] + rng.gauss(0, 900)))
            opp_mr = None
            if in_master:
                opp_lp = max(opp_lp, ranks.MASTER_LP)
                opp_mr = int(me["mr"] + rng.gauss(0, 60))
            gap = ((opp_mr - me["mr"]) / 400) if in_master else (opp_lp - me["lp"]) / 4000
            p = 0.53 + me["skill"] + matchup_bias[opp_char] - gap
            p -= 0.07 if recent[-2:] == ["L", "L"] else 0
            p -= 0.04 if pos >= 12 else 0
            win = rng.random() < max(0.15, min(0.85, p))

            my_rounds, opp_rounds = _rounds(rng, win)
            before = {"lp": me["lp"], "mr": me["mr"]}
            if in_master:   # Elo-style, like MR
                expected = 1 / (1 + 10 ** ((opp_mr - me["mr"]) / 400))
                change = round(32 * ((1 if win else 0) - expected))
                me["mr"] += max(change, 1) if win else min(change, -1)
            else:
                change = rng.randint(70, 140) if win else -rng.randint(40, 110)
                change += round((opp_lp - me["lp"]) / 40)
                me["lp"] = max(0, me["lp"] + (max(change, 15) if win else min(change, 0)))
                if me["lp"] >= ranks.MASTER_LP:
                    me["lp"], me["mr"] = ranks.MASTER_LP, 1500
            me["skill"] += 0.0004 if not in_master else 0
            shown = before if timing == "pre" else {"lp": me["lp"], "mr": me["mr"]}

            mine_info = _player(DEMO_SID, "DemoPlayer", main, shown["lp"], shown["mr"], my_rounds, rng)
            opp_info = _player(opp_sid, opp_name, opp_char, opp_lp, opp_mr, opp_rounds, rng)
            p1, p2 = (mine_info, opp_info) if rng.random() < 0.5 else (opp_info, mine_info)
            replays.append({
                "replay_id": f"DEMO{len(replays):06d}",
                "uploaded_at": t,
                "replay_battle_type": 1,
                "replay_battle_type_name": "Ranked Match",
                "player1_info": p1,
                "player2_info": p2,
            })
            recent.append("W" if win else "L")
            t += rng.randint(150, 330)
    return replays


def _rounds(rng, win: bool) -> tuple[list[int], list[int]]:
    """Round codes for both sides: 2-0 or 2-1 for the winner, with a rare draw round."""
    seq = (rng.choice([["W", "L"], ["L", "W"]]) + ["W"]) if rng.random() < 0.45 else ["W", "W"]
    if not win:
        seq = ["L" if s == "W" else "W" for s in seq]
    if rng.random() < 0.02:
        seq.insert(rng.randrange(len(seq)), "D")
    mine = [ranks.DRAW_CODE if s == "D" else _finish(rng) if s == "W" else 0 for s in seq]
    theirs = [ranks.DRAW_CODE if s == "D" else _finish(rng) if s == "L" else 0 for s in seq]
    return mine, theirs


def _finish(rng) -> int:
    codes, weights = zip(*_FINISHES)
    return rng.choices(codes, weights)[0]


def _player(sid, name, char, lp, mr, rounds, rng) -> dict:
    return {
        "player": {"short_id": sid, "fighter_id": name, "platform_name": rng.choice(["Steam", "PlayStation", "Xbox"])},
        "playing_character_name": char,
        "playing_character_tool_name": char.lower().replace(". ", "").replace(".", ""),
        "battle_input_type": rng.choice([0, 0, 0, 1]),
        "league_point": lp,
        "master_rating": mr or 0,
        "league_rank": (ranks.division_index(lp) or 0) + 1,
        "round_results": rounds,
    }


def generate(n: int = 600, seed: int = 7) -> list[dict]:
    rows, _ = buckler.parse_import(generate_replays(n, seed), DEMO_SID)
    return rows

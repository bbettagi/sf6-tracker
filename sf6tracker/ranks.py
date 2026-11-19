"""SF6 ranked ladder: LP divisions, Master tiers and round-finish codes."""

from __future__ import annotations

# (league, minimum LP) for every division below Master, in ladder order.
# Rookie divisions are 200 LP wide, Iron/Bronze 400, Silver/Gold 800, Platinum/Diamond 1200.
_LEAGUES = [
    ("Rookie", 0, 200),
    ("Iron", 1000, 400),
    ("Bronze", 3000, 400),
    ("Silver", 5000, 800),
    ("Gold", 9000, 800),
    ("Platinum", 13000, 1200),
    ("Diamond", 19000, 1200),
]

DIVISIONS: list[tuple[str, int]] = []
for _league, _start, _width in _LEAGUES:
    for _n in range(5):
        DIVISIONS.append((f"{_league} {_n + 1}", _start + _n * _width))
MASTER_LP = 25000
DIVISIONS.append(("Master", MASTER_LP))
MASTER_INDEX = len(DIVISIONS) - 1

# Master is split by Master Rate (MR). Legend (top 500) can't be derived from MR alone.
MASTER_TIERS = [
    ("Master", 0),
    ("High Master", 1600),
    ("Grand Master", 1700),
    ("Ultimate Master", 1800),
]

# Buckler round_results codes: 0 means that side did not win the round.
FINISHES = {
    1: ("V", "Knockout"),
    2: ("C", "Chip KO"),
    3: ("T", "Time over"),
    4: ("D", "Draw"),
    5: ("OD", "Overdrive"),
    6: ("SA", "Super Art"),
    7: ("CA", "Critical Art"),
    8: ("P", "Perfect"),
}
DRAW_CODE = 4

CHARACTERS = [
    "Ryu", "Luke", "Jamie", "Chun-Li", "Guile", "Kimberly", "Juri", "Ken",
    "Blanka", "Dhalsim", "E. Honda", "Dee Jay", "Manon", "Marisa", "JP",
    "Zangief", "Lily", "Cammy", "Rashid", "A.K.I.", "Ed", "Akuma", "M. Bison",
    "Terry", "Mai", "Elena", "Sagat", "C. Viper", "Alex", "Ingrid",
]


def division_index(lp: int | None) -> int | None:
    if lp is None or lp < 0:
        return None
    idx = 0
    for i, (_, floor) in enumerate(DIVISIONS):
        if lp >= floor:
            idx = i
    return idx


def division_name(lp: int | None) -> str | None:
    idx = division_index(lp)
    return None if idx is None else DIVISIONS[idx][0]


def league_name(lp: int | None) -> str | None:
    name = division_name(lp)
    return None if name is None else name.split(" ")[0]


def next_division(lp: int | None) -> tuple[str, int] | None:
    """The next division up and the LP it starts at, or None at Master."""
    idx = division_index(lp)
    if idx is None or idx >= MASTER_INDEX:
        return None
    return DIVISIONS[idx + 1]


def master_tier(mr: int | None) -> str | None:
    if not mr or mr <= 0:
        return None
    name = MASTER_TIERS[0][0]
    for tier, floor in MASTER_TIERS:
        if mr >= floor:
            name = tier
    return name


def next_master_tier(mr: int | None) -> tuple[str, int] | None:
    if not mr or mr <= 0:
        return None
    for tier, floor in MASTER_TIERS:
        if mr < floor:
            return (tier, floor)
    return None


def finish_label(code: int) -> str:
    return FINISHES.get(code, (f"#{code}", f"Code {code}"))[1]

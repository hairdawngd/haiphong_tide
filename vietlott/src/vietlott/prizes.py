"""Cơ cấu giải thưởng và xác suất lý thuyết của từng hạng giải."""
from math import comb

K = 6
TICKET_PRICE = 10_000  # đồng / bộ số

GAMES = {
    "power655": {
        "name": "Power 6/55", "n": 55, "has_bonus": True,
        "tiers": [  # (khóa, tên, giá trị cố định; None = tích lũy)
            ("jackpot1", "Jackpot 1", None),
            ("jackpot2", "Jackpot 2", None),
            ("first", "Giải Nhất", 40_000_000),
            ("second", "Giải Nhì", 500_000),
            ("third", "Giải Ba", 50_000),
        ],
    },
    "mega645": {
        "name": "Mega 6/45", "n": 45, "has_bonus": False,
        "tiers": [
            ("jackpot", "Jackpot", None),
            ("first", "Giải Nhất", 10_000_000),
            ("second", "Giải Nhì", 300_000),
            ("third", "Giải Ba", 30_000),
        ],
    },
}


def classify(game, matches, bonus_hit):
    """Hạng giải (khóa) theo số trùng; None nếu không trúng."""
    if game == "power655":
        if matches == 6: return "jackpot1"
        if matches == 5 and bonus_hit: return "jackpot2"
        if matches == 5: return "first"
        if matches == 4: return "second"
        if matches == 3: return "third"
    else:
        if matches == 6: return "jackpot"
        if matches == 5: return "first"
        if matches == 4: return "second"
        if matches == 3: return "third"
    return None


def tier_name(game, key):
    return {k: nm for k, nm, _ in GAMES[game]["tiers"]}.get(key, "")


def tier_value(game, key):
    """Giá trị giải cố định (đồng); 0 với Jackpot vì phụ thuộc mức tích lũy."""
    return {k: v for k, _, v in GAMES[game]["tiers"]}.get(key) or 0


def tier_probs(game):
    """Xác suất lý thuyết trúng từng hạng giải với MỘT bộ số."""
    n = GAMES[game]["n"]
    total = comb(n, K)
    other = n - K
    if game == "power655":
        return {
            "jackpot1": 1 / total,
            "jackpot2": 6 * 1 / total,
            "first": 6 * (other - 1) / total,
            "second": comb(6, 4) * comb(other, 2) / total,
            "third": comb(6, 3) * comb(other, 3) / total,
        }
    return {
        "jackpot": 1 / total,
        "first": 6 * other / total,
        "second": comb(6, 4) * comb(other, 2) / total,
        "third": comb(6, 3) * comb(other, 3) / total,
    }


def win_prob(game):
    return sum(tier_probs(game).values())


def jackpot_odds(game):
    return comb(GAMES[game]["n"], K)


def vnd(x):
    return f"{int(x):,}".replace(",", ".") + "đ"

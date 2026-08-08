"""Maps Lichess puzzle themes, and the user's own critical-moment history,
onto the same four weakness categories /progress talks about (tactics,
endgame, opening mistakes, positional understanding) — so targeted puzzle
selection can point at a subscriber's actual weak spots.

Both mappings here are approximate by design (per the task): Lichess theme
tags are informal and overlapping, and classifying the user's own moments
below is a fast heuristic proxy, not the real thing. The real thing is what
/progress already does — asking Claude to read each position and judge it —
but that's an LLM call per request, too slow/costly to run on every puzzle
fetch. This reads the exact same usage-table fields /progress does
(move_number, cp_loss) and classifies them with simple thresholds instead,
which is good enough to bias puzzle selection without adding latency.
"""

CATEGORY_TACTICS = "tactics"
CATEGORY_ENDGAME = "endgame"
CATEGORY_OPENING = "opening"
CATEGORY_POSITIONAL = "positional"

CATEGORY_LABELS_RU = {
    CATEGORY_TACTICS: "тактика",
    CATEGORY_ENDGAME: "эндшпиль",
    CATEGORY_OPENING: "дебютные ошибки",
    CATEGORY_POSITIONAL: "позиционное понимание",
}

# Lichess puzzle theme -> weakness category. Not every theme is mapped —
# pure difficulty/length/source tags (short, veryLong, master, oneMove...)
# don't say anything about the *kind* of mistake, so they're left out; a
# puzzle just needs at least one of its themes to land in the target
# category to be selectable for it.
THEME_TO_CATEGORY = {
    # opening
    "opening": CATEGORY_OPENING,
    "castling": CATEGORY_OPENING,
    # endgame
    "endgame": CATEGORY_ENDGAME,
    "pawnEndgame": CATEGORY_ENDGAME,
    "bishopEndgame": CATEGORY_ENDGAME,
    "knightEndgame": CATEGORY_ENDGAME,
    "rookEndgame": CATEGORY_ENDGAME,
    "queenEndgame": CATEGORY_ENDGAME,
    "queenRookEndgame": CATEGORY_ENDGAME,
    "zugzwang": CATEGORY_ENDGAME,
    # tactics — sharp/forcing patterns and mating attacks
    "fork": CATEGORY_TACTICS,
    "pin": CATEGORY_TACTICS,
    "skewer": CATEGORY_TACTICS,
    "discoveredAttack": CATEGORY_TACTICS,
    "doubleCheck": CATEGORY_TACTICS,
    "attraction": CATEGORY_TACTICS,
    "deflection": CATEGORY_TACTICS,
    "clearance": CATEGORY_TACTICS,
    "interference": CATEGORY_TACTICS,
    "intermezzo": CATEGORY_TACTICS,
    "xRayAttack": CATEGORY_TACTICS,
    "sacrifice": CATEGORY_TACTICS,
    "trappedPiece": CATEGORY_TACTICS,
    "hangingPiece": CATEGORY_TACTICS,
    "capturingDefender": CATEGORY_TACTICS,
    "promotion": CATEGORY_TACTICS,
    "underPromotion": CATEGORY_TACTICS,
    "enPassant": CATEGORY_TACTICS,
    "quietMove": CATEGORY_TACTICS,
    "attackingF2F7": CATEGORY_TACTICS,
    "kingsideAttack": CATEGORY_TACTICS,
    "queensideAttack": CATEGORY_TACTICS,
    "exposedKing": CATEGORY_TACTICS,
    "mate": CATEGORY_TACTICS,
    "mateIn1": CATEGORY_TACTICS,
    "mateIn2": CATEGORY_TACTICS,
    "mateIn3": CATEGORY_TACTICS,
    "mateIn4": CATEGORY_TACTICS,
    "mateIn5": CATEGORY_TACTICS,
    "backRankMate": CATEGORY_TACTICS,
    "smotheredMate": CATEGORY_TACTICS,
    "arabianMate": CATEGORY_TACTICS,
    "anastasiaMate": CATEGORY_TACTICS,
    "bodenMate": CATEGORY_TACTICS,
    "hookMate": CATEGORY_TACTICS,
    "dovetailMate": CATEGORY_TACTICS,
    "doubleBishopMate": CATEGORY_TACTICS,
    # positional — general-advantage / slow-accumulation themes, not a
    # single tactical shot
    "advantage": CATEGORY_POSITIONAL,
    "crushing": CATEGORY_POSITIONAL,
    "equality": CATEGORY_POSITIONAL,
    "advancedPawn": CATEGORY_POSITIONAL,
    "defensiveMove": CATEGORY_POSITIONAL,
    "middlegame": CATEGORY_POSITIONAL,
}


def category_tags(category: str) -> set[str]:
    return {tag for tag, cat in THEME_TO_CATEGORY.items() if cat == category}


# Rough phase thresholds by move number — good enough to bias puzzle
# selection, not precise enough to write coaching prose about (that's what
# /progress's Claude call is for).
_OPENING_MOVE_CUTOFF = 10
_ENDGAME_MOVE_CUTOFF = 30
_TACTICAL_CP_LOSS_THRESHOLD = 300


def _classify_moment(move_number: int, cp_loss: int) -> str:
    if move_number <= _OPENING_MOVE_CUTOFF:
        return CATEGORY_OPENING
    if move_number >= _ENDGAME_MOVE_CUTOFF:
        return CATEGORY_ENDGAME
    return CATEGORY_TACTICS if cp_loss >= _TACTICAL_CP_LOSS_THRESHOLD else CATEGORY_POSITIONAL


def top_weak_categories(moments, limit: int = 2) -> list[str]:
    """`moments` are rows from database.get_critical_moments_since — the
    same data /progress reads. Returns up to `limit` category keys, most
    frequent first.
    """
    counts: dict[str, int] = {}
    for m in moments:
        if m["move_number"] is None or m["cp_loss"] is None:
            continue
        category = _classify_moment(m["move_number"], m["cp_loss"])
        counts[category] = counts.get(category, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [category for category, _ in ranked[:limit]]

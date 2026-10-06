"""Self-assessment questionnaire that suggests an NTRP rating.

Players tend to over-rate themselves; anchoring the rating on concrete skills curbs that.
Self-assessment is capped at 5.5 — higher levels are only assigned at partner screening.
"""

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Question:
    key: str
    prompt: str
    options: tuple[str, ...]


QUESTIONS: tuple[Question, ...] = (
    Question(
        "experience",
        "How long have you been playing regularly?",
        ("Less than a year", "1–3 years", "3–7 years", "More than 7 years"),
    ),
    Question(
        "rally",
        "How consistent are your groundstrokes in a rally?",
        (
            "I struggle to keep the ball in play",
            "I can rally 5+ shots at a moderate pace",
            "I can rally 10+ shots and direct the ball",
            "I sustain pace and depth from both sides",
        ),
    ),
    Question(
        "backhand",
        "How would you describe your backhand?",
        (
            "I avoid it when I can",
            "Reliable on slower balls",
            "I can drive or slice it with direction",
            "It's a weapon",
        ),
    ),
    Question(
        "serve",
        "How would you describe your serve?",
        (
            "Getting it in is a struggle",
            "Consistent but without much pace",
            "I use pace or spin and can place it",
            "It wins me points outright",
        ),
    ),
    Question(
        "net",
        "How comfortable are you at the net?",
        (
            "I rarely come in",
            "I can volley slower balls",
            "Solid volleys and overheads",
            "I finish points at the net confidently",
        ),
    ),
    Question(
        "competition",
        "What's your match experience?",
        (
            "I haven't played matches",
            "Casual or social matches",
            "League (e.g. USTA) or club tournaments",
            "High school varsity, college or open tournaments",
        ),
    ),
)

MAX_SELF_ASSESSED = Decimal("5.5")
MAX_WITHOUT_COMPETITION = Decimal("4.0")

LEVEL_DESCRIPTIONS: dict[Decimal, str] = {
    Decimal("1.5"): "Just starting out — focused on getting the ball in play.",
    Decimal("2.0"): "Learning the basic strokes; short rallies at slow pace.",
    Decimal("2.5"): "Can sustain slow rallies; working on court coverage.",
    Decimal("3.0"): "Consistent on medium-paced balls; developing direction and depth.",
    Decimal("3.5"): "Improving consistency with direction; starting to use the net.",
    Decimal("4.0"): "Dependable strokes with directional control on both sides.",
    Decimal("4.5"): "Uses pace and spin effectively; solid serve and net game.",
    Decimal("5.0"): "Strong shot anticipation; can hit winners and force errors.",
    Decimal("5.5"): "Tournament-level player with weapons around which to build a game.",
}


def suggest_ntrp(answers: dict[str, int]) -> Decimal:
    """Map answers (each 0-3) to an NTRP rating between 1.5 and 5.5 in 0.5 steps."""
    total = sum(answers[q.key] for q in QUESTIONS)
    max_total = 3 * len(QUESTIONS)
    raw = 1.5 + (total / max_total) * float(MAX_SELF_ASSESSED - Decimal("1.5"))
    rating = Decimal(math.floor(raw * 2 + 0.5)) / 2  # round half up to the nearest 0.5
    if answers["competition"] < 2:
        rating = min(rating, MAX_WITHOUT_COMPETITION)
    return min(max(rating, Decimal("1.5")), MAX_SELF_ASSESSED)


def describe(rating: Decimal) -> str:
    return LEVEL_DESCRIPTIONS.get(rating, LEVEL_DESCRIPTIONS[MAX_SELF_ASSESSED])

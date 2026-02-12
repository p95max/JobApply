from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classified:
    detected_type: str
    confidence: int


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify(subject: str, snippet: str) -> Classified:
    """
    Heuristic classifier. No ML.
    Returns (type, confidence 0..100).
    """
    text = _norm(f"{subject} {snippet}")

    if any(x in text for x in ["newsletter", "job alert", "unsubscribe", "marketing", "angebot", "rabatt"]):
        return Classified("noise", 90)

    rejection_terms = [
        "absage",
        "leider",
        "nicht berücksichtigen",
        "haben uns entschieden",
        "unfortunately",
        "we regret",
        "other candidates",
        "cannot offer you",
        "we have decided",
    ]
    if any(t in text for t in rejection_terms):
        return Classified("rejection", 90)

    invite_terms = [
        "einladung",
        "interview",
        "gespräch",
        "termin",
        "kennenlerngespräch",
        "invitation",
        "meeting",
        "call",
        "video call",
        "teams",
        "zoom",
    ]
    if any(t in text for t in invite_terms):
        return Classified("invite", 88)

    auto_ack_terms = [
        "eingangsbestätigung",
        "haben ihre bewerbung erhalten",
        "vielen dank für ihre bewerbung",
        "thank you for your application",
        "received your application",
        "we have received",
    ]
    if any(t in text for t in auto_ack_terms):
        return Classified("auto_ack", 80)

    if any(x in text for x in ["bewerbung", "application", "stelle", "vacancy", "position"]):
        return Classified("response", 65)

    return Classified("unknown", 0)

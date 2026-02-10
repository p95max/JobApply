from __future__ import annotations


def build_responses_query(days: int) -> str:
    return (
        f"newer_than:{days}d "
        "("
        "bewerbung OR application OR \"Ihre Bewerbung\" OR \"your application\" "
        "OR Stelle OR vacancy OR position"
        ") "
        "-category:promotions -category:social"
    )


def build_rejections_query(days: int) -> str:
    return (
        f"newer_than:{days}d "
        "("
        "leider OR Absage OR \"nicht berücksichtigen\" OR \"haben uns entschieden\" "
        "OR unfortunately OR \"we regret\" OR \"other candidates\""
        ") "
        "("
        "bewerbung OR application OR Stelle OR position OR vacancy"
        ") "
        "-category:promotions -category:social"
    )


def build_invites_query(days: int) -> str:
    return (
        f"newer_than:{days}d "
        "("
        "Einladung OR Interview OR Gespräch OR Termin OR \"Kennenlerngespräch\" "
        "OR invitation OR interview OR meeting OR call"
        ") "
        "("
        "bewerbung OR application OR Stelle OR position OR vacancy"
        ") "
        "-category:promotions -category:social"
    )

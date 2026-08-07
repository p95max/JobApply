from __future__ import annotations


def build_candidate_query(days: int) -> str:
    """Build the single bounded inbound Gmail query for the assistant pipeline."""
    return (
        f"newer_than:{days}d "
        "("
        "bewerbung OR application OR interview OR gespräch OR recruiter OR recruiting "
        'OR absage OR einladung OR "ihre unterlagen" OR "your application"'
        ") "
        "-category:promotions -category:social -from:me"
    )


def build_sent_applications_query(days: int) -> str:
    """Bounded query for applications the mailbox owner sent themselves."""
    return (
        f"in:sent newer_than:{days}d "
        "(bewerbung OR application OR applying OR apply OR position OR stelle OR vacancy) "
        "-category:promotions -category:social"
    )


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

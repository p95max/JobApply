from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from apps.gmail_stats.services.application_matcher import (
    EmailMatchData,
    match_applications,
    normalize_company,
    normalize_position,
)


@dataclass(frozen=True)
class Application:
    pk: int
    user_id: int
    company: str
    title: str
    status: str = "applied"
    applied_at: datetime = datetime(2026, 7, 1, tzinfo=timezone.utc)


def email(**changes):
    values = {
        "thread_id": "thread-1",
        "sender_email": "recruiting@example.com",
        "received_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
        "company": "Example GmbH",
        "position_title": "Python Backend Developer",
        "external_application_id": None,
    }
    values.update(changes)
    return EmailMatchData(**values)


def application(**changes):
    values = {
        "pk": 1,
        "user_id": 10,
        "company": "Example GmbH",
        "title": "Python Backend Developer",
    }
    values.update(changes)
    return Application(**values)


def test_normalization_preserves_display_values_but_removes_legal_suffixes_for_comparison():
    assert normalize_company("Example, GmbH & Co. KG") == "example"
    assert normalize_position("Python-Backend Developer") == "python backend developer"


def test_exact_match_is_a_high_confidence_suggestion():
    result = match_applications(user_id=10, applications=[application()], email=email())

    assert result.suggested and result.suggested.application.pk == 1
    assert result.suggested.method == "exact_company_title"


def test_thread_match_has_priority_over_other_signals():
    linked = application(pk=2, company="Different GmbH", title="Different role")
    result = match_applications(
        user_id=10,
        applications=[application(), linked],
        email=email(),
        thread_matches=[linked],
    )

    assert result.suggested and result.suggested.application.pk == 2
    assert result.suggested.method == "thread_id"


def test_external_id_match_has_priority_after_thread_match():
    linked = application(pk=2, company="Different GmbH", title="Different role")
    result = match_applications(
        user_id=10,
        applications=[application(), linked],
        email=email(external_application_id="ATS-123"),
        external_id_matches=[linked],
    )

    assert result.suggested and result.suggested.application.pk == 2
    assert result.suggested.method == "external_application_id"


def test_sender_domain_and_title_make_an_ambiguous_manual_review_candidate():
    candidate = application(company="Example AG")
    result = match_applications(
        user_id=10,
        applications=[candidate],
        email=email(company=None, sender_email="jobs@example.com"),
    )

    assert result.suggested is None
    assert result.ambiguous[0].method == "sender_domain_title"


def test_fuzzy_company_and_title_make_an_ambiguous_candidate():
    candidate = application(company="Example Technology GmbH", title="Python Backend Engineer")
    result = match_applications(
        user_id=10,
        applications=[candidate],
        email=email(company="Example Technologies", position_title="Python Backend Engineer"),
    )

    assert result.suggested is None
    assert result.ambiguous[0].method == "fuzzy_company_title"


def test_ambiguous_candidates_are_returned_for_manual_selection():
    first = application(pk=1)
    second = application(pk=2)
    result = match_applications(user_id=10, applications=[first, second], email=email())

    assert result.suggested is None
    assert {candidate.application.pk for candidate in result.ambiguous} == {1, 2}


def test_unmatched_email_has_no_candidate():
    result = match_applications(
        user_id=10,
        applications=[application()],
        email=email(company="Other GmbH", position_title="Designer"),
    )

    assert result.is_unmatched


def test_cross_user_and_terminal_status_applications_are_excluded():
    result = match_applications(
        user_id=10,
        applications=[
            application(pk=1, user_id=11),
            application(pk=2, status="archived"),
            application(pk=3, status="rejected"),
        ],
        email=email(),
    )

    assert result.is_unmatched


def test_platform_and_ats_messages_match_the_same_application():
    candidate = application()
    platform = match_applications(user_id=10, applications=[candidate], email=email())
    ats = match_applications(
        user_id=10,
        applications=[candidate],
        email=email(thread_id="thread-2", sender_email="ats@example.com"),
    )

    assert platform.suggested and platform.suggested.application.pk == candidate.pk
    assert ats.suggested and ats.suggested.application.pk == candidate.pk


def test_same_company_with_a_different_title_does_not_match():
    result = match_applications(
        user_id=10,
        applications=[application(title="Product Designer")],
        email=email(),
    )

    assert result.is_unmatched

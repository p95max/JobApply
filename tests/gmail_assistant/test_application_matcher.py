from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.gmail_assistant.services.application_matcher import (
    EmailMatchData,
    PendingCreateTarget,
    match_applications,
    normalize_company,
    normalize_position,
)
from tests.gmail_assistant.corpus import GMAIL_ASSISTANT_FIXTURES


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
    assert result.suggested.score == 98


def test_thread_match_has_priority_over_other_signals():
    linked = application(pk=2, company="Different GmbH", title="Different role")
    result = match_applications(
        user_id=10,
        applications=[application(), linked],
        email=email(),
        thread_matches=[linked],
    )

    assert result.suggested and result.suggested.application.pk == 2
    assert result.suggested.method == "gmail_thread"


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
        email=email(
            company="Example Technologies",
            position_title="Python Backend Engineer",
            sender_email="jobs@ats-provider.org",
        ),
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


def test_fixture_corpus_platform_and_ats_pair_cannot_create_duplicate_match_targets():
    candidate = application()
    duplicate_pair = [
        fixture for fixture in GMAIL_ASSISTANT_FIXTURES if fixture.duplicate_group == "ats-receipt"
    ]

    matched_application_ids = {
        match_applications(
            user_id=10,
            applications=[candidate],
            email=email(thread_id=fixture.name, sender_email=fixture.sender_email),
        ).suggested.application.pk
        for fixture in duplicate_pair
    }

    assert matched_application_ids == {candidate.pk}


def test_same_company_with_a_different_title_does_not_match():
    result = match_applications(
        user_id=10,
        applications=[application(title="Product Designer")],
        email=email(),
    )

    assert result.is_unmatched


def test_exact_match_can_use_a_pending_create_as_a_temporary_target():
    pending_create = PendingCreateTarget(
        proposal=SimpleNamespace(pk=99),
        company="Example GmbH",
        title="Python Backend Developer",
        applied_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        thread_id="original-thread",
    )

    result = match_applications(
        user_id=10,
        applications=[],
        email=email(thread_id="follow-up-thread"),
        pending_create_targets=[pending_create],
    )

    assert result.suggested is not None
    assert result.suggested.application is None
    assert result.suggested.pending_create_proposal.pk == pending_create.proposal.pk
    assert result.suggested.method == "pending_create_exact_company_title"


def test_generic_rejection_title_matches_one_recent_application_at_company():
    candidate = application(
        company="firstwaters GmbH",
        title="Junior IT Architect (m/w/d)",
        applied_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )

    result = match_applications(
        user_id=10,
        applications=[candidate],
        email=email(
            company="firstwaters",
            position_title="Developer",
            received_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            is_rejection=True,
        ),
    )

    assert result.suggested and result.suggested.application.pk == candidate.pk
    assert result.suggested.method == "company_temporal"
    assert result.suggested.score == 91


def test_generic_rejection_with_multiple_recent_company_applications_stays_ambiguous():
    first = application(pk=1, company="firstwaters GmbH", title="Junior IT Architect")
    second = application(pk=2, company="firstwaters GmbH", title="Python Developer")

    result = match_applications(
        user_id=10,
        applications=[first, second],
        email=email(company="firstwaters", position_title="Developer", is_rejection=True),
    )

    assert result.suggested is None
    assert {candidate.application.pk for candidate in result.ambiguous} == {first.pk, second.pk}
    assert {candidate.method for candidate in result.ambiguous} == {"company_temporal"}


def test_documents_requested_matches_unique_recent_pending_application_at_company():
    pending_create = PendingCreateTarget(
        proposal=SimpleNamespace(pk=101),
        company="ALTEN Consulting Services GmbH",
        title="Developer",
        applied_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        thread_id="application-thread",
    )

    result = match_applications(
        user_id=10,
        applications=[],
        email=email(
            thread_id="documents-thread",
            company="ALTEN Consulting Services GmbH",
            position_title=None,
            received_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            event_type="documents_requested",
        ),
        pending_create_targets=[pending_create],
    )

    assert result.suggested is not None
    assert result.suggested.pending_create_proposal.pk == pending_create.proposal.pk
    assert result.suggested.method == "pending_create_company_temporal_follow_up"
    assert result.suggested.score == 90


def test_interview_invitation_matches_unique_recent_application_at_company():
    candidate = application(
        company="Example GmbH",
        title="Python Backend Developer",
        applied_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    result = match_applications(
        user_id=10,
        applications=[candidate],
        email=email(
            company="Example GmbH",
            position_title=None,
            received_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
            event_type="interview_invitation",
        ),
    )

    assert result.suggested and result.suggested.application.pk == candidate.pk
    assert result.suggested.method == "company_temporal_follow_up"
    assert result.suggested.score == 90


def test_follow_up_with_multiple_recent_company_applications_stays_ambiguous():
    first = application(pk=1, company="Example GmbH", title="Backend Developer")
    second = application(pk=2, company="Example GmbH", title="Frontend Developer")

    result = match_applications(
        user_id=10,
        applications=[first, second],
        email=email(
            company="Example GmbH",
            position_title=None,
            event_type="documents_requested",
        ),
    )

    assert result.suggested is None
    assert {candidate.application.pk for candidate in result.ambiguous} == {1, 2}
    assert {candidate.method for candidate in result.ambiguous} == {"company_temporal_follow_up"}

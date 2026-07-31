from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_stats.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    GmailMessage,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.services.application_matcher import ApplicationMatch, MatchCandidate
from apps.gmail_stats.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_stats.services.proposal_builder import build_proposals
from apps.interviews.models import InterviewEvent, InterviewStatus


@pytest.fixture
def proposal_context(db, django_user_model):
    user = django_user_model.objects.create_user("proposal-user", email="proposal@example.com")
    application = JobApplication.objects.create(
        user=user,
        company="Example GmbH",
        title="Python Developer",
        status=ApplicationStatus.APPLIED,
    )
    message = GmailMessage.objects.create(
        user=user,
        message_id="message-1",
        thread_id="thread-1",
        received_at=timezone.now() + timedelta(hours=1),
        subject="Interview invitation",
    )
    return user, application, message


def analysis(*, user, message, event_type, extracted_data=None):
    return GmailAnalysis.objects.create(
        user=user,
        message=message,
        event_type=event_type,
        is_job_related=True,
        confidence=90,
        extracted_data=extracted_data or {},
    )


def matched(application):
    return ApplicationMatch(
        suggested=MatchCandidate(application, 95, "exact_company_title", ("exact match",)),
        ambiguous=(),
    )


def interview_data(starts_at="2026-08-04T14:30:00+02:00"):
    return {
        "interview": {
            "starts_at": starts_at,
            "location": "Microsoft Teams",
        }
    }


@pytest.mark.django_db
def test_interview_invitation_creates_pending_proposals_only(proposal_context):
    user, application, message = proposal_context
    result = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.INTERVIEW_INVITATION,
            extracted_data=interview_data(),
        ),
        match=matched(application),
    )

    assert {proposal.proposal_type for proposal in result} == {
        ProposalType.UPDATE_APPLICATION,
        ProposalType.CREATE_INTERVIEW,
    }
    assert all(proposal.status == ProposalStatus.PENDING for proposal in result)
    application.refresh_from_db()
    assert application.status == ApplicationStatus.APPLIED
    assert InterviewEvent.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("event_type", [GmailEventType.NOISE, GmailEventType.UNKNOWN])
def test_noise_and_unknown_create_no_proposals(proposal_context, event_type):
    user, application, message = proposal_context

    assert build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=event_type),
        match=matched(application),
    ) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "event_type",
    [GmailEventType.APPLICATION_SENT, GmailEventType.APPLICATION_RECEIVED],
)
def test_unmatched_application_event_can_propose_new_application(proposal_context, event_type):
    user, _, message = proposal_context
    result = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=event_type,
            extracted_data={"company": "New GmbH", "position_title": "Backend Engineer"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )

    proposal = result[0]
    assert proposal.proposal_type == ProposalType.CREATE_APPLICATION
    assert proposal.application is None
    assert proposal.changes["application"]["operation"] == "create"


@pytest.mark.django_db
def test_action_required_proposal_does_not_change_status(proposal_context):
    user, application, message = proposal_context
    result = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
            extracted_data={"action_text": "Confirm your email", "deadline_at": None},
        ),
        match=matched(application),
    )

    assert result[0].proposal_type == ProposalType.ACTION_REQUIRED
    assert result[0].changes["action"]["required"] is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("event_type", "expected_type"),
    [
        (GmailEventType.APPLICATION_CONFIRMATION_REQUIRED, ProposalType.ACTION_REQUIRED),
        (GmailEventType.DOCUMENTS_REQUESTED, ProposalType.ACTION_REQUIRED),
        (GmailEventType.GENERAL_UPDATE, ProposalType.UPDATE_APPLICATION),
        (GmailEventType.SCREENING, ProposalType.UPDATE_APPLICATION),
        (GmailEventType.OFFER, ProposalType.UPDATE_APPLICATION),
        (GmailEventType.REJECTION, ProposalType.UPDATE_APPLICATION),
        (GmailEventType.WITHDRAWAL_CONFIRMATION, ProposalType.UPDATE_APPLICATION),
    ],
)
def test_actionable_events_create_the_expected_proposal_type(proposal_context, event_type, expected_type):
    user, application, message = proposal_context

    proposals = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=event_type),
        match=matched(application),
    )

    assert expected_type in {proposal.proposal_type for proposal in proposals}


@pytest.mark.django_db
def test_builder_deduplicates_active_proposals(proposal_context):
    user, application, message = proposal_context
    record = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.INTERVIEW_INVITATION,
        extracted_data=interview_data(),
    )

    build_proposals(message=message, analysis=record, match=matched(application))
    build_proposals(message=message, analysis=record, match=matched(application))

    assert ApplicationUpdateProposal.objects.filter(status=ProposalStatus.PENDING).count() == 2


@pytest.mark.django_db
def test_accept_is_atomic_and_idempotent(proposal_context):
    user, application, message = proposal_context
    record = analysis(user=user, message=message, event_type=GmailEventType.GENERAL_UPDATE)
    proposal = build_proposals(message=message, analysis=record, match=matched(application))[0]

    first = apply_proposal(proposal=proposal, user=user)
    second = apply_proposal(proposal=proposal, user=user)

    application.refresh_from_db()
    message.refresh_from_db()
    assert first.already_accepted is False
    assert second.already_accepted is True
    assert application.status == ApplicationStatus.REPLIED
    assert message.application_id == application.pk
    assert proposal.status == ProposalStatus.PENDING
    first.proposal.refresh_from_db()
    assert first.proposal.status == ProposalStatus.ACCEPTED
    assert first.proposal.reviewed_at is not None


@pytest.mark.django_db
def test_accept_rejects_proposal_owned_by_another_user(proposal_context, django_user_model):
    user, application, message = proposal_context
    other = django_user_model.objects.create_user("other", email="other@example.com")
    proposal = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.GENERAL_UPDATE),
        match=matched(application),
    )[0]

    with pytest.raises(ProposalApplyError, match="not found"):
        apply_proposal(proposal=proposal, user=other)


@pytest.mark.django_db
def test_accept_revalidates_status_transition(proposal_context):
    user, application, message = proposal_context
    proposal = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.GENERAL_UPDATE),
        match=matched(application),
    )[0]
    application.status = ApplicationStatus.OFFER
    application.save()

    with pytest.raises(ProposalApplyError, match="status transition"):
        apply_proposal(proposal=proposal, user=user)


@pytest.mark.django_db
def test_interview_accept_creates_one_event_and_reschedule_updates_it(proposal_context):
    user, application, message = proposal_context
    invitation = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.INTERVIEW_INVITATION,
        extracted_data=interview_data(),
    )
    proposals = build_proposals(message=message, analysis=invitation, match=matched(application))
    for proposal in proposals:
        apply_proposal(proposal=proposal, user=user)
    event = InterviewEvent.objects.get(application=application)

    reschedule_message = GmailMessage.objects.create(
        user=user,
        message_id="message-2",
        thread_id="thread-1",
        received_at=message.received_at + timedelta(days=1),
    )
    reschedule_proposals = build_proposals(
        message=reschedule_message,
        analysis=analysis(
            user=user,
            message=reschedule_message,
            event_type=GmailEventType.INTERVIEW_RESCHEDULED,
            extracted_data=interview_data("2026-08-05T14:30:00+02:00"),
        ),
        match=matched(application),
    )
    reschedule = next(
        proposal for proposal in reschedule_proposals if proposal.proposal_type == ProposalType.UPDATE_INTERVIEW
    )
    apply_proposal(proposal=reschedule, user=user)

    event.refresh_from_db()
    assert InterviewEvent.objects.filter(application=application).count() == 1
    assert event.starts_at.isoformat().startswith("2026-08-05T12:30:00")


@pytest.mark.django_db
def test_invitation_without_datetime_can_be_completed_with_a_manual_override(proposal_context):
    user, application, message = proposal_context
    proposals = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.INTERVIEW_INVITATION,
            extracted_data={"interview": {"starts_at": None, "location": "Office"}},
        ),
        match=matched(application),
    )
    proposal = next(proposal for proposal in proposals if proposal.proposal_type == ProposalType.CREATE_INTERVIEW)

    result = apply_proposal(
        proposal=proposal,
        user=user,
        overrides={"interview": {"starts_at": "2026-08-06T09:00:00+02:00"}},
    )

    assert result.interview and result.interview.starts_at.isoformat().startswith("2026-08-06T07:00:00")


@pytest.mark.django_db
def test_cancellation_cancels_interview_without_downgrading_application(proposal_context):
    user, application, message = proposal_context
    application.status = ApplicationStatus.INTERVIEW
    application.save()
    event = InterviewEvent.objects.create(
        user=user,
        application=application,
        starts_at=message.received_at + timedelta(days=2),
    )
    proposals = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.INTERVIEW_CANCELLED),
        match=matched(application),
    )
    proposal = next(proposal for proposal in proposals if proposal.proposal_type == ProposalType.UPDATE_INTERVIEW)

    apply_proposal(proposal=proposal, user=user)

    application.refresh_from_db()
    event.refresh_from_db()
    assert application.status == ApplicationStatus.INTERVIEW
    assert event.status == InterviewStatus.CANCELED


@pytest.mark.django_db
def test_reject_and_ignore_are_ownership_safe(proposal_context):
    user, application, message = proposal_context
    proposal = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.GENERAL_UPDATE),
        match=matched(application),
    )[0]

    reviewed = review_proposal(proposal=proposal, user=user, status=ProposalStatus.IGNORED)

    assert reviewed.status == ProposalStatus.IGNORED
    assert reviewed.reviewed_at is not None

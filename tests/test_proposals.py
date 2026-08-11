from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.applications.models import ApplicationStatus, JobApplication
from apps.gmail_assistant.models import (
    ApplicationUpdateProposal,
    GmailAnalysis,
    GmailEventType,
    ProposalStatus,
    ProposalType,
)
from apps.gmail_stats.models import GmailMessage
from apps.gmail_assistant.services.application_matcher import ApplicationMatch, MatchCandidate, match_for_message
from apps.gmail_assistant.services.apply_proposal import ProposalApplyError, apply_proposal, review_proposal
from apps.gmail_assistant.services.proposal_builder import build_proposals, rebuild_pending_proposals_for_user
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
            extracted_data={"company": "New GmbH", "position_title": "Backend Engineer", "location": "Berlin"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )

    proposal = result[0]
    assert proposal.proposal_type == ProposalType.CREATE_APPLICATION
    assert proposal.application is None
    assert proposal.changes["application"]["operation"] == "create"
    assert proposal.changes["application"]["location"] == "Berlin"


@pytest.mark.django_db
def test_job_board_name_is_not_used_as_a_new_application_company(proposal_context):
    user, _, message = proposal_context

    result = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.APPLICATION_RECEIVED,
            extracted_data={"company": "Stepstone", "position_title": "Python Software Engineer"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )

    assert result == []


@pytest.mark.django_db
def test_reanalysis_removes_an_existing_job_board_create_proposal(proposal_context):
    user, _, message = proposal_context
    record = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "Real Company", "position_title": "Python Software Engineer"},
    )
    build_proposals(message=message, analysis=record, match=ApplicationMatch(suggested=None, ambiguous=()))
    record.extracted_data = {"company": "Indeed Ireland Operations Limited", "position_title": "Python Software Engineer"}
    record.save(update_fields=["extracted_data"])

    result = build_proposals(message=message, analysis=record, match=ApplicationMatch(suggested=None, ambiguous=()))

    assert result == []
    assert not ApplicationUpdateProposal.objects.filter(
        message=message,
        analysis=record,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).exists()


@pytest.mark.django_db
def test_reanalysis_removes_stale_create_when_event_is_no_longer_an_application(proposal_context):
    user, _, message = proposal_context
    record = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "Real Company", "position_title": "Python Software Engineer"},
    )
    build_proposals(message=message, analysis=record, match=ApplicationMatch(suggested=None, ambiguous=()))
    record.event_type = GmailEventType.GENERAL_UPDATE
    record.save(update_fields=["event_type"])

    result = build_proposals(message=message, analysis=record, match=ApplicationMatch(suggested=None, ambiguous=()))

    assert result == []
    assert not ApplicationUpdateProposal.objects.filter(
        message=message,
        analysis=record,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).exists()


@pytest.mark.django_db
def test_matching_pending_create_intent_does_not_create_a_second_application_proposal(proposal_context):
    user, _, message = proposal_context
    first = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.APPLICATION_RECEIVED,
            extracted_data={"company": "Smart Systems Hub GmbH", "position_title": "Python Software Engineer"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )[0]
    second_message = GmailMessage.objects.create(
        user=user,
        message_id="message-duplicate",
        thread_id="thread-duplicate",
        received_at=message.received_at + timedelta(minutes=2),
        subject="Application received again",
        from_email="no-reply@example.org",
    )

    result = build_proposals(
        message=second_message,
        analysis=analysis(
            user=user,
            message=second_message,
            event_type=GmailEventType.APPLICATION_RECEIVED,
            extracted_data={"company": "Smart Systems Hub GmbH", "position_title": "Python Software Engineer"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )

    first.refresh_from_db()
    assert result == []
    assert ApplicationUpdateProposal.objects.filter(
        user=user,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).count() == 1
    assert first.changes["related_messages"][0]["subject"] == "Application received again"


@pytest.mark.django_db
def test_later_same_company_and_title_is_not_collapsed_into_pending_create(proposal_context):
    user, _, message = proposal_context
    first_analysis = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "Separate GmbH", "position_title": "Platform Developer"},
    )
    build_proposals(
        message=message,
        analysis=first_analysis,
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )
    later_message = GmailMessage.objects.create(
        user=user,
        message_id="later-application",
        thread_id="later-thread",
        received_at=message.received_at + timedelta(days=7),
        subject="Application received again",
        from_email="no-reply@example.org",
    )
    later_analysis = analysis(
        user=user,
        message=later_message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "Separate GmbH", "position_title": "Platform Developer"},
    )
    match = match_for_message(
        user=user,
        message=later_message,
        extracted_data=later_analysis.extracted_data,
        event_type=later_analysis.event_type,
    )
    assert match.suggested is not None
    assert match.suggested.method == "pending_create_exact_company_title"

    build_proposals(message=later_message, analysis=later_analysis, match=match)

    assert ApplicationUpdateProposal.objects.filter(
        user=user,
        proposal_type=ProposalType.CREATE_APPLICATION,
        status=ProposalStatus.PENDING,
    ).count() == 2


@pytest.mark.django_db
def test_rebuilding_pending_create_proposal_refreshes_extracted_location(proposal_context):
    user, _, message = proposal_context
    record = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "New GmbH", "position_title": "Backend Engineer"},
    )
    unmatched = ApplicationMatch(suggested=None, ambiguous=())
    proposal = build_proposals(message=message, analysis=record, match=unmatched)[0]

    record.extracted_data["location"] = "Leipzig"
    record.save(update_fields=["extracted_data"])
    refreshed = build_proposals(message=message, analysis=record, match=unmatched)[0]

    assert refreshed.pk == proposal.pk
    assert refreshed.changes["application"]["location"] == "Leipzig"


@pytest.mark.django_db
def test_unmatched_rejection_requires_manual_application_assignment(proposal_context):
    user, _, message = proposal_context
    result = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.REJECTION),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )

    proposal = result[0]
    assert proposal.proposal_type == ProposalType.UPDATE_APPLICATION
    assert proposal.application is None
    assert proposal.changes["application"]["status"] == {"old": None, "new": "rejected"}


@pytest.mark.django_db
def test_manually_linked_create_proposal_reuses_the_application(proposal_context):
    user, application, message = proposal_context
    proposal = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.APPLICATION_RECEIVED,
            extracted_data={"company": "Example GmbH", "position_title": "Python Developer"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )[0]
    proposal.application = application
    proposal.match_method = "manual"
    proposal.save(update_fields=["application", "match_method"])

    result = apply_proposal(proposal=proposal, user=user)

    assert result.application == application
    assert JobApplication.objects.filter(user=user).count() == 1


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
def test_unlinked_action_cannot_be_accepted(proposal_context):
    user, _, message = proposal_context
    proposal = build_proposals(
        message=message,
        analysis=analysis(
            user=user,
            message=message,
            event_type=GmailEventType.APPLICATION_CONFIRMATION_REQUIRED,
            extracted_data={"action_text": "Confirm your application"},
        ),
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )[0]

    with pytest.raises(ProposalApplyError, match="assign an application"):
        apply_proposal(proposal=proposal, user=user)

    proposal.refresh_from_db()
    assert proposal.status == ProposalStatus.PENDING


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
def test_historical_rejection_after_application_date_proposes_rejected_status(proposal_context):
    user, application, message = proposal_context
    application.applied_at = timezone.now() - timedelta(days=2)
    application.save()
    message.received_at = application.applied_at + timedelta(hours=1)
    message.save(update_fields=["received_at"])

    proposal = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.REJECTION),
        match=matched(application),
    )[0]

    assert proposal.changes["application"]["status"] == {"old": "applied", "new": "rejected"}
    apply_proposal(proposal=proposal, user=user)
    application.refresh_from_db()
    assert application.status == ApplicationStatus.REJECTED
    assert application.applied_at == message.received_at - timedelta(hours=1)
    assert application.recruiter_reply_at == message.received_at


@pytest.mark.django_db
def test_rejection_cannot_override_the_original_application_date(proposal_context):
    user, application, message = proposal_context
    original_applied_at = application.applied_at
    proposal = build_proposals(
        message=message,
        analysis=analysis(user=user, message=message, event_type=GmailEventType.REJECTION),
        match=matched(application),
    )[0]

    with pytest.raises(ProposalApplyError, match="rejection proposals"):
        apply_proposal(
            proposal=proposal,
            user=user,
            overrides={"application": {"applied_at": message.received_at.isoformat()}},
        )

    application.refresh_from_db()
    assert application.applied_at == original_applied_at


@pytest.mark.django_db
def test_accepted_create_proposal_links_itself_and_replies_in_same_thread_match(proposal_context):
    user, _, message = proposal_context
    create_analysis = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "firstwaters", "position_title": "Junior IT Architect"},
    )
    create = build_proposals(
        message=message,
        analysis=create_analysis,
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )[0]

    result = apply_proposal(proposal=create, user=user)
    create.refresh_from_db()
    assert create.application_id == result.application.pk

    rejection_message = GmailMessage.objects.create(
        user=user,
        message_id="thread-rejection",
        thread_id=message.thread_id,
        received_at=message.received_at + timedelta(days=2),
        from_email="careers@firstwaters.de",
    )
    rejection_analysis = analysis(
        user=user,
        message=rejection_message,
        event_type=GmailEventType.REJECTION,
        extracted_data={"company": "firstwaters", "position_title": "Developer"},
    )

    match = match_for_message(
        user=user,
        message=rejection_message,
        extracted_data=rejection_analysis.extracted_data,
        event_type=rejection_analysis.event_type,
    )
    assert match.suggested and match.suggested.application.pk == result.application.pk
    assert match.suggested.method == "gmail_thread"


@pytest.mark.django_db
def test_pending_create_is_a_temporary_target_until_it_is_accepted(proposal_context):
    user, _, message = proposal_context
    create_analysis = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "firstwaters", "position_title": "Junior IT Architect"},
    )
    create = build_proposals(
        message=message,
        analysis=create_analysis,
        match=ApplicationMatch(suggested=None, ambiguous=()),
    )[0]
    rejection_message = GmailMessage.objects.create(
        user=user,
        message_id="pending-create-rejection",
        thread_id=message.thread_id,
        received_at=message.received_at + timedelta(days=2),
        from_email="careers@firstwaters.de",
    )
    rejection_analysis = analysis(
        user=user,
        message=rejection_message,
        event_type=GmailEventType.REJECTION,
        extracted_data={"company": "firstwaters", "position_title": "Developer"},
    )

    match = match_for_message(
        user=user,
        message=rejection_message,
        extracted_data=rejection_analysis.extracted_data,
        event_type=rejection_analysis.event_type,
    )
    assert match.suggested is not None
    assert match.suggested.application is None
    assert match.suggested.pending_create_proposal.pk == create.pk
    assert match.suggested.method == "pending_create_gmail_thread"

    rejection = build_proposals(message=rejection_message, analysis=rejection_analysis, match=match)[0]
    assert rejection.application is None
    assert rejection.changes["pending_create_proposal_id"] == create.pk
    assert rejection.changes["application"]["status"] == {"old": "applied", "new": "rejected"}

    created = apply_proposal(proposal=create, user=user)
    rejection.refresh_from_db()
    assert rejection.application_id == created.application.pk
    assert rejection.message.application_id == created.application.pk

    apply_proposal(proposal=rejection, user=user)
    created.application.refresh_from_db()
    assert created.application.status == ApplicationStatus.REJECTED


@pytest.mark.django_db
def test_full_rebuild_orders_pending_create_before_a_later_followup(proposal_context):
    user, _, message = proposal_context
    original = analysis(
        user=user,
        message=message,
        event_type=GmailEventType.APPLICATION_RECEIVED,
        extracted_data={"company": "firstwaters", "position_title": "Junior IT Architect"},
    )
    rejection_message = GmailMessage.objects.create(
        user=user,
        message_id="ordered-rejection",
        thread_id="later-thread",
        received_at=message.received_at + timedelta(days=2),
        from_email="careers@firstwaters.de",
    )
    rejection = analysis(
        user=user,
        message=rejection_message,
        event_type=GmailEventType.REJECTION,
        extracted_data={"company": "firstwaters", "position_title": "Developer"},
    )

    rebuild_pending_proposals_for_user(user=user)

    create = ApplicationUpdateProposal.objects.get(analysis=original, proposal_type=ProposalType.CREATE_APPLICATION)
    update = ApplicationUpdateProposal.objects.get(analysis=rejection, proposal_type=ProposalType.UPDATE_APPLICATION)
    assert update.application is None
    assert update.changes["pending_create_proposal_id"] == create.pk
    assert update.match_method == "pending_create_company_temporal"


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

    assert result.interview and result.interview.starts_at.isoformat().startswith("2026-08-06T09:00:00+02:00")


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

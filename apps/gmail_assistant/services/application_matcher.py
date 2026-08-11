from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Iterable

from django.conf import settings

_COMPANY_SUFFIXES = frozenset(
    {
        "ag",
        "bv",
        "co",
        "corp",
        "corporation",
        "gmbh",
        "inc",
        "kg",
        "ltd",
        "llc",
        "limited",
        "mbh",
        "plc",
        "se",
        "ug",
    }
)
_POSITION_NOISE_TOKENS = frozenset({"m", "w", "d", "f", "x", "gn"})
_EXCLUDED_STATUSES = frozenset({"archived", "rejected"})
_GENERIC_POSITION_TITLES = frozenset(
    {
        "developer",
        "software developer",
        "softwareentwickler",
        "entwickler",
        "engineer",
        "software engineer",
        "it",
    }
)


@dataclass(frozen=True)
class EmailMatchData:
    """Minimal extracted email data needed for application matching."""

    thread_id: str
    sender_email: str
    received_at: datetime
    company: str | None
    position_title: str | None
    external_application_id: str | None
    is_rejection: bool = False


@dataclass(frozen=True)
class MatchCandidate:
    """An explainable candidate that requires manual review before any write."""

    application: Any
    score: int
    method: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationMatch:
    """A deterministic application-match outcome with no side effects."""

    suggested: MatchCandidate | None
    ambiguous: tuple[MatchCandidate, ...]

    @property
    def is_unmatched(self) -> bool:
        """Return whether no candidate reached the manual-review threshold."""
        return self.suggested is None and not self.ambiguous


def normalize_company(value: str | None) -> str:
    """Normalize a company name only for comparison, preserving stored display values."""
    tokens = _normalized_tokens(value)
    return " ".join(token for token in tokens if token not in _COMPANY_SUFFIXES)


def normalize_position(value: str | None) -> str:
    """Normalize a position title and drop common gender-marker noise."""
    return " ".join(token for token in _normalized_tokens(value) if token not in _POSITION_NOISE_TOKENS)


def match_applications(
    *,
    user_id: int,
    applications: Iterable[Any],
    email: EmailMatchData,
    thread_matches: Iterable[Any] = (),
    external_id_matches: Iterable[Any] = (),
) -> ApplicationMatch:
    """Rank user-scoped applications without changing any application state."""
    eligible = {
        application.pk: application
        for application in applications
        if application.user_id == user_id and application.status not in _EXCLUDED_STATUSES
    }
    if not eligible:
        return ApplicationMatch(suggested=None, ambiguous=())

    for application in thread_matches:
        if application.pk in eligible:
            return _outcome((MatchCandidate(application, 100, "gmail_thread", ("matching Gmail thread",)),))

    for application in external_id_matches:
        if application.pk in eligible:
            return _outcome(
                (
                    MatchCandidate(
                        application,
                        98,
                        "external_application_id",
                        ("matching external application ID",),
                    ),
                )
            )

    candidates = [
        candidate
        for application in eligible.values()
        if (candidate := _score_candidate(application, email)) is not None
    ]
    scored = _outcome(tuple(candidates))
    # Preserve exact company/title and external-ID outcomes before falling back
    # to the more permissive rejection-only company/time window.
    if scored.suggested is not None:
        return scored

    temporal_candidates = _rejection_company_temporal_candidates(
        applications=eligible.values(),
        email=email,
    )
    if len(temporal_candidates) == 1:
        return ApplicationMatch(suggested=temporal_candidates[0], ambiguous=())
    if temporal_candidates:
        return ApplicationMatch(suggested=None, ambiguous=temporal_candidates)
    return scored


def match_for_message(
    *,
    user: Any,
    message: Any,
    extracted_data: dict[str, Any],
    event_type: str | None = None,
) -> ApplicationMatch:
    """Match one Gmail message using only applications owned by the supplied user."""
    from apps.applications.models import JobApplication
    from apps.gmail_assistant.models import ApplicationUpdateProposal, GmailAnalysis

    email = EmailMatchData(
        thread_id=message.thread_id,
        sender_email=message.from_email,
        received_at=message.received_at,
        company=_optional_string(extracted_data.get("company")),
        position_title=_optional_string(extracted_data.get("position_title")),
        external_application_id=_optional_string(extracted_data.get("external_application_id")),
        is_rejection=event_type == "rejection",
    )
    # The analysis event is stored on the model, rather than in extracted data.
    # Keep the optional JSON hint for callers outside the sync pipeline, then
    # replace it below when the analysis exists.
    if event_type is None:
        analysis = GmailAnalysis.objects.filter(user=user, message=message).only("event_type").first()
        event_type = analysis.event_type if analysis is not None else None
    if event_type is not None:
        email = EmailMatchData(
            thread_id=email.thread_id,
            sender_email=email.sender_email,
            received_at=email.received_at,
            company=email.company,
            position_title=email.position_title,
            external_application_id=email.external_application_id,
            is_rejection=event_type == "rejection",
        )
    applications = JobApplication.objects.filter(user=user).exclude(status__in=_EXCLUDED_STATUSES)
    thread_application_ids = set(
        JobApplication.objects.filter(
            user=user,
            gmail_messages__thread_id=message.thread_id,
        )
        .exclude(status__in=_EXCLUDED_STATUSES)
        .values_list("pk", flat=True)
    )
    thread_application_ids.update(
        ApplicationUpdateProposal.objects.filter(
            user=user,
            message__thread_id=message.thread_id,
            application__isnull=False,
        ).values_list("application_id", flat=True)
    )
    if message.application_id:
        thread_application_ids.add(message.application_id)
    thread_matches = JobApplication.objects.filter(
        user=user,
        pk__in=thread_application_ids,
    ).exclude(status__in=_EXCLUDED_STATUSES)

    external_id_matches: Iterable[Any] = ()
    if email.external_application_id:
        analyses = (
            GmailAnalysis.objects.filter(
                user=user,
                message__application__isnull=False,
                extracted_data__external_application_id=email.external_application_id,
            )
            .select_related("message__application")
            .exclude(message__application__status__in=_EXCLUDED_STATUSES)
        )
        external_id_matches = tuple(analysis.message.application for analysis in analyses)

    return match_applications(
        user_id=user.pk,
        applications=applications,
        email=email,
        thread_matches=thread_matches,
        external_id_matches=external_id_matches,
    )


def _normalized_tokens(value: str | None) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value or "").casefold()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", normalized)


def _score_candidate(application: Any, email: EmailMatchData) -> MatchCandidate | None:
    company = normalize_company(email.company)
    title = normalize_position(email.position_title)
    application_company = normalize_company(application.company)
    application_title = normalize_position(application.title)
    company_ratio = _ratio(company, application_company)
    title_ratio = _ratio(title, application_title)
    sender_domain_match = _sender_domain_matches_company(email.sender_email, application_company)
    evidence: list[str] = []

    if company and title and company == application_company and title == application_title:
        score, method = 95, "exact_company_title"
        evidence.extend(("exact normalized company", "exact normalized title"))
    elif company and title and company == application_company and _title_contains(title, application_title):
        score, method = 92, "exact_company_title_containment"
        evidence.extend(("exact normalized company", "one normalized title contains the other"))
    elif sender_domain_match and title_ratio >= 80:
        score, method = 82, "sender_domain_title"
        evidence.extend(("sender domain matches company", "similar normalized title"))
    elif company_ratio >= 85 and title_ratio >= 80:
        score, method = 75, "fuzzy_company_title"
        evidence.extend(("similar normalized company", "similar normalized title"))
    else:
        return None

    if _within_application_window(email.received_at, application.applied_at):
        score = min(100, score + 3)
        evidence.append("email is near application date")
    return MatchCandidate(application, score, method, tuple(evidence))


def _rejection_company_temporal_candidates(
    *,
    applications: Iterable[Any],
    email: EmailMatchData,
) -> tuple[MatchCandidate, ...]:
    """Resolve a rejection only when one recent active record shares its company.

    Employer replies commonly shorten the role to "Developer" or omit it
    entirely. A matching company plus a bounded application timeline is more
    reliable than fuzzy title scoring in that case. Several records remain a
    manual decision on purpose.
    """
    company = normalize_company(email.company)
    if not email.is_rejection or not company:
        return ()

    candidates = [
        MatchCandidate(
            application,
            91 if _is_generic_position(email.position_title) else 90,
            "company_temporal",
            (
                "exact normalized company",
                "application precedes rejection within configured lookback",
                *("generic or missing role ignored" if _is_generic_position(email.position_title) else (),),
            ),
        )
        for application in applications
        if normalize_company(application.company) == company
        and _is_recent_application_before_message(application.applied_at, email.received_at)
    ]
    if len(candidates) == 1:
        return tuple(candidates)
    return tuple(
        MatchCandidate(
            candidate.application,
            85,
            "company_temporal",
            candidate.evidence + ("more than one recent application at company",),
        )
        for candidate in candidates
    )


def _title_contains(left: str, right: str) -> bool:
    return bool(left and right and (left in right or right in left))


def _outcome(candidates: tuple[MatchCandidate, ...]) -> ApplicationMatch:
    ordered = tuple(sorted(candidates, key=lambda candidate: (-candidate.score, candidate.application.pk)))
    high_confidence = tuple(candidate for candidate in ordered if candidate.score >= 90)
    if len(high_confidence) == 1:
        return ApplicationMatch(suggested=high_confidence[0], ambiguous=())
    ambiguous = tuple(candidate for candidate in ordered if candidate.score >= 70)
    return ApplicationMatch(suggested=None, ambiguous=ambiguous)


def _ratio(left: str, right: str) -> int:
    if not left or not right:
        return 0
    return round(SequenceMatcher(a=left, b=right).ratio() * 100)


def _sender_domain_matches_company(sender_email: str, normalized_company: str) -> bool:
    domain = sender_email.rsplit("@", 1)[-1].casefold().split(".", 1)[0]
    return bool(domain and normalized_company and domain in normalized_company.replace(" ", ""))


def _within_application_window(received_at: datetime, applied_at: datetime) -> bool:
    return abs((received_at - applied_at).days) <= 90


def _is_recent_application_before_message(applied_at: datetime, received_at: datetime) -> bool:
    return (
        applied_at <= received_at
        and (received_at - applied_at).days <= settings.GMAIL_REJECTION_MATCH_LOOKBACK_DAYS
    )


def _is_generic_position(value: str | None) -> bool:
    return normalize_position(value) in _GENERIC_POSITION_TITLES or not normalize_position(value)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None

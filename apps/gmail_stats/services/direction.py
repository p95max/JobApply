from __future__ import annotations

from email.utils import getaddresses, parseaddr

from apps.gmail_stats.models import GmailDirection


def _clean_email(address: str) -> str:
    normalized = address.strip().casefold()
    return normalized if "@" in normalized else ""


def normalize_email(value: str) -> str:
    """Return a case-insensitive email address suitable for comparison."""
    _, address = parseaddr(value or "")
    return _clean_email(address)


def parse_sender(value: str) -> tuple[str, str]:
    """Parse an email header without raising for malformed input."""
    name, address = parseaddr(value or "")
    return name.strip()[:255], _clean_email(address)[:254]


def parse_recipients(values: list[str]) -> list[str]:
    """Return unique recipient addresses from a collection of headers."""
    addresses: list[str] = []
    for _, address in getaddresses(values):
        normalized = _clean_email(address)
        if normalized and normalized not in addresses:
            addresses.append(normalized[:254])
    return addresses


def determine_direction(
    *,
    from_email: str,
    recipient_emails: list[str],
    profile_email: str,
    aliases: tuple[str, ...] = (),
) -> str:
    """Classify a message direction using only authenticated mailbox addresses."""
    account_addresses = {normalize_email(profile_email)}
    account_addresses.update(normalize_email(alias) for alias in aliases)
    account_addresses.discard("")

    sender = normalize_email(from_email)
    recipients = {normalize_email(address) for address in recipient_emails}
    recipients.discard("")

    if sender and sender in account_addresses:
        return GmailDirection.OUTBOUND
    if sender and sender not in account_addresses and recipients & account_addresses:
        return GmailDirection.INBOUND
    return GmailDirection.UNKNOWN

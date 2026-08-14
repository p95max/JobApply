from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from apps.gmail_stats.services.direction import parse_recipients, parse_sender


class _HTMLTextExtractor(HTMLParser):
    """Converts safe HTML email content into readable text without executing it."""

    _BLOCK_TAGS = {"address", "br", "div", "li", "p", "table", "tr"}
    _HIDDEN_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN_TAGS:
            self._hidden_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


@dataclass(frozen=True)
class ParsedGmailMessage:
    """A bounded, sanitized representation of a Gmail message for analysis."""

    from_name: str
    from_email: str
    to_emails: list[str]
    subject: str
    rfc_message_id: str
    text: str
    content_hash: str
    html_text: str = ""


def _header_value(headers: list[dict[str, Any]], name: str) -> str:
    normalized_name = name.casefold()
    for header in headers:
        if str(header.get("name") or "").casefold() == normalized_name:
            return str(header.get("value") or "")
    return ""


def _decode_body(data: str, charset: str | None) -> str:
    padding = "=" * (-len(data) % 4)
    try:
        decoded = base64.urlsafe_b64decode(data + padding)
    except (ValueError, TypeError):
        return ""

    for encoding in (charset, "utf-8", "latin-1"):
        if not encoding:
            continue
        try:
            return decoded.decode(encoding, errors="replace")
        except LookupError:
            continue
    return ""


def _part_charset(part: dict[str, Any]) -> str | None:
    for header in part.get("headers") or []:
        if str(header.get("name") or "").casefold() != "content-type":
            continue
        match = re.search(r"charset=[\"']?([^\s;\"']+)", str(header.get("value") or ""), re.I)
        if match:
            return match.group(1)
    return None


def _text_parts(part: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if part.get("filename") or (part.get("body") or {}).get("attachmentId"):
        return plain_parts, html_parts

    mime_type = str(part.get("mimeType") or "").casefold()
    body_data = str((part.get("body") or {}).get("data") or "")
    if body_data and mime_type in {"text/plain", "text/html"}:
        body = _decode_body(body_data, _part_charset(part))
        if mime_type == "text/plain":
            plain_parts.append(body)
        else:
            html_parts.append(body)

    for child in part.get("parts") or []:
        child_plain, child_html = _text_parts(child)
        plain_parts.extend(child_plain)
        html_parts.extend(child_html)
    return plain_parts, html_parts


def _html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def _strip_quoted_history(value: str) -> str:
    markers = (
        r"(?im)^on .+wrote:\s*$",
        r"(?im)^-{2,}\s*original message\s*-{2,}\s*$",
        r"(?im)^from:\s.+\n(?:sent|date):\s.+$",
    )
    positions = [match.start() for pattern in markers if (match := re.search(pattern, value))]
    return value[: min(positions)] if positions else value


def _normalize_text(value: str, max_chars: int) -> str:
    value = _strip_quoted_history(value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]*\n+", "\n\n", value)
    return value.strip()[:max_chars]


def parse_gmail_message(raw_message: dict[str, Any], max_chars: int = 12000) -> ParsedGmailMessage:
    """Extract and sanitize a bounded text body from a Gmail full-format message."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

    payload = raw_message.get("payload") or {}
    headers = payload.get("headers") or []
    from_name, from_email = parse_sender(_header_value(headers, "From"))
    to_emails = parse_recipients(
        [
            _header_value(headers, "To"),
            _header_value(headers, "Cc"),
            _header_value(headers, "Delivered-To"),
        ]
    )
    plain_parts, html_parts = _text_parts(payload)
    raw_text = "\n\n".join(part for part in plain_parts if part)
    html_text = _normalize_text(
        "\n\n".join(_html_to_text(part) for part in html_parts if part),
        max_chars,
    )
    if not raw_text:
        raw_text = html_text
    text = _normalize_text(raw_text, max_chars)

    return ParsedGmailMessage(
        from_name=from_name,
        from_email=from_email,
        to_emails=to_emails,
        subject=_header_value(headers, "Subject")[:500],
        rfc_message_id=_header_value(headers, "Message-ID")[:998],
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        html_text=html_text,
    )

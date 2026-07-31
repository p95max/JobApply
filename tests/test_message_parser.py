from __future__ import annotations

import base64

import pytest

from apps.gmail_stats.services.message_parser import parse_gmail_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def message(payload: dict) -> dict:
    return {"id": "gmail-id", "payload": payload}


def headers() -> list[dict[str, str]]:
    return [
        {"name": "From", "value": "Recruiter <recruiter@example.org>"},
        {"name": "To", "value": "Candidate <candidate@example.com>"},
        {"name": "Subject", "value": "Interview update"},
        {"name": "Message-ID", "value": "<message@example.org>"},
    ]


def text_part(mime_type: str, value: str, **extra: object) -> dict:
    return {"mimeType": mime_type, "body": {"data": encoded(value)}, **extra}


def test_parser_extracts_plain_text_and_headers():
    parsed = parse_gmail_message(message({"headers": headers(), **text_part("text/plain", "Hello candidate.")}))

    assert parsed.from_name == "Recruiter"
    assert parsed.from_email == "recruiter@example.org"
    assert parsed.to_emails == ["candidate@example.com"]
    assert parsed.subject == "Interview update"
    assert parsed.rfc_message_id == "<message@example.org>"
    assert parsed.text == "Hello candidate."


def test_parser_falls_back_to_html_without_scripts_or_styles():
    parsed = parse_gmail_message(
        message(
            {
                "headers": headers(),
                **text_part(
                    "text/html",
                    "<style>.hidden { display: none; }</style><p>Hello <b>candidate</b>.</p><script>alert(1)</script>",
                ),
            }
        )
    )

    assert parsed.text == "Hello candidate."
    assert "alert" not in parsed.text
    assert "hidden" not in parsed.text


def test_parser_prefers_plain_text_in_multipart_alternative():
    parsed = parse_gmail_message(
        message(
            {
                "headers": headers(),
                "mimeType": "multipart/alternative",
                "parts": [
                    text_part("text/html", "<p>HTML version</p>"),
                    text_part("text/plain", "Plain text version"),
                ],
            }
        )
    )

    assert parsed.text == "Plain text version"


def test_parser_handles_nested_parts_and_ignores_attachments():
    parsed = parse_gmail_message(
        message(
            {
                "headers": headers(),
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [text_part("text/plain", "Nested message")],
                    },
                    text_part("text/plain", "Do not parse attachment", filename="notes.txt"),
                ],
            }
        )
    )

    assert parsed.text == "Nested message"


def test_parser_removes_quoted_history_and_normalizes_whitespace():
    body = "Latest update.\n\nOn Tuesday, Recruiter wrote:\nEarlier message."
    parsed = parse_gmail_message(message({"headers": headers(), **text_part("text/plain", body)}))

    assert parsed.text == "Latest update."


def test_parser_handles_invalid_body_and_applies_size_limit():
    malformed = message({"headers": headers(), "mimeType": "text/plain", "body": {"data": "%%%"}})
    assert parse_gmail_message(malformed).text == ""

    parsed = parse_gmail_message(
        message({"headers": headers(), **text_part("text/plain", "abcdefghij")}),
        max_chars=5,
    )
    assert parsed.text == "abcde"


def test_normalized_content_has_stable_hash():
    first = parse_gmail_message(message({"headers": headers(), **text_part("text/plain", "Hello   candidate\n\n")}))
    second = parse_gmail_message(message({"headers": headers(), **text_part("text/plain", "Hello candidate")}))

    assert first.text == second.text
    assert first.content_hash == second.content_hash


def test_parser_rejects_non_positive_text_limit():
    with pytest.raises(ValueError, match="max_chars"):
        parse_gmail_message(message({"headers": headers(), **text_part("text/plain", "Hello")}), max_chars=0)

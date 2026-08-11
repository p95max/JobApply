from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


CATALOGS = (
    Path("locale/de/LC_MESSAGES/django.po"),
    Path("apps/accounts/locale/de/LC_MESSAGES/django.po"),
)


def _message_ids(path: Path) -> list[str]:
    """Read uncontextualized gettext message IDs without a msgfmt dependency."""
    message_ids: list[str] = []
    current: str | None = None
    collecting = False

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            if current:
                message_ids.append(current)
            current = ast.literal_eval(line.removeprefix("msgid "))
            collecting = True
        elif collecting and line.startswith('"'):
            current = (current or "") + ast.literal_eval(line)
        elif collecting:
            if current:
                message_ids.append(current)
            current = None
            collecting = False

    if current:
        message_ids.append(current)
    return message_ids


def test_german_translation_catalogs_do_not_repeat_message_ids():
    for catalog in CATALOGS:
        counts = Counter(_message_ids(catalog))
        duplicates = sorted(msgid for msgid, count in counts.items() if count > 1)

        assert not duplicates, f"Duplicate msgid entries in {catalog}: {duplicates}"

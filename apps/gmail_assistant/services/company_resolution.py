from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from apps.gmail_assistant.services.application_matcher import normalize_company

_RULES_PATH = Path(__file__).with_name("company_resolution_rules.json")


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    """Load explicit, reviewable employer aliases for known ATS sender labels."""
    with _RULES_PATH.open(encoding="utf-8") as source:
        value = json.load(source)
    aliases = value.get("aliases") if isinstance(value, dict) else None
    if not isinstance(aliases, dict) or not all(
        isinstance(alias, str) and isinstance(company, str) and alias.strip() and company.strip()
        for alias, company in aliases.items()
    ):
        raise ValueError("company_resolution_rules.json must contain non-empty string aliases")
    return {normalize_company(alias): company.strip() for alias, company in aliases.items()}


def resolve_company(company: Any) -> Any:
    """Return a configured employer name without guessing from an ATS sender."""
    if not isinstance(company, str) or not company.strip():
        return company
    return _aliases().get(normalize_company(company), company.strip())


def resolve_extracted_company(extracted_data: dict[str, Any]) -> dict[str, Any]:
    """Copy extracted facts and canonicalise only explicitly configured aliases."""
    resolved = dict(extracted_data)
    if "company" in resolved:
        resolved["company"] = resolve_company(resolved["company"])
    return resolved

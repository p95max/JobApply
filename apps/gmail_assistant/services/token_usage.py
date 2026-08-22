from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.gmail_assistant.usage_models import OpenAITokenUsage


# Standard API prices in USD per 1M text tokens.
# Environment variables remain available as a fallback for unknown models.
_MODEL_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-5.4-nano": (Decimal("0.20"), Decimal("1.25")),
}


@dataclass(frozen=True)
class TokenUsageSummary:
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    by_day: tuple[dict[str, object], ...]
    by_model: tuple[dict[str, object], ...]
    available: bool = True
    error: str = ""


def _price(name: str) -> Decimal | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _model_prices(model_name: str) -> tuple[Decimal, Decimal] | None:
    normalized = (model_name or "").strip().lower()
    if normalized in _MODEL_PRICES:
        return _MODEL_PRICES[normalized]

    input_price = _price("OPENAI_INPUT_USD_PER_1M")
    output_price = _price("OPENAI_OUTPUT_USD_PER_1M")
    if input_price is None or output_price is None:
        return None
    return input_price, output_price


def estimate_model_cost(model_name: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Estimate API cost for persisted token usage using the shared model price table."""
    prices = _model_prices(model_name)
    if prices is None:
        return None
    input_price, output_price = prices
    million = Decimal(1_000_000)
    return ((Decimal(input_tokens) * input_price) + (Decimal(output_tokens) * output_price)) / million


def load_token_usage(*, user, days: int = 30) -> TokenUsageSummary:
    since = timezone.now() - timedelta(days=days)
    queryset = OpenAITokenUsage.objects.filter(user=user, created_at__gte=since)

    totals = queryset.aggregate(
        requests=Count("id"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    requests = totals["requests"] or 0
    input_total = totals["input_tokens"] or 0
    output_total = totals["output_tokens"] or 0

    raw_days = list(
        queryset.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            requests=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
        )
        .order_by("day")
    )
    maximum = max(
        (int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0) for row in raw_days),
        default=0,
    )
    day_rows = tuple(
        {
            "day": row["day"].isoformat(),
            "requests": row["requests"],
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "total_tokens": (row["input_tokens"] or 0) + (row["output_tokens"] or 0),
            "input_percent": round(((row["input_tokens"] or 0) / maximum) * 100, 2) if maximum else 0,
            "output_percent": round(((row["output_tokens"] or 0) / maximum) * 100, 2) if maximum else 0,
        }
        for row in raw_days
    )

    raw_models = list(
        queryset.values("model_name")
        .annotate(
            requests=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
        )
        .order_by("model_name")
    )
    model_rows = tuple(
        {
            "model": row["model_name"],
            "requests": row["requests"],
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "total_tokens": (row["input_tokens"] or 0) + (row["output_tokens"] or 0),
            "estimated_cost_usd": estimate_model_cost(
                row["model_name"],
                row["input_tokens"] or 0,
                row["output_tokens"] or 0,
            ),
        }
        for row in raw_models
    )

    model_costs = [row["estimated_cost_usd"] for row in model_rows]
    estimated_cost = None if any(cost is None for cost in model_costs) else sum(model_costs, Decimal("0"))

    return TokenUsageSummary(
        requests=requests,
        input_tokens=input_total,
        output_tokens=output_total,
        total_tokens=input_total + output_total,
        estimated_cost_usd=estimated_cost,
        by_day=day_rows,
        by_model=model_rows,
    )

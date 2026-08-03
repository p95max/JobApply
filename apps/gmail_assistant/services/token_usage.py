from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

_TOKEN_LINE = re.compile(
    r"OpenAI Gmail analysis completed .*?model=(?P<model>\S+) .*?"
    r"input_tokens=(?P<input>\d+) output_tokens=(?P<output>\d+)"
)
_TIMESTAMP = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+")


@dataclass(frozen=True)
class TokenUsageSummary:
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    by_day: tuple[dict[str, object], ...]
    by_model: tuple[dict[str, object], ...]
    available: bool
    error: str = ""


def _price(name: str) -> Decimal | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _estimate_cost(input_tokens: int, output_tokens: int) -> Decimal | None:
    input_price = _price("OPENAI_INPUT_USD_PER_1M")
    output_price = _price("OPENAI_OUTPUT_USD_PER_1M")
    if input_price is None or output_price is None:
        return None
    million = Decimal(1_000_000)
    return ((Decimal(input_tokens) * input_price) + (Decimal(output_tokens) * output_price)) / million


def load_token_usage(days: int = 30) -> TokenUsageSummary:
    command = [
        "journalctl",
        "--no-pager",
        "-o",
        "short-iso",
        "--since",
        f"{days} days ago",
        "-u",
        "jobapply-web.service",
        "-u",
        "jobapply-gmail-worker.service",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return TokenUsageSummary(0, 0, 0, 0, None, (), (), False, type(error).__name__)

    if result.returncode != 0:
        return TokenUsageSummary(0, 0, 0, 0, None, (), (), False, result.stderr.strip()[:200])

    input_total = 0
    output_total = 0
    requests = 0
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "input": 0, "output": 0})
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "input": 0, "output": 0})

    for line in result.stdout.splitlines():
        usage_match = _TOKEN_LINE.search(line)
        if not usage_match:
            continue
        input_tokens = int(usage_match.group("input"))
        output_tokens = int(usage_match.group("output"))
        model = usage_match.group("model")
        timestamp_match = _TIMESTAMP.match(line)
        day = "Unknown"
        if timestamp_match:
            try:
                day = datetime.fromisoformat(timestamp_match.group("timestamp").replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                pass

        requests += 1
        input_total += input_tokens
        output_total += output_tokens
        by_day[day]["requests"] += 1
        by_day[day]["input"] += input_tokens
        by_day[day]["output"] += output_tokens
        by_model[model]["requests"] += 1
        by_model[model]["input"] += input_tokens
        by_model[model]["output"] += output_tokens

    day_rows = tuple(
        {
            "day": day,
            "requests": values["requests"],
            "input_tokens": values["input"],
            "output_tokens": values["output"],
            "total_tokens": values["input"] + values["output"],
        }
        for day, values in sorted(by_day.items(), reverse=True)
    )
    model_rows = tuple(
        {
            "model": model,
            "requests": values["requests"],
            "input_tokens": values["input"],
            "output_tokens": values["output"],
            "total_tokens": values["input"] + values["output"],
        }
        for model, values in sorted(by_model.items())
    )
    return TokenUsageSummary(
        requests=requests,
        input_tokens=input_total,
        output_tokens=output_total,
        total_tokens=input_total + output_total,
        estimated_cost_usd=_estimate_cost(input_total, output_total),
        by_day=day_rows,
        by_model=model_rows,
        available=True,
    )

#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

NUMERIC_FIELDS = [
    "success_rate",
    "hits_at_budget_mean",
    "auc_found_targets_mean",
    "time_to_first_hit_mean",
    "miss_recovery_rate",
]


def aggregate_result_summaries(paths: Iterable[Path]) -> dict[str, dict[str, float | None]]:
    buckets: dict[str, dict[str, list[float]]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload.get("summary", {})
        for method, metrics in summary.items():
            bucket = buckets.setdefault(method, {field: [] for field in NUMERIC_FIELDS})
            for field in NUMERIC_FIELDS:
                value = metrics.get(field)
                if value is not None:
                    bucket[field].append(float(value))

    aggregated: dict[str, dict[str, float | None]] = {}
    for method, metrics in buckets.items():
        aggregated[method] = {}
        for field, values in metrics.items():
            aggregated[method][field] = (sum(values) / len(values)) if values else None
    return aggregated


def _fmt(value: float | None) -> str:
    return "None" if value is None else f"{value:.3f}"


def build_experiment_log_block(
    *,
    iteration: int,
    title: str,
    hypothesis: str,
    patch_summary: str,
    smoke_result: str,
    full_run_result: str,
    primary_metric_delta: str,
    guardrail_status: str,
    keep_or_revert: str,
    why: str,
    next_best_step: str,
    aggregate_summary: dict[str, dict[str, float | None]],
) -> str:
    summary_lines = []
    for method, metrics in aggregate_summary.items():
        parts = [
            f"success={_fmt(metrics.get('success_rate'))}",
            f"hits={_fmt(metrics.get('hits_at_budget_mean'))}",
            f"auc={_fmt(metrics.get('auc_found_targets_mean'))}",
            f"t_first={_fmt(metrics.get('time_to_first_hit_mean'))}",
        ]
        summary_lines.append(f"  - {method}: " + ", ".join(parts))
    summary_text = "\n".join(summary_lines) if summary_lines else "  - no aggregated summary"

    return (
        f"### ITERATION {iteration} — {title}\n"
        f"- Hypothesis:\n  - {hypothesis}\n"
        f"- Patch summary:\n  - {patch_summary}\n"
        f"- Smoke result:\n  - {smoke_result}\n"
        f"- Full run result:\n  - {full_run_result}\n"
        f"- Aggregate summary:\n{summary_text}\n"
        f"- Primary metric delta:\n  - {primary_metric_delta}\n"
        f"- Guardrail status:\n  - {guardrail_status}\n"
        f"- Keep or revert:\n  - {keep_or_revert}\n"
        f"- Why:\n  - {why}\n"
        f"- Next best step:\n  - {next_best_step}\n"
    )


def append_jsonl(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def append_md(path: Path, block: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(block.rstrip() + "\n\n")

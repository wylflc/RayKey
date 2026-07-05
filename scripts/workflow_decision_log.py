#!/usr/bin/env python3
"""Append auditable workflow decision records."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
WORKFLOW_VERSION = "a-share-selection-operation-v13"

DECISION_LOG_FIELDS = [
    "logged_at_utc",
    "workflow_stage",
    "run_id",
    "as_of",
    "security_code",
    "security_name",
    "decision_type",
    "decision_result",
    "summary_reason",
    "input_files",
    "source_urls",
    "output_file",
    "operator_or_script",
    "workflow_version",
]


def append_decision_log(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DECISION_LOG_FIELDS})

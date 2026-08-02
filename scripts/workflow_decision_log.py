#!/usr/bin/env python3
"""Append auditable workflow decision records."""

from __future__ import annotations

import csv
import re
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
WORKFLOW_SPEC = ROOT / "docs/000_Ashare_workflow.md"


def _read_workflow_version() -> str:
    """Single-source the version from the spec's own title line.

    Hard-coding it here let the constant drift 19 versions behind the changelog
    (stuck at v1.43 while the spec was at v1.62), and every decision-log row
    written in between carries the wrong version. The title line is the one
    place a reader looks, so it is the truth; this parses it (§15.2 第 3 条).
    """
    try:
        head = WORKFLOW_SPEC.read_text(encoding="utf-8").split("\n", 1)[0]
    except OSError:
        return "a-share-selection-operation-unknown"
    match = re.search(r"v(\d+\.\d+)", head)
    return f"a-share-selection-operation-v{match.group(1)}" if match else (
        "a-share-selection-operation-unknown"
    )


WORKFLOW_VERSION = _read_workflow_version()

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
    "decision_id",
    "supersedes_decision_id",
]


def make_decision_id(row: dict[str, object]) -> str:
    """`stage:as_of:code:short-uuid` — unique and human-scannable (§2.1)."""
    stage = str(row.get("workflow_stage", "") or "stage")
    as_of = str(row.get("as_of", "") or "na")
    code = str(row.get("security_code", "") or "na")
    return f"{stage}:{as_of}:{code}:{uuid.uuid4().hex[:8]}"


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
            record = {field: row.get(field, "") for field in DECISION_LOG_FIELDS}
            if not record["decision_id"]:
                record["decision_id"] = make_decision_id(row)
            writer.writerow(record)

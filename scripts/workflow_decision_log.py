#!/usr/bin/env python3
"""Append auditable workflow decision records."""

from __future__ import annotations

import csv
import re
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
WORKFLOW_SPEC = ROOT / "docs/000_Ashare_workflow.md"
WORKFLOW_CHANGELOG = ROOT / "docs/Ashare_workflow_changelog.md"


def _read_workflow_version() -> str:
    """Single-source the version from the spec's own title line.

    Hard-coding it here let the constant drift 19 versions behind the changelog
    (stuck at v1.43 while the spec was at v1.62), and every decision-log row
    written in between carries the wrong version. The title line is the one
    place a reader looks, so it is the truth; this parses it (§13 第 3 条).
    """
    try:
        head = WORKFLOW_SPEC.read_text(encoding="utf-8").split("\n", 1)[0]
    except OSError:
        return "a-share-selection-operation-unknown"
    match = re.search(r"v(\d+\.\d+)", head)
    return f"a-share-selection-operation-v{match.group(1)}" if match else (
        "a-share-selection-operation-unknown"
    )


def _read_changelog_version() -> str | None:
    """changelog 表格首个数据行的版本号 = 最近一次已记录的修订。"""
    try:
        text = WORKFLOW_CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\|\s*\*{0,2}v(\d+\.\d+)\*{0,2}\s*\|", text, re.MULTILINE)
    return match.group(1) if match else None


def version_sync_warning() -> str | None:
    """正文版本行落后/领先 changelog 时返回告警文本，同步时返回 None（结 OI-032 成因）。

    OI-032 的形态：2026-08-06 的 v2.15 只改了 changelog 与小节标题，**正文第 1 行没改**，
    于是 08-06/08-07 两日全部决策日志行的 `workflow_version` 都被记成 v2.14——溯源时会把
    v2.15 的结论归到 v2.14 名下。缺陷本身当日已修，但**成因没消除**：没有任何检查确保
    「改了 changelog 就必须改正文版本行」。本函数就是那个检查。

    放在导入期而非 `__main__`：写决策日志的每个脚本都导入本模块，这样它在**每日跑批时**
    可见（§13 第 2 条要求新规则附跑批时可见的落地校验），而不是只在有人专门跑自检时。
    同步时一字不印，避免每日噪音。
    """
    spec = WORKFLOW_VERSION.rsplit("-v", 1)[-1] if "-v" in WORKFLOW_VERSION else ""
    changelog = _read_changelog_version()
    if not spec or not changelog or spec == changelog:
        return None
    return (
        f"**版本号不同步（OI-032）**：正文第 1 行 v{spec}，而 changelog 首行 v{changelog}。"
        f"本次跑批写入决策日志的 workflow_version 将是 v{spec}——"
        f"若 changelog 才是新版，先改 docs/000_Ashare_workflow.md 第 1 行再重跑，否则本批日志溯源会归错版本。"
    )


WORKFLOW_VERSION = _read_workflow_version()

_VERSION_WARNING = version_sync_warning()
if _VERSION_WARNING:
    print(f"[workflow_decision_log] {_VERSION_WARNING}", file=sys.stderr)

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


# --- 改判链自检（§2.1，v2.08） ---------------------------------------------
#
# 日志是 append-only 审计流，**同一业务键出现多行本身不是缺陷**：§9.1 明确支持同一
# 交易日盘中一次、收盘一次，池物化每跑一次就为每家写一行。分辨"正常重跑"和"改判没
# 留痕"的，是 `supersedes_decision_id` ——它才是把后一行接到前一行上的那根线。
#
# 实测 2026-08-03：31,004 行里只有 87 行填了 supersedes，即这根线基本没接过。后果不是
# 行数多，而是**给定一个业务键，无法判定哪一行是当前结论**。本函数把这件事变成可见的
# 数字（§13 第 2 条：新规则须同时给出跑批时可见的命中数）。

BUSINESS_KEY_FIELDS = ("as_of", "workflow_stage", "security_code", "decision_type")


def business_key(row: dict) -> tuple:
    """一条结论的业务身份。同键多行 = 同一天对同一标的同一问题的多次结论。"""
    return tuple(str(row.get(field, "") or "") for field in BUSINESS_KEY_FIELDS)


def audit_supersedes(path: Path) -> dict[str, object]:
    """统计同业务键多行中有多少接上了改判链。供跑批与人工核对调用。"""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    by_key: dict[tuple, list[dict]] = {}
    for row in rows:
        by_key.setdefault(business_key(row), []).append(row)

    repeated = {key: group for key, group in by_key.items() if len(group) > 1}
    linked = sum(
        1 for group in repeated.values()
        for row in group[1:] if str(row.get("supersedes_decision_id", "") or "").strip()
    )
    followups = sum(len(group) - 1 for group in repeated.values())
    return {
        "rows": len(rows),
        "business_keys": len(by_key),
        "repeated_keys": len(repeated),
        "followup_rows": followups,
        "linked_followups": linked,
        "unlinked_followups": followups - linked,
        "blank_decision_id": sum(1 for r in rows if not str(r.get("decision_id", "") or "").strip()),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("用法：workflow_decision_log.py [决策日志CSV]\n"
              "无参数时自检缺省日志（版本同步 + supersedes 链完整性）；"
              "作为库导入时提供 append 接口。")
        sys.exit(0)
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DECISION_LOG
    stats = audit_supersedes(target)
    print(f"版本同步自检（OI-032）：正文 {WORKFLOW_VERSION}"
          + (f"｜**{_VERSION_WARNING}**" if _VERSION_WARNING else "｜与 changelog 首行一致"))
    print(f"决策日志自检 {target.name}（§2.1）")
    print(f"  总行数 {stats['rows']}｜业务键 {stats['business_keys']}｜同键多行的键 {stats['repeated_keys']}")
    print(f"  后续行 {stats['followup_rows']} 行，其中已接改判链 {stats['linked_followups']} 行，"
          f"**未接 {stats['unlinked_followups']} 行**")
    print(f"  decision_id 为空 {stats['blank_decision_id']} 行（§2.1：旧行可为空，新行由脚本自动生成）")

#!/usr/bin/env python3
"""Offline checks for active instructions, document links and displayed quality state."""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = [
    "AGENTS.md", "CLAUDE.md", "README.md", "docs/000_Ashare_workflow.md",
    "docs/000_personal-investment-system-v1.zh.md", "docs/Ashare_quality_rubric.md",
]


def read_rows(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


# OI-194：工作流程点名的脚本所读写的 data/processed 产物必须在工作流程出现（按文件名或目录名匹配）。
# 研究专用输入不在工作流程定义，落点在回测日志与报告：美股移植（OI-159）与宇宙对照臂 U6A。
RESEARCH_ONLY_PRODUCTS = re.compile(r"^(us_|pit_attention/panel_sp\d+_us\.csv$|pit_attention/panel_moat_bank_v6a\.csv$)")


def audit_processed_products(workflow: str) -> list[str]:
    errors: list[str] = []
    named = set(re.findall(r"scripts/([A-Za-z0-9_]+\.py)", workflow)) | set(re.findall(r"`([A-Za-z0-9_]+\.py)`", workflow))
    for script in sorted(named):
        path = ROOT / "scripts" / script
        if not path.is_file():
            continue
        for rel in sorted(set(re.findall(r"data/processed/([A-Za-z0-9_./-]+)", path.read_text(encoding="utf-8", errors="ignore")))):
            if "{" in rel or "<" in rel or RESEARCH_ONLY_PRODUCTS.match(rel):
                continue
            parts = rel.rstrip("/").split("/")
            if parts[-1] in workflow or (len(parts) > 1 and f"data/processed/{parts[0]}/" in workflow):
                continue
            errors.append(f"product not defined in workflow: data/processed/{rel} (used by scripts/{script})")
    return errors


def audit() -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    texts = {name: (ROOT / name).read_text() for name in ACTIVE}
    for name, text in texts.items():
        for token in ("CONTEXT.md", "docs/adr/", "a-share-quality-tiering", "grill-with-doc"):
            if token in text:
                errors.append(f"{name}: obsolete instruction reference {token}")
    for name in ACTIVE[3:5]:
        body = texts[name].split("\n", 1)[1]
        for pattern in (r"v\d+\.\d+", r"^## .*修订记录", r"旧口径|此前|已退役|已删除|已失效",
                        r"在册读数（|全池 \d+ 家结果|流动性门槛|成本价不能决定任何持仓动作"):
            if re.search(pattern, body, re.MULTILINE):
                errors.append(f"{name}: history or obsolete rule in execution body: {pattern}")
    rubric = texts["docs/Ashare_quality_rubric.md"]
    for phrase in ("三态矩阵", "anchor_override", "直接判 L3", "建仓档位", "Q2 ≥ 82"):
        if phrase in rubric:
            errors.append(f"score rubric duplicates or contradicts workflow: {phrase}")

    workflow = texts["docs/000_Ashare_workflow.md"]
    headings = set(re.findall(r"^#{2,6} (\d+(?:\.\d+)*)[ .]", workflow, re.MULTILINE))
    for ref in re.findall(r"§(\d+(?:\.\d+)+)", workflow):
        if ref not in headings:
            errors.append(f"workflow has missing section §{ref}")
    for target in set(re.findall(r"scripts/[A-Za-z0-9_./-]+\.(?:py|sbatch)", workflow)):
        if not (ROOT / target).is_file():
            errors.append(f"workflow script missing: {target}")
    errors.extend(audit_processed_products(workflow))
    for name, text in texts.items():
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if target and not ((ROOT / name).parent / target).exists():
                errors.append(f"{name}: broken link {target}")

    triage = {r["security_code"]: r for r in read_rows("data/processed/a_share_attention_triage.csv")}
    tiers = {r["security_code"]: r for r in read_rows("data/processed/a_share_watchlist_quality_tiers.csv")}
    for code, row in tiers.items():
        state = triage.get(code, {}).get("attention_class")
        tier = row.get("quality_tier", "")
        valid = ((state == "worth_attention" and tier in ("L1", "L2", "L3"))
                 or (state == "documented_not_attention" and tier == "L4"))
        if not valid:
            errors.append(f"A-share {code}: class {state} conflicts with tier {tier}")
    overseas = read_rows("data/processed/overseas_watchlist_valuation.csv")
    for row in overseas:
        code, state, tier = row["security_code"], row.get("attention_class"), row.get("quality_tier")
        if state in ("boundary_pending", "garbage"):
            if tier or row.get("quality_score"):
                errors.append(f"overseas {code}: unclassified company has score/tier")
        elif not ((state == "worth_attention" and tier in ("L1", "L2", "L3"))
                  or (state == "documented_not_attention" and tier == "L4")):
            errors.append(f"overseas {code}: invalid class/tier {state}/{tier}")
        if row.get("buy_eligibility") != "off_pipeline_watch_only":
            errors.append(f"overseas {code}: unexpected execution eligibility")
    index = read_rows("data/processed/a_share_company_analysis_index.csv")
    for row in index:
        code = row["security_code"]
        if row.get("round1_attention_class", "") != triage.get(code, {}).get("attention_class", ""):
            errors.append(f"company index {code}: stale attention state")
        if row.get("prior_quality_tier", "") != tiers.get(code, {}).get("quality_tier", ""):
            errors.append(f"company index {code}: stale quality tier")
    if (ROOT / "data/processed/manual_band_overrides.csv").exists():
        errors.append("retired manual valuation table is present")
    for name in ("apply_forecast_band_overlay.py", "apply_model_bands_to_dossiers.py"):
        source = (ROOT / "scripts" / name).read_text()
        if any(token in source for token in ("manual_band_overrides.csv", '"--overrides"', "def load_overrides")):
            errors.append(f"{name}: retired manual valuation input is active")
    pool_text = (ROOT / "docs/000_a_share_core_valuation_pool.md").read_text()
    if "## L4｜" in pool_text or re.search(r"\| L4 \| (?:boundary_pending|garbage) \|", pool_text):
        errors.append("pool reading version uses L4 as an archive category")
    calibration = list((ROOT / "docs/peer-group-calibration").glob("*.md"))
    for path in calibration:
        if path.name != "README.md" and "历史行业校准记录：" not in path.read_text()[:250]:
            errors.append(f"unmarked historical calibration: {path.name}")
    from workflow_decision_log import version_sync_warning
    warning = version_sync_warning()
    if warning:
        errors.append(warning)
    return sorted(set(errors)), {"active_docs": len(texts), "a_share_tiers": len(tiers),
                                "overseas_rows": len(overseas), "index_rows": len(index),
                                "calibration_notes": len(calibration) - 1}


def main() -> int:
    errors, counts = audit()
    print("Documentation audit:", ", ".join(f"{key}={value}" for key, value in counts.items()))
    for error in errors:
        print("ERROR:", error)
    print(f"{len(errors)} error(s)")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())

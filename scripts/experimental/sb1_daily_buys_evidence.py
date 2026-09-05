#!/usr/bin/env python3
"""归档本轮小体积指标、成交上限与贡献证据，不删除任何回测产物。"""
from __future__ import annotations

import collections
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import clean_derived_artifacts as archive
import sweep_backtest_configs as sweep
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION
from dose_table import load
from sb1_daily_buys import EXP


def main():
    assert (EXP / "union_sets.json").exists(), "finish sensitivity job first"
    full, ex, _ = load(EXP / "sweep.txt")
    old_full, old_ex, _ = load(ROOT / "data/experiments/exp_swap_variants/sweep_newbase_sb1_rel.txt")
    for before, after in (("V4134", "BASE"), ("BASE", "SB1")):
        assert old_full[before] == full[after]
        assert old_ex[before] == ex[after]
    metrics = []
    for scope, path in (("原快照", EXP / "sweep.txt"), ("截至2026-08-07", EXP / "sweep_cutoff.txt")):
        a, e, labels = load(path)
        for population, group in (("全样本", a), ("剔除A", e)):
            for label in labels:
                if label == "SUBSET_CHECK":
                    continue
                assert set(group[label]) == set(sweep.DEFAULT_STARTS)
                for ref in ("BASE", "SB1"):
                    for key in sweep.FIELDS:
                        delta = [group[label][s][key] - group[ref][s][key] for s in sweep.DEFAULT_STARTS]
                        metrics.append(dict(snapshot=scope, sample=population, arm=label, reference=ref,
                                            metric=key, level=statistics.median(r[key] for r in group[label].values()),
                                            paired_delta=statistics.median(delta), positive=sum(x > 0 for x in delta), n=len(delta)))
    with (EXP / "paired_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)

    counts = {}
    artifacts = EXP / "artifacts"
    base_trades = next(artifacts.glob("*_daily_BASE_trades.csv"))
    for path in sorted(EXP.glob("trades_*.csv")):
        label = path.stem.removeprefix("trades_")
        with path.open(encoding="utf-8-sig") as fh:
            days = collections.Counter(r["date"] for r in csv.DictReader(fh) if r["action"] == "买入")
        if "BUY" in label:
            assert max(days.values(), default=0) <= int(label[-1])
        counts[label] = dict(buys=sum(days.values()), buying_days=len(days),
                             max_buys_per_day=max(days.values(), default=0),
                             days_by_buy_count=dict(sorted(collections.Counter(days.values()).items())))
        if label != "BASE":
            with (EXP / f"attribution_{label}.txt").open("w", encoding="utf-8") as out:
                subprocess.run([sys.executable, str(ROOT / "scripts/experimental/delta_attribution.py"),
                                "--base", str(base_trades), "--arm", str(next(artifacts.glob(f"*_daily_{label}_trades.csv")))],
                               stdout=out, check=True)
    (EXP / "buy_count_audit.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 唯一前缀避免覆盖其它纪元的 BASE/同名实验；调用现有归并函数保留既有台账。
    entries = [SimpleNamespace(name="summary_SB1DB20260905_" + p.name.removeprefix("summary_"), path=str(p))
               for p in (EXP / "summaries").glob("summary_*.csv")]
    assert len(entries) == 420
    rows, columns = archive.merge_summaries(entries)
    with archive.MERGED.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    stamp = "sb1_daily_buys_20260905"
    with DEFAULT_DECISION_LOG.open(encoding="utf-8-sig") as fh:
        recorded = any(r.get("run_id") == stamp for r in csv.DictReader(fh))
    if not recorded:
        append_decision_log(DEFAULT_DECISION_LOG, [{
            "logged_at_utc": datetime.now(timezone.utc).isoformat(), "workflow_stage": "backtest",
            "run_id": stamp, "as_of": "2026-09-05", "decision_type": "strategy_experiment",
            "decision_result": "research_complete_no_production_change",
            "summary_reason": "SB1 与每日买入笔数复核完成；两表14起点、统一截止日与赢家并集证据见报告，生产参数未改。",
            "input_files": "data/experiments/exp_sb1_daily_buys/manifest.json",
            "output_file": "docs/reports/sb1_daily_buy_review.zh.md",
            "operator_or_script": "scripts/experimental/sb1_daily_buys_evidence.py", "workflow_version": WORKFLOW_VERSION,
        }])
    print(f"历史复现 56/56，成交核验 {len(counts)} 臂；归档主扫描 {len(entries)} 行；指标 {len(metrics)} 行。")


if __name__ == "__main__":
    main()

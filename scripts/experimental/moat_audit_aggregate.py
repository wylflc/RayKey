#!/usr/bin/env python3
"""汇总关注池护城河审核各批 JSONL（2026-09-07）：校验字段 → 合并表 → 阅读版报告 → 决策日志行。

用法：python3 scripts/experimental/moat_audit_aggregate.py [--write-log]
不带 --write-log 只出合并表与报告；带它才向 `a_share_workflow_decision_log.csv` 追加逐票审核行（只追加）。
名单迁移（attention_class 改动）不在本脚本内，须用户裁定后另行执行。
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data/interim/moat_audit_2026-09-07"
REPORT = ROOT / "docs/reports/moat_audit_2026-09-07.zh.md"
MERGED = DIR / "moat_audit_merged.csv"
LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
VERDICTS = ("维持", "降 boundary_pending", "待外部取证")
REQUIRED = ("security_code", "security_name", "quality_tier", "carrier", "carrier_fact", "replication_test",
            "quant_support", "quant_note", "peer_anchor", "erosion", "erosion_path", "verdict", "confidence",
            "reason", "sources", "evidence_status")


def load() -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    expected = {}
    for p in sorted(DIR.glob("batch_*_input.json")):
        for item in json.load(p.open(encoding="utf-8")):
            expected[item["security_code"]] = item["security_name"]
    seen = set()
    for p in sorted(DIR.glob("batch_*.jsonl")):
        for n, line in enumerate(p.open(encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"{p.name}:{n} JSON 解析失败 {e}")
                continue
            missing = [k for k in REQUIRED if k not in r]
            if missing:
                problems.append(f"{p.name}:{n} {r.get('security_code')} 缺字段 {missing}")
            if r.get("verdict") not in VERDICTS:
                problems.append(f"{p.name}:{n} {r.get('security_code')} verdict 非法：{r.get('verdict')!r}")
            if len(str(r.get("reason", ""))) > 160:
                problems.append(f"{p.name}:{n} {r.get('security_code')} reason 超长 {len(r['reason'])}")
            code = r.get("security_code")
            if code in seen:
                problems.append(f"{p.name}:{n} {code} 重复")
            if code not in expected:
                problems.append(f"{p.name}:{n} {code} 不在关注池输入")
            seen.add(code)
            r["_batch"] = p.name
            rows.append(r)
    for code, name in expected.items():
        if code not in seen:
            problems.append(f"缺审核结果：{code} {name}")
    return rows, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-log", action="store_true")
    args = ap.parse_args()
    rows, problems = load()
    for p in problems:
        print("⚠", p, file=sys.stderr)
    tiers = {r["security_code"]: r for r in csv.DictReader((ROOT / "data/processed/a_share_watchlist_quality_tiers.csv").open(encoding="utf-8"))}
    quant = {r["security_code"]: r for r in csv.DictReader((DIR / "quant_evidence.csv").open(encoding="utf-8"))}
    order = {v: i for i, v in enumerate(VERDICTS)}
    rows.sort(key=lambda r: (order.get(r.get("verdict"), 9), r.get("quality_tier", ""), r["security_code"]))
    cols = list(REQUIRED) + ["industry", "roe_median", "roe_pctl_median", "roe_years_ge15", "_batch"]
    with MERGED.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            q = quant.get(r["security_code"], {})
            out = dict(r)
            out["carrier"] = "＋".join(r["carrier"]) if isinstance(r.get("carrier"), list) else r.get("carrier", "")
            out["sources"] = " ; ".join(r["sources"]) if isinstance(r.get("sources"), list) else r.get("sources", "")
            out.update({"industry": q.get("industry", ""), "roe_median": q.get("roe_median", ""),
                        "roe_pctl_median": q.get("roe_pctl_median", ""), "roe_years_ge15": q.get("roe_years_ge15", "")})
            w.writerow(out)
    by_v = Counter(r["verdict"] for r in rows)
    by_tier = Counter((r["quality_tier"], r["verdict"]) for r in rows)
    by_ev = Counter(r.get("evidence_status", "") for r in rows)
    by_rep = Counter(r.get("replication_test", "") for r in rows)

    def cell(s: object, n: int = 0) -> str:
        s = str(s if s is not None else "").replace("|", "／").replace("\n", " ")
        return s if not n or len(s) <= n else s[: n - 1] + "…"

    lines = [
        "# 关注池护城河逐家审核（2026-09-07）",
        "",
        f"审核对象：`worth_attention` 全部 {len(rows)} 家（分层表 {sum(1 for t in tiers.values() if t['attention_class']=='worth_attention')} 家）。"
        "标准照工作流 §5.4 资本复制测试与行业特殊口径，协议与逐家原始判语在 `data/interim/moat_audit_2026-09-07/`（`PROTOCOL.md`、`batch_*.jsonl`、`moat_audit_merged.csv`）。",
        "量化证据：FY2015-2025 年报加权 ROE 中位／最低／≥15% 年数、证监会门类内 ROE 分位中位（粗尺）、毛利率首末五年、归母 CAGR、经营现金流÷净利（`quant_evidence.csv`，脚本只连接数据不判定）。",
        "",
        "本报告只给审核结论与建议；`attention_class` 迁移须用户裁定后按 §5.5 执行并写决策日志。",
        "",
    ] + ((DIR / "summary_head.md").read_text(encoding="utf-8").rstrip("\n").split("\n") + [""] if (DIR / "summary_head.md").exists() else []) + [
        "## 1. 结果汇总",
        "",
        "| 判定 | 家数 |", "| --- | ---: |",
    ] + [f"| {v} | {by_v.get(v, 0)} |" for v in VERDICTS] + [
        "",
        "| 层级 | 维持 | 降 boundary_pending | 待外部取证 |", "| --- | ---: | ---: | ---: |",
    ] + [f"| {t} | {by_tier.get((t, VERDICTS[0]), 0)} | {by_tier.get((t, VERDICTS[1]), 0)} | {by_tier.get((t, VERDICTS[2]), 0)} |" for t in ("L1", "L2", "L3")] + [
        "",
        "证据强度：" + "、".join(f"{k or '未填'} {v}" for k, v in by_ev.most_common()) + "。资本复制测试：" + "、".join(f"{k} {v}" for k, v in by_rep.most_common()) + "。",
        "",
        "## 2. 建议移出关注池（降 boundary_pending）",
        "",
        "| 代码 | 名称 | 层级 | 载体 | 复制测试 | ROE 中位 / 门类分位 | 理由 | 证据 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if r["verdict"] != VERDICTS[1]:
            continue
        q = quant.get(r["security_code"], {})
        car = "＋".join(r["carrier"]) if isinstance(r.get("carrier"), list) else r.get("carrier", "")
        lines.append(f"| {r['security_code']} | {r['security_name']} | {r['quality_tier']} | {cell(car, 30)} | {r['replication_test']} | "
                     f"{q.get('roe_median','')} / {q.get('roe_pctl_median','')} | {cell(r['reason'])} | {r.get('evidence_status','')} |")
    lines += ["", "## 3. 待外部取证（判定悬于未核实事实）", "",
              "| 代码 | 名称 | 层级 | 悬而未决的事实 | 证据 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["verdict"] == VERDICTS[2]:
            lines.append(f"| {r['security_code']} | {r['security_name']} | {r['quality_tier']} | {cell(r['reason'])} | {r.get('evidence_status','')} |")
    lines += ["", "## 4. 维持关注池（全部）", "",
              "| 代码 | 名称 | 层级 | 载体 | ROE 中位 / 门类分位 / ≥15% 年数 | 侵蚀 | 可指事实 | 置信 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["verdict"] != VERDICTS[0]:
            continue
        q = quant.get(r["security_code"], {})
        car = "＋".join(r["carrier"]) if isinstance(r.get("carrier"), list) else r.get("carrier", "")
        lines.append(f"| {r['security_code']} | {r['security_name']} | {r['quality_tier']} | {cell(car, 30)} | "
                     f"{q.get('roe_median','')} / {q.get('roe_pctl_median','')} / {q.get('roe_years_ge15','')} | {r.get('erosion','')} | {cell(r['carrier_fact'], 110)} | {r.get('confidence','')} |")
    if problems:
        lines += ["", "## 附：校验告警", ""] + [f"- {p}" for p in problems]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"合并 {len(rows)} 行 → {MERGED.relative_to(ROOT)}；报告 → {REPORT.relative_to(ROOT)}；告警 {len(problems)}", file=sys.stderr)
    print("判定：", dict(by_v), file=sys.stderr)

    if args.write_log and not problems:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        version = (ROOT / "docs/000_Ashare_workflow.md").read_text(encoding="utf-8").splitlines()[0].split()[-1]
        with LOG.open("a", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            for r in rows:
                src = " ; ".join(r["sources"]) if isinstance(r.get("sources"), list) else str(r.get("sources", ""))
                did = "moat_audit:2026-09-07:" + r["security_code"] + ":" + hashlib.sha1((r["security_code"] + r["reason"]).encode()).hexdigest()[:6]
                w.writerow([now, "quality_review", "moat_audit:2026-09-07", "2026-09-07", r["security_code"], r["security_name"],
                            "moat_audit", r["verdict"], f"载体 {('＋'.join(r['carrier']) if isinstance(r.get('carrier'), list) else r.get('carrier',''))}；复制测试 {r['replication_test']}；{r['reason']}",
                            f"data/interim/moat_audit_2026-09-07/{r['_batch']};data/interim/moat_audit_2026-09-07/quant_evidence.csv",
                            src[:500], str(REPORT.relative_to(ROOT)), "scripts/experimental/moat_audit_aggregate.py",
                            f"a-share-selection-operation-{version}", did, ""])
        print(f"决策日志追加 {len(rows)} 行", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

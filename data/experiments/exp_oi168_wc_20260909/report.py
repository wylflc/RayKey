"""Report accounting/input differences and paired OI-168 backtest effects."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import statistics as st
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import sweep_backtest_configs as sw
from ex_winner_symmetry_report import CLAUSE4


def write_csv(name, rows):
    with (EXP / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def save(name, data):
    (EXP / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def num(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def valuation_report():
    with (ROOT / "data/processed/a_share_pool_model_bands_adopted.csv").open() as f:
        core = {r["security_code"] for r in csv.DictReader(f)}
    bands = {}
    for tag in ("BASE", "WCREP", "WCOP"):
        with (EXP / "val" / tag / "roic_bands_base.csv").open() as f:
            bands[tag] = {(r["security_code"], r["report_date"]): r for r in csv.DictReader(f)}
    assert set(bands["BASE"]) == set(bands["WCREP"]) == set(bands["WCOP"])
    invariants = Counter(); violations = []
    for key, b in bands["BASE"].items():
        for tag in ("WCREP", "WCOP"):
            r = bands[tag][key]
            if b["status"] == r["status"] == "ok":
                for field in ("nopat_ps", "roic0", "incremental_roic", "wacc", "fin_net_debt_ps"):
                    invariants[tag + ":" + field] += 1
                    if r[field] != b[field]:
                        violations.append({"arm": tag, "code": key[0], "period": key[1], "field": field,
                                           "base": b[field], "arm_value": r[field]})
    latest = {}
    for code, period in bands["BASE"]:
        if code in core and (code not in latest or period > latest[code]):
            latest[code] = period
    rows = []; counts = {tag: Counter() for tag in ("WCREP", "WCOP")}
    for code, period in sorted(latest.items()):
        key = (code, period); b = bands["BASE"][key]
        out = {"security_code": code, "security_name": b["security_name"], "report_date": period,
               "available_at": b["available_at"], "base_path": b["roic_path"]}
        for tag in ("BASE", "WCREP", "WCOP"):
            r = bands[tag][key]
            for field in ("status", "intrinsic_value", "reinvestment_rate", "g0", "roic_g_source",
                          "wc_first_period", "wc_last_period", "wc_start", "wc_end", "wc_change",
                          "wc_financing_start", "wc_financing_end", "wc_conflict_years"):
                out[tag + ":" + field] = r[field]
            if tag != "BASE" and b["status"] == "ok":
                count = counts[tag]; count["base_latest_ok"] += 1
                if r["status"] != "ok":
                    count["new_rejected"] += 1
                else:
                    change = float(r["intrinsic_value"]) / float(b["intrinsic_value"]) - 1
                    count["lower" if change < -.00001 else "higher" if change > .00001 else "same"] += 1
                    count["rr_changed"] += r["reinvestment_rate"] != b["reinvestment_rate"]
                    count["growth_changed"] += r["g0"] != b["g0"]
        for before, after in (("BASE", "WCREP"), ("BASE", "WCOP"), ("WCREP", "WCOP")):
            v0, v1 = num(out[before + ":intrinsic_value"]), num(out[after + ":intrinsic_value"])
            out[f"{after}_vs_{before}"] = v1/v0-1 if v0 and v1 and out[before+":status"] == out[after+":status"] == "ok" else None
        rows.append(out)
    write_csv("current_valuation_changes.csv", rows)
    save("valuation_verification.json", {"counts": counts, "invariants_checked": invariants,
                                          "invariant_violations": violations, "band_rows_per_arm": len(bands["BASE"])})
    assert not violations, "Unexpected change outside the working-capital/growth path"
    print(json.dumps(counts, ensure_ascii=False))


def backtest_report():
    groups = defaultdict(lambda: defaultdict(dict))
    with (EXP / "summary_rows.csv").open() as f:
        for row in csv.DictReader(f):
            groups[row["group"]][row["arm"]][row["start"]] = row
    paired = []; index = {}; comparisons = []
    for group, arms in groups.items():
        base = arms["BASE"]
        for arm, paths in arms.items():
            assert set(paths) == set(base) == set(sw.DEFAULT_STARTS)
            for metric in sw.FIELDS:
                values = [sw._field_value(paths[s], metric) for s in sw.DEFAULT_STARTS]
                changes = [sw._field_value(paths[s], metric) - sw._field_value(base[s], metric) for s in sw.DEFAULT_STARTS]
                r = {"group": group, "arm": arm, "metric": metric, "level_median": st.median(values),
                     "paired_delta_median": st.median(changes), "positive_starts": sum(d > 0 for d in changes)}
                paired.append(r); index[(group, arm, metric)] = r
                if group in {"full", "A"} and arm.startswith("WCOP"):
                    d = [sw._field_value(paths[s], metric)-sw._field_value(arms["WCREPSEP09"][s], metric) for s in sw.DEFAULT_STARTS]
                    comparisons.append({"group": group, "arm": arm, "metric": metric,
                                        "delta_vs_dedup": st.median(d), "positive_starts": sum(v > 0 for v in d)})
    write_csv("paired_metrics.csv", paired); write_csv("paired_vs_dedup.csv", comparisons)
    save("report_index.json", {"groups": {g: list(arms) for g, arms in groups.items()}})
    def m(group, arm, metric): return index[(group, arm, metric)]
    decisions = []
    for arm in groups["full"]:
        if arm == "BASE": continue
        reasons = []
        for metric in ("年化", "滚动5年年化中位"):
            if m("full", arm, metric)["paired_delta_median"] < -sw.RULING_TOLERANCE:
                reasons.append(metric + "损失超过轨道A护栏")
        if m("full", arm, "滚动5年回撤中位")["paired_delta_median"] > sw.DRAWDOWN_GATE:
            reasons.append("回撤闸门")
        negative = sum(float(groups["full"]["BASE"][s]["滚动5年为负的窗口占比"]) == 0 and
                       float(groups["full"][arm][s]["滚动5年为负的窗口占比"]) > 0 for s in sw.DEFAULT_STARTS)
        if negative > len(sw.DEFAULT_STARTS)/2: reasons.append("负收益窗口否决")
        u = next(g for g, arms in groups.items() if g.startswith("U") and arm in arms)
        inferior = []
        for metric, scale, good in CLAUSE4:
            change = m(u, arm, metric)["paired_delta_median"] * scale * good
            if change < -(.005 if scale == 1 else .15):
                inferior.append({"metric": metric, "oriented_delta": change,
                                 "beyond_one_pp": change < -(.033 if scale == 1 else 1)})
        decisions.append({"arm": arm, "track": "A", "initial_guardrails_passed": not reasons,
                          "diagnostic_raw_line": arm == "WCOPRAWSEP09", "reasons": reasons,
                          "negative_new_starts": negative, "U_group": u,
                          "U_excellent": not inferior or (len(inferior) == 1 and not inferior[0]["beyond_one_pp"]),
                          "U_inferior": inferior})
    save("decisions.json", decisions)
    by_start = []
    for s in sw.DEFAULT_STARTS:
        out = {"start": s}
        for arm in ("BASE", "WCREPSEP09", "WCOPM15SEP09", "WCOPRAWSEP09"):
            for g in ("full", "A"):
                r = groups[g][arm][s]; base = groups[g]["BASE"][s]
                out[g+":"+arm+":CAGR"] = r["年化"]
                out[g+":"+arm+":delta"] = float(r["年化"])-float(base["年化"])
        by_start.append(out)
    write_csv("cagr_by_start.csv", by_start)
    text = ["# OI-168 营运资金修复回测", "", "全部Δ为14起点配对差中位，单位pp，回撤Δ为正表示变深；会计修复按轨道A。",
            "U各自对同剔除集BASE，不同U不跨候选比较。原门槛臂只作拆解诊断。", "",
            "| 方案 | 全样本年化中位 | Δ年化全 | Δ年化A | Δ年化U | Δ滚5全 | Δ滚5 A | Δ滚5回撤全 | 初步护栏 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for d in sorted(decisions, key=lambda r: m("full", r["arm"], "年化")["paired_delta_median"], reverse=True):
        arm = d["arm"]; cells = [f"{m('full',arm,'年化')['level_median']:.2%}"]
        for g, metric in (("full", "年化"), ("A", "年化"), (d["U_group"], "年化"),
                          ("full", "滚动5年年化中位"), ("A", "滚动5年年化中位"), ("full", "滚动5年回撤中位")):
            cells.append(f"{m(g,arm,metric)['paired_delta_median']*100:+.2f}")
        text.append(f"| {arm} | " + " | ".join(cells) + " | " + ("通过" if d["initial_guardrails_passed"] else "未通过") + " |")
    text += ["", f"原BASE全样本年化中位{m('full','BASE','年化')['level_median']:.2%}；A为{m('A','BASE','年化')['level_median']:.2%}。两个水平中位之差不等于配对差中位；逐起点数见cagr_by_start.csv。",
             "", "中心档相对上一轮仅去重版本："]
    for g in ("full", "A"):
        r = next(r for r in comparisons if r["group"] == g and r["arm"] == "WCOPM15SEP09" and r["metric"] == "年化")
        text.append(f"- {g}：Δ年化 {r['delta_vs_dedup']*100:+.2f}pp，正号{r['positive_starts']}/14。")
    text += ["", "完整标准指标、尾部和集中度见report_full_A.txt及report_U*.txt；44指标的水平/配对差/正号数见paired_metrics.csv。历史结果不作未来收益预测。"]
    (EXP / "readout.md").write_text("\n".join(text) + "\n")
    print("\n".join(text))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--valuation-only", action="store_true")
    args = parser.parse_args()
    valuation_report()
    if not args.valuation_only: backtest_report()

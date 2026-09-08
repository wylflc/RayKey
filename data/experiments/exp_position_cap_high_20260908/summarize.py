"""Build exact paired comparisons; keep parameter and implementation effects separate."""
import csv
import json
import math
from pathlib import Path
import statistics as st
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sw

CONTROL = "PC60SSEP08"
CANDIDATES = [f"PC{cap}SSEP08" for cap in (70, 80, 90, 100)]
LABELS = ["BASE", CONTROL, *CANDIDATES]
NAMES = {"BASE": "当前60%", **{f"PC{cap}SSEP08": f"严格{cap}%" for cap in (60,70,80,90,100)}}


def write_csv(name, rows):
    with (EXP / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    manifest = json.loads((EXP / "manifest.json").read_text())
    verification = json.loads((EXP / "verification.json").read_text())
    assert verification["inputs_unchanged"]
    groups = {}
    with (EXP / "summary_rows.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == verification["summary_rows"]
    for row in rows:
        arm = groups.setdefault(row["group"], {}).setdefault(row["arm"], {})
        assert row["start"] not in arm
        assert row["计量版本"] == sw.METRIC_VERSION == manifest["metric"]
        arm[row["start"]] = row
        assert all(math.isfinite(sw._field_value(row, key)) for key in sw.FIELDS)
    for group in groups.values():
        for arm in group.values():
            assert set(arm) == set(manifest["starts"])
    assert set(groups["full"]) == set(groups["A"]) == set(LABELS)

    def values(group, label, key):
        return [float(group[label][start][key]) for start in manifest["starts"]]

    def differences(group, label, key, base="BASE"):
        return [a-b for a,b in zip(values(group,label,key), values(group,base,key))]

    def level(group, label, key="年化", scale=100):
        return st.median(values(group,label,key))*scale

    def delta(group, label, key="年化", base="BASE", scale=100):
        return st.median(differences(group,label,key,base))*scale

    metrics = list(dict.fromkeys([item[1] for item in sw.STANDARD_SET] + list(sw.FIELDS[6:12]) + ["滚动10年年化中位"]))
    comparisons, pairs = [], []
    for group_name, group in groups.items():
        for label in group:
            for base in ("BASE", CONTROL):
                for key in metrics:
                    diffs = differences(group,label,key,base)
                    comparisons.append({"group":group_name,"arm":label,"reference":base,"metric":key,
                                        "median":st.median(values(group,label,key)),
                                        "paired_delta_median":st.median(diffs),
                                        "positive_starts":sum(d>0 for d in diffs),"starts":len(diffs)})
                for start in manifest["starts"]:
                    row, ref = group[label][start], group[base][start]
                    pairs.append({"group":group_name,"arm":label,"reference":base,"start":start,
                                  "cagr":row["年化"],"reference_cagr":ref["年化"],
                                  "delta_cagr":float(row["年化"])-float(ref["年化"]),
                                  "delta_roll5":float(row["滚动5年年化中位"])-float(ref["滚动5年年化中位"]),
                                  "delta_nonoverlap5":float(row["互不重叠5年块中位"])-float(ref["互不重叠5年块中位"])})
    write_csv("comparisons.csv", comparisons)
    write_csv("paired_by_start.csv", pairs)
    adjacent = []
    for scope in ("full", "A"):
        group = groups[scope]
        for lower, upper in zip(LABELS[1:-1], LABELS[2:]):
            for key in ("年化", "滚动5年年化中位", "互不重叠5年块中位"):
                diffs = differences(group,upper,key,lower)
                adjacent.append({"group":scope,"lower":lower,"upper":upper,"metric":key,
                                 "paired_delta_median":st.median(diffs),
                                 "positive_starts":sum(d>0 for d in diffs),"starts":len(diffs)})
    write_csv("adjacent_comparisons.csv", adjacent)

    lines = ["# 单股买入上限放宽至70%／80%／90%／100%", "",
             "买入上限以净资产为分母；被动超限不触发卖出，既有卖出规则不变。所有新候选使用前次独立实验的整手守卫。",
             "原实现60%（BASE）与严格60%同批复跑，分别隔离相对当前策略的总变化与单纯上限变化。融资、费用、估值、股票池、执行时点均不变。",
             "计量m2、14个标准起点；水平是各起点中位，Δ先按同起点相减再取中位，不等于两个水平中位数相减。数据末次净值日2026-08-28；155份面板行情仍止于8月7日。", ""]
    for name, title in (("full","全样本"),("A","剔除基准五大赢家 A")):
        group = groups[name]
        lines += [f"## {title}", "",
                  "| 上限／实现 | 年化中位数 | Δ年化 对当前60% pp | 正号起点 | Δ年化 对严格60% pp | Δ滚5 对当前60% pp |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for label in LABELS:
            positive = sum(d>0 for d in differences(group,label,"年化"))
            lines.append(f"| {NAMES[label]} | {level(group,label):.2f}% | {delta(group,label):+.2f} | {positive}/14 | {delta(group,label,base=CONTROL):+.2f} | {delta(group,label,'滚动5年年化中位'):+.2f} |")
        lines.append("")

    lines += ["## 双方赢家并集 U", "",
              "各U按候选与BASE在2011-11-01的前五赢家并集确定；不同U的候选水平不能直接比较。", "",
              "| 候选 | 剔除集 | 同集BASE年化 | 候选年化 | Δ年化 对当前60% pp | 正号起点 | Δ年化 对严格60% pp | Δ滚5 对当前60% pp |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    overview = {}
    for name, info in verification["union_groups"].items():
        group = groups[name]
        for label in info["candidates"]:
            positive = sum(d>0 for d in differences(group,label,"年化"))
            lines.append(f"| {NAMES[label]} | {name}，{len(info['codes'])}只 | {level(group,'BASE'):.2f}% | {level(group,label):.2f}% | {delta(group,label):+.2f} | {positive}/14 | {delta(group,label,base=CONTROL):+.2f} | {delta(group,label,'滚动5年年化中位'):+.2f} |")
            # Workflow 12.1.4 excludes turnover and the separate concentration table.
            qualifying = []
            for short, key, _scale, _width, _precision, good in sw.STANDARD_SET:
                if key == "年均换手":
                    continue
                raw = st.median(differences(group,label,key))*good
                ratio = "Calmar" in key or "Sharpe" in key
                qualifying.append({"metric":key,"oriented_delta":raw,
                                   "noise":.005 if ratio else .0015,
                                   "tolerance":.033 if ratio else .01})
            failures = [item for item in qualifying if item["oriented_delta"] < -item["noise"]]
            excellent = len(failures) == 0 or (len(failures) == 1 and failures[0]["oriented_delta"] >= -failures[0]["tolerance"])
            overview[label] = {"U_group":name,"U_codes":info["codes"],"workflow_U_excellent":excellent,
                               "U_qualification_metrics":qualifying}
            for scope in ("full","A",name):
                g = groups[scope]
                overview[label][scope] = {"cagr_median":level(g,label)/100,
                                         "delta_vs_current":delta(g,label)/100,
                                         "delta_vs_strict60":delta(g,label,base=CONTROL)/100,
                                         "positive_vs_current":sum(d>0 for d in differences(g,label,"年化")),
                                         "delta_roll5":delta(g,label,"滚动5年年化中位")/100}
    lines.append("")
    for name, info in verification["union_groups"].items():
        lines.append(f"- {name}：{','.join(info['codes'])}；{'复用A' if info['reuses_A'] else '独立补跑'}。")

    lines += ["", "## 两个长跑锚点（全样本年化）", "",
              "| 起点 | " + " | ".join(NAMES[label] for label in LABELS) + " |",
              "| --- | " + " | ".join("---:" for _ in LABELS) + " |"]
    for start in sw.LONGRUN_STARTS:
        lines.append(f"| {groups['full']['BASE'][start]['首个净值日']} | " + " | ".join(
            f"{float(groups['full'][label][start]['年化'])*100:.2f}%" for label in LABELS) + " |")
    lines += ["", "## 非重叠五年块与资金分配（全样本）", "",
              "| 上限／实现 | 5年块中位 | Δ5年块 pp | 平均仓位 | 持仓数中位 | 单票权重中位 | 年均换手 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    g = groups["full"]
    for label in LABELS:
        lines.append(f"| {NAMES[label]} | {level(g,label,'互不重叠5年块中位'):.2f}% | {delta(g,label,'互不重叠5年块中位'):+.2f} | {level(g,label,'平均仓位'):.2f}% | {level(g,label,'持仓数中位',1):.1f} | {level(g,label,'单票权重中位'):.2f}% | {level(g,label,'年均换手',1):.2f} |")
    lines += ["", "## 同日两轮严格上限剂量表", "",
              "20%／25%／30%引用上一轮精确摘要；本轮输入哈希与上轮一致，BASE及严格60%的全/A标准报告字段逐位复现。以下所有上限均严格执行。", "",
              "| 严格上限 | 全样本年化中位数 | A年化中位数 |", "| --- | ---: | ---: |"]
    with (EXP.with_name("exp_position_cap_25_20260908") / "summary_rows.csv").open() as handle:
        old = list(csv.DictReader(handle))
    for cap in (20,25,30):
        label = f"PC{cap}SSEP08"
        cells = [st.median(float(row["年化"]) for row in old if row["group"]=="strict_"+scope and row["arm"]==label)*100 for scope in ("full","A")]
        lines.append(f"| {cap}% | {cells[0]:.2f}% | {cells[1]:.2f}% |")
    for cap in (60,70,80,90,100):
        label = f"PC{cap}SSEP08"
        lines.append(f"| {cap}% | {level(groups['full'],label):.2f}% | {level(groups['A'],label):.2f}% |")
    lines += ["", "## 结果解释", "",
              "全样本中四个放宽档位的配对年化均低于当前60%及严格60%，非重叠五年块也下降；本次结果不支持为提高收益而放宽上限。",
              "A集下方向相反，四档配对年化均为正；70%／80%在再剔除海螺水泥的U1中转负，90%／100%的U2等于A，保留正号。这说明上限效果随具体股票集合及资金路径变化，不存在此次证据支持的普遍单调关系。",
              "60%在本日已测严格档位的全样本年化水平最高，不等于证明60%是全局或未来最优；本轮未扫描30%至60%之间的全部档位。", ""]
    lines += ["", "## 复核与使用边界", "",
              f"实际执行{verification['paths_full_A'] + verification['paths_U']}条回测路径；保留{len(rows)}条完整摘要（若U=A，引用行不计新执行路径）。",
              "BASE与严格60%的全样本/A标准报告字段对上一轮逐位复现；前五赢家占正贡献一处浮点尾差约1e-16单独记录，其他字段精确一致。本轮输入哈希前后不变，续跑前另核源文件不变。普通A摘要缓存已恢复。",
              "完整标准指标与跨起点尾部见 report_full_A.txt 和 report_U*.txt；逐指标对两个对照的精确配对差见 comparisons.csv，逐起点差见 paired_by_start.csv。",
              "新增四个候选名；本日两轮上限实验累计11个候选名，不把重复对照或U集合副本算作新增参数。更早纪元扫描记录另存台账，未拼入本次收益水平。",
              "上限变化会改变资金分配、后续信号参与及净值路径，不能仅凭最终收益分离具体归因；14起点共享大量历史，不是14次独立验证。",
              "本次是研究实验，生产仍为原实现60%；OI-167仍待正式处理。历史收益与配对差均不作为未来预测。", ""]
    (EXP / "readout.md").write_text("\n".join(lines))
    (EXP / "overview.json").write_text(json.dumps(overview,ensure_ascii=False,indent=2)+"\n")
    (EXP / "verification_summary.json").write_text(json.dumps({
        "summary_rows":len(rows),"unique_group_arm_start":True,"all_starts_complete":True,
        "metric":"m2","all_report_fields_finite":True,"comparisons":len(comparisons),
        "paired_rows":len(pairs)},indent=2)+"\n")


if __name__ == "__main__":
    main()

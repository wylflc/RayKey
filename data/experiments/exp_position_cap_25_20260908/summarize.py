"""Consolidate exact summary rows and generate paired, reproducible readout tables."""
import csv
import json
from pathlib import Path
import statistics as st

EXP = Path(__file__).resolve().parent


def read_group(name):
    groups = {}
    for path in sorted((EXP / "summaries" / name).glob("summary_*.csv")):
        with path.open() as handle:
            row = next(csv.DictReader(handle))
        label = path.stem.removeprefix("summary_")
        if label.endswith("ex5"):
            label = label[:-3]
        label, start = label[:-8], label[-8:]
        groups.setdefault(label, {})[start] = row
    return groups


def write_csv(name, rows):
    with (EXP / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def values(group, arm, metric):
    return [float(row[metric]) for _, row in sorted(group[arm].items())]


def delta(group, arm, metric, base="BASE"):
    return [value - reference for value, reference in zip(values(group, arm, metric), values(group, base, metric))]


def main():
    manifest = json.loads((EXP / "manifest.json").read_text())
    verification = json.loads((EXP / "verification_strict.json").read_text())
    starts = {start.replace("-", "") for start in manifest["starts"]}
    groups = {name: read_group(name) for name in ("full", "A", "U", "strict_full", "strict_A", "strict_U")}
    if verification["U_reuses_A"]:
        groups["strict_U"] = {label: groups["strict_A"][label] for label in ("BASE", "PC25SSEP08")}
    for group in groups.values():
        for arm in group.values():
            assert set(arm) == starts
            assert all(row["计量版本"] == "m2" for row in arm.values())
    for group, reference in (("strict_full", "full"), ("strict_A", "A")):
        assert groups[group]["BASE"] == groups[reference]["BASE"], "BASE changed between runs"
    consolidated = []
    paired = []
    for group_name, group in groups.items():
        for label, by_start in group.items():
            for start, row in sorted(by_start.items()):
                consolidated.append({"group": group_name, "arm": label, "start": start, **row})
                base = group["BASE"][start]
                paired.append({"group": group_name, "arm": label, "start": start,
                               "cagr": row["年化"], "baseline_cagr": base["年化"],
                               "delta_cagr": float(row["年化"]) - float(base["年化"]),
                               "roll5": row["滚动5年年化中位"],
                               "delta_roll5": float(row["滚动5年年化中位"]) - float(base["滚动5年年化中位"])})
    write_csv("summary_rows.csv", consolidated)
    write_csv("paired_by_start.csv", paired)
    lines = ["# 单股买入上限 25% 对照结果", "",
             "主表采用严格整手守卫：剩余上限额度不足一手则跳过，不因被动超限卖出。BASE 为现行 60% 原实现。",
             "14 个标准起点；计量 m2；本金、融资、费税、估值、股票池及买卖时点保持原基准。摘要止于 2026-08-28，行情缓存末端不齐。",
             "水平为各起点中位，Δ 为同起点配对差中位；两者不得相减替代。所有收益均为历史模拟。", "",
             "## 1. 主比较：严格 25% 对当前 60%", "",
             "| 口径 | BASE年化 | 25%年化 | 配对Δ年化 pp | 为正起点 | 配对Δ滚5中位 pp |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, title in (("strict_full", "全样本"), ("strict_A", "剔除A"), ("strict_U", "剔除U")):
        group = groups[name]
        ds = delta(group, "PC25SSEP08", "年化")
        lines.append(f"| {title} | {st.median(values(group,'BASE','年化'))*100:.2f}% | {st.median(values(group,'PC25SSEP08','年化'))*100:.2f}% | {st.median(ds)*100:+.2f} | {sum(d>0 for d in ds)}/14 | {st.median(delta(group,'PC25SSEP08','滚动5年年化中位'))*100:+.2f} |")
    lines += ["", f"严格25% A={','.join(verification['A'])}；B={','.join(verification['B'])}；U={','.join(verification['U'])}。", "",
              "## 2. 邻档与整手实现分解", "",
              "| 实现／上限 | 全样本年化 | 配对Δ pp | A年化 | 配对Δ pp |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for label, title, prefix in (("BASE","当前60%",""), ("PC60SSEP08","严格60%","strict_"),
                                  ("PC20SSEP08","严格20%","strict_"), ("PC25SSEP08","严格25%","strict_"),
                                  ("PC30SSEP08","严格30%","strict_"), ("PC25SEP08","原实现25%","")):
        parts = []
        for name in (prefix+"full", prefix+"A"):
            group = groups[name]
            parts += [f"{st.median(values(group,label,'年化'))*100:.2f}%", f"{st.median(delta(group,label,'年化'))*100:+.2f}"]
        lines.append(f"| {title} | " + " | ".join(parts) + " |")
    lines += ["", "严格25%减严格60%（两侧均执行整手守卫），全样本/A 的配对Δ年化分别为 " +
              " / ".join(f"{st.median(delta(groups[name],'PC25SSEP08','年化','PC60SSEP08'))*100:+.2f}pp" for name in ("strict_full","strict_A")) + "。", "",
              "## 3. 两个长跑起点（全样本）", "",
              "| 起点 | BASE年化 | 严格25%年化 | Δ pp | BASE期末资产 万元 | 严格25%期末资产 万元 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for start in ("20091101", "20111101"):
        base, cap = (groups["strict_full"][label][start] for label in ("BASE", "PC25SSEP08"))
        lines.append(f"| {base['首个净值日']} | {float(base['年化'])*100:.2f}% | {float(cap['年化'])*100:.2f}% | {(float(cap['年化'])-float(base['年化']))*100:+.2f} | {float(base['期末资产'])/1e4:.2f} | {float(cap['期末资产'])/1e4:.2f} |")
    lines += ["", "## 4. 资金分配与其它描述指标（全样本）", "",
              "| 指标 | BASE水平 | 严格25%水平 | 配对差 |", "| --- | ---: | ---: | ---: |"]
    for key, scale in (("平均仓位",100),("持仓数中位",1),("单票权重中位",100),("前三权重中位",100),
                       ("年均换手",1),("滚动5年年化P25",100),("互不重叠5年块中位",100),
                       ("逐年收益中位",100),("最大回撤",100),("Sharpe",1)):
        group = groups["strict_full"]
        lines.append(f"| {key}{'（%／pp）' if scale==100 else ''} | {st.median(values(group,'BASE',key))*scale:.3f} | {st.median(values(group,'PC25SSEP08',key))*scale:.3f} | {st.median(delta(group,'PC25SSEP08',key))*scale:+.3f} |")
    lines += ["", "## 5. 复核与边界", "",
              "两批 BASE 全/A 原始摘要逐字段一致，第一批对原在册 BASE 的报告字段也无变化；两批源输入前后哈希一致。",
              "本轮共7个候选名：原实现20/25/30，严格实现20/25/30/60；各批U只用于对应25%候选，不能跨不同剔除集直接比较。",
              "严格守卫的四项合成路径检查覆盖新建仓越限、上限内的一手成交、加仓剩余额度不足一手、被动超限不卖出。",
              "生产引擎与交易参数未改；整手边界缺陷另记待处理。单股权重仍可被动超过25%，此上限不等于每日强制再平衡。",
              "完整标准集及跨起点尾部见 report_strict_full_A.txt / report_strict_U.txt；summary_rows.csv 保留全部精确摘要，paired_by_start.csv 保留逐起点差。", ""]
    (EXP / "readout.md").write_text("\n".join(lines), encoding="utf-8")
    (EXP / "verification_summary.json").write_text(json.dumps({"summary_rows": len(consolidated), "starts_per_arm":14,
                                                               "baseline_original_and_strict_batches_identical": True}, indent=2)+"\n")


if __name__ == "__main__":
    main()

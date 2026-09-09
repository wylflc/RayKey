"""Separate the first economic trade change from valuation-only ledger changes."""
import csv
from itertools import zip_longest
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent


def main():
    verification = json.loads((EXP / "attribution_verification.json").read_text())
    assert verification["paths_reproduced"] == 24 and verification["inputs_unchanged"]
    with (EXP / "attribution_summary.csv").open() as f:
        comparisons = list(csv.DictReader(f))
    fields = ("date", "security_code", "action", "shares", "price", "amount")
    differences = []
    for r in comparisons:
        base = EXP / "attrib" / r["group"] / r["start"] / r["base"] / "ledger.csv"
        arm = EXP / "attrib" / r["group"] / r["start"] / r["arm"] / "ledger.csv"
        with base.open() as bf, arm.open() as af:
            for i, (br, ar) in enumerate(zip_longest(csv.DictReader(bf), csv.DictReader(af)), 1):
                if br is None or ar is None or any(br[k] != ar[k] for k in fields):
                    differences.append({k: r[k] for k in ("group", "start", "arm", "base")} |
                                       {"ledger_row": i, "base_trade": br, "arm_trade": ar})
                    break
    (EXP / "first_economic_trade_differences.json").write_text(json.dumps(differences, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 两长跑锚点的交易归因", "", "贡献按闭合周期逐日盈亏/前日净资产累计，不能加总成CAGR差。",
             "前三代码按贡献差绝对值排序；净额占比可为负或超过100%。", "",
             "| 样本 | 起点 | 候选 | 对照 | ΔCAGR pp | 前三代码 | 前三净额占比 | 前三绝对贡献占比 |",
             "| --- | --- | --- | --- | ---: | --- | ---: | ---: |"]
    for r in comparisons:
        lines.append("| " + " | ".join([r["group"], r["start"], r["arm"], r["base"],
            f"{float(r['delta_CAGR'])*100:+.2f}", r["top3_codes"],
            f"{float(r['top3_net_share']):.1%}" if r["top3_net_share"] else "NA",
            f"{float(r['top3_gross_share']):.1%}" if r["top3_gross_share"] else "NA"]) + " |")
    lines += ["", "## 相同会计口径，仅对齐买入线的首次真实成交分叉", "",
              "下列对比剔除仅估值/PV字段变化；比较日期、代码、方向、股数、价格和金额。"]
    for r in differences:
        if r["base"] != "WCOPRAWSEP09": continue
        def describe(t):
            if t is None: return "无后续成交"
            return f"{t['date']} {t['security_code']} {t['action']} {t['shares']}股，成交价{t['price']}，流水P/V {t['pv_ratio'] or '空'}"
        lines += ["", f"- {r['group']} / {r['start']}，第{r['ledger_row']}笔：原线 {describe(r['base_trade'])}；对齐线 {describe(r['arm_trade'])}。"]
    lines += ["", "全部代码贡献差见attribution_codes.csv；完整首次经济成交变化见first_economic_trade_differences.json。"]
    (EXP / "attribution_readout.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

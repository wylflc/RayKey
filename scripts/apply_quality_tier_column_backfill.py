#!/usr/bin/env python3
"""回填 §5.7.4 两个有硬性依赖的子集：L1 的 `q2_moat_type` 与 L3 的 `tactical_thesis`（OI-024）。

与 `backfill_quality_tier_columns.py` 的分工
--------------------------------------------
那个脚本只做**转录**（把 `moat_summary` 里已有的「前瞻侵蚀」段搬进 `q2_erosion_paths`），
不含任何判断。本脚本承载的是**判断**，因此内容以逐票常量表写死在这里、可逐条复核，
而不是由规则从自由文本里猜——§5.7.4 硬约束第 4 条禁止关键词脚本自动打分。

为什么只回填这两列
------------------
六列里这两列各自卡着一条现行规则：

* `q2_moat_type`（L1 22 家）——§5.7.2 的 L1 否决判据第 1 条要求「点名具体路径」，而
  路径要针对**哪一种壁垒**才有意义。护城河类型不落列，否决与非否决就只能在自由文本里比。
* `tactical_thesis`（L3 9 家）——§6.2.1 对 L3 的买入前置是「须有明确战术理由兑现路径」。
  该列为空 = 这条前置当前**对 9 家全部无法校验**。

其余四列（`q1_reason`/`q3_reason`/`q4_reason` 与 L2 的 `q2_moat_type`）内容散在
`score_reason` 里、且不卡任何现行规则，按 §5.7.4 随下一次季度质量复核（§5.1）逐票回填。

证据与效力
----------
两张表的内容**全部由该行自身已在库的 `moat_summary`/`score_reason`/`peer_comparison`/
`flags` 归纳而来，不引入任何新证据、不改任何档位与分数**（§5.7.4 硬约束第 6 条：档与
分数只在质量复核时凭新证据变更）。因此它们是**初稿**，须在下一次季度质量复核时逐票确认。

`tactical_thesis` 允许并且**必须**能写「无」：§6.2.1 对 L3 的前置若不成立，如实写无，
该票即使落到低估档也不可买。9 家里 5 家判无——把"没有战术理由"写出来，正是这一列的用处。

用法::

    python3 scripts/apply_quality_tier_column_backfill.py
    python3 scripts/apply_quality_tier_column_backfill.py --check
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"

# 护城河类型词表（七类，与 §5.7 的壁垒表述同源）：
#   品牌与心智／行政法律独占／资源地理独占／网络效应与生态／转换成本与认证锁定／
#   成本与规模优势／事实标准与技术代际
# 多类型以 `+` 连接，**排在首位的是主壁垒**（§5.7.2 判据 1 点名路径时对准的就是它）。
L1_MOAT_TYPE = {
    "600519": "品牌与心智 + 资源地理独占（赤水河产区、陈年基酒）",
    "000858": "品牌与心智 + 资源地理独占（明代老窖池）",
    "600809": "品牌与心智（清香品类第一心智）",
    "000568": "资源地理独占（400年连续使用老窖池）+ 品牌与心智",
    "000538": "行政法律独占（国家保密配方）+ 品牌与心智",
    "600436": "行政法律独占（国家绝密配方、天然麝香配额）+ 品牌与心智",
    "600900": "资源地理独占（长江干流梯级电站）+ 成本与规模优势",
    "601088": "行政法律独占（煤炭产能指标冻结）+ 成本与规模优势（路港电一体化）",
    "603505": "行政法律独占（萤石采矿证）+ 资源地理独占（储量产量第一）",
    "002049": "转换成本与认证锁定（军工资质）+ 事实标准与技术代际（FPGA双寡头）",
    "002371": "转换成本与认证锁定（各大 fab 验证深度）+ 成本与规模优势（多品类平台）",
    "688120": "转换成本与认证锁定（CMP 独家量产 + 耗材服务绑定）",
    "688008": "事实标准与技术代际（JEDEC 标准制定者、内存接口双寡头）",
    "688111": "网络效应与生态（办公套件生态位）+ 行政法律独占（信创标配）",
    "600660": "成本与规模优势 + 转换成本与认证锁定（整车厂认证与快速响应）",
    "600406": "事实标准与技术代际（继保/调度事实标准）+ 行政法律独占（电网安全责任壁垒）",
    "300750": "成本与规模优势 + 事实标准与技术代际（麒麟/神行/钠电代际）",
    "600161": "行政法律独占（浆站牌照 2001 年后近乎冻结）",
    "600160": "行政法律独占（基加利协定三代制冷剂配额）+ 成本与规模优势（氟氯联动一体化）",
    "600862": "转换成本与认证锁定（航空复材资质认证锁定）",
    "688122": "转换成本与认证锁定（军钛与超导全流程资质）+ 事实标准与技术代际",
    "600415": "网络效应与生态（六十万商户 × 全球采购商）+ 资源地理独占（义乌市场物理位置）",
}

# L3 战术理由（§6.2.1 买入前置）。每条要么给出**可证伪的兑现路径 + 里程碑**，要么写「无」。
L3_TACTICAL_THESIS = {
    "603156": "**无**。品类结构性退潮已在数上兑现（收入 −12%／利润 −27%），新品类拓展未验证，"
              "无可指的兑现里程碑；高分红属估值理由而非战术理由。按 §6.2.1 即使落低估档亦不可买。",
    "300146": "**无**。品牌壁垒正被线上白牌与跨境购侵蚀且**侵蚀正在发生**（连续两年收入下滑 −8.4%、"
              "ROE 降至 7.2%、药店渠道萎缩），无止跌路径。按 §6.2.1 即使落低估档亦不可买。",
    "301498": "**有（条件式）**：高端线弗列加特放量 + 国产替代份额提升，是 9 家 L3 中唯一已有超额回报证据者"
              "（ROE 15.3%／收入 +29%）。**兑现里程碑**：①弗列加特收入占比与其毛利率逐季不降；"
              "②线上主要平台份额不被新锐品牌与外资反扑侵蚀。任一转负即本战术理由失效。",
    "300474": "**有（条件式，未验证）**：景宏系列 AI 训推卡商业化。当前仍亏损（NM −31.4%）、"
              "商业化对照海光/昇腾落后两档，故本条属**待验证**而非已成立。"
              "**兑现里程碑**：AI 卡出现有价格与订单量的对外收入并连续两季确认；在此之前按无战术理由处理。",
    "300232": "**无**。与利亚德同处内卷硬件层且盈利更弱（ROE 1.4%／利润 −36.8%），项目制 + 价格战 + 应收，"
              "无可指的兑现路径。按 §6.2.1 即使落低估档亦不可买。",
    "002236": "**无**。命中 `dominated`——被海康全方位覆盖且无不可替代利基，锚点双重对照显示份额、盈利、"
              "创新业务全面次位（ROE 10.4% 对 17.3%），同受制裁。被全面覆盖本身即战术理由不成立的定义。",
    "300341": "**无**。供应链位置非垄断（ABB/西门子多供应商体系）、盈利平庸（ROE 9.1%）、业务组合分散；"
              "对照华明装备无同等品类垄断位与回报证据。按 §6.2.1 即使落低估档亦不可买。",
    "300360": "**有（条件式）**：电网招标节奏恢复 + 海外 AMI 拓展。盈利质量本身不差（NM 34.3%），"
              "当前收入 −16.8% 主因招标节奏而非份额流失。**兑现里程碑**：①国网/南网招标中标额同比转正；"
              "②海外收入占比逐季提升。两项均不兑现即回到无战术理由。",
    "000157": "**有（条件式）**：出口与高空作业机械对冲地产链下行。**兑现里程碑**：①海外收入占比继续提升；"
              "②应收账款周转与金融性销售敞口不再扩大（该项是历史问题，须逐期核）。"
              "对照三一/徐工同档，本条不构成相对优势，只构成本票自身的周期兑现路径。",
}


def apply_backfill(rows: list[dict[str, str]]) -> tuple[int, int, list[str]]:
    moat_written = thesis_written = 0
    mismatches: list[str] = []
    by_code = {row.get("security_code", ""): row for row in rows}

    for code, value in L1_MOAT_TYPE.items():
        row = by_code.get(code)
        if row is None:
            mismatches.append(f"L1 表中的 {code} 不在分层表内")
            continue
        if row.get("quality_tier") != "L1":
            mismatches.append(f"{row.get('security_name')}({code}) 已不是 L1（现 {row.get('quality_tier')}），跳过")
            continue
        if not (row.get("q2_moat_type") or "").strip():
            row["q2_moat_type"] = value
            moat_written += 1

    for code, value in L3_TACTICAL_THESIS.items():
        row = by_code.get(code)
        if row is None:
            mismatches.append(f"L3 表中的 {code} 不在分层表内")
            continue
        if row.get("quality_tier") != "L3":
            mismatches.append(f"{row.get('security_name')}({code}) 已不是 L3（现 {row.get('quality_tier')}），跳过")
            continue
        if not (row.get("tactical_thesis") or "").strip():
            row["tactical_thesis"] = value
            thesis_written += 1

    # 覆盖面自检：表里写死的家数必须与分层表当前的 L1/L3 家数一致，不一致说明分层变过而本表没跟上。
    l1_now = sum(1 for row in rows if row.get("quality_tier") == "L1")
    l3_now = sum(1 for row in rows if row.get("quality_tier") == "L3")
    if l1_now != len(L1_MOAT_TYPE):
        mismatches.append(f"**L1 现有 {l1_now} 家，本表只覆盖 {len(L1_MOAT_TYPE)} 家**")
    if l3_now != len(L3_TACTICAL_THESIS):
        mismatches.append(f"**L3 现有 {l3_now} 家，本表只覆盖 {len(L3_TACTICAL_THESIS)} 家**")
    return moat_written, thesis_written, mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 L1 q2_moat_type 与 L3 tactical_thesis（OI-024）")
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--check", action="store_true", help="只报当前覆盖，不写回")
    args = parser.parse_args()

    with args.tiers.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    for column in ("q2_moat_type", "tactical_thesis"):
        if column not in fields:
            fields.append(column)
        for row in rows:
            row.setdefault(column, "")

    if args.check:
        l1 = [r for r in rows if r.get("quality_tier") == "L1"]
        l3 = [r for r in rows if r.get("quality_tier") == "L3"]
        print(f"L1 q2_moat_type 非空 {sum(1 for r in l1 if (r.get('q2_moat_type') or '').strip())}/{len(l1)}")
        print(f"L3 tactical_thesis 非空 {sum(1 for r in l3 if (r.get('tactical_thesis') or '').strip())}/{len(l3)}")
        return 0

    moat, thesis, mismatches = apply_backfill(rows)
    with args.tiers.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"回填 q2_moat_type {moat} 行（L1）、tactical_thesis {thesis} 行（L3）")
    no_thesis = sum(1 for row in rows
                    if row.get("quality_tier") == "L3" and (row.get("tactical_thesis") or "").startswith("**无**"))
    print(f"  其中 L3 判「无战术理由」{no_thesis} 家 —— 按 §6.2.1，这几家即使落低估档也不可买")
    for note in mismatches:
        print(f"  ⚠ {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

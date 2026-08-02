#!/usr/bin/env python3
"""海外关注清单逐票估值档案与参考分（§6.8 + §6.5.7 + §5.7.4）。

为什么要有这个脚本
------------------
海外清单原先的 21 条带是**通用十一类公式直接套出来的**，与 A 股在 v2.00 已经退役的
那条路径同源。2026-08-03 建档前审计实测出四类缺陷：

1. **倍数直接指定或用历史 PE 中位**（11/19 有带者）——违反 §6.5.7 v1.54「倍数必须
   被推导出来，不得直接指定」。例：京东「修复后合理PE 8-10x」、英伟达「合理PE 27x」
   都只有定性理由；腾讯/海底捞/Adobe 用自身 5-10 年 PE 中位回归。
2. **带宽由方法自身区间叠加**——PEG [1.0,1.5] 被直接当成带宽，泡泡玛特/谷歌/优步/
   微软/Meta 五条带宽度 ≈1.50，而 A 股 261 条带的中位是 1.235、**最大只有 1.278**。
   §6.5.7 v1.62 明写「带宽一律由分层系数承担，不由方法自身的区间叠加」。
3. **PEG 未写 ROE 修正理由**（6 家）——§6.5.7 v1.54 要求写明取值理由。
4. **美光状态自相矛盾**——`valuation_tier` 是「周期假设未决」，带却仍参与自动定档并
   显示「高估」、空间 −88%；其自身推导写明两情景相差 12-18 倍。按 §6.5.5.1，
   按定义不可双向使用的带一律判「无法估值」并清空带。

本脚本把这 21 家改成**输入 → 计算 → 带**的可复算形式：每个输入都带出处，每条带都由
下面四条路径之一算出，不再有「先有档位、后凑带」的空间。

方法路径（§6.5.7 v1.54 三选一，外加不可估值）
--------------------------------------------
* ``implied_pe``  稳态、g < r：``PE = 分红率/(r − g)``（戈登）
* ``ddm3``        分红率 ≥60%，或 g ≥ r 使戈登失效：三阶段股利折现
                  n1 年 g1（= 一致预期窗口长度，不外推）→ n2 年线性衰减 → 永续 g∞
* ``peg``         成长可见且分红率低：``PE = PEG × g``，PEG 按 ROE 上移（OI-005）
* ``unvaluable``  输入不可得或带不可双向使用 → 判无法估值、清空带

口径约定（与 A 股同尺，理由见 §6.8）
----------------------------------
* ``r = 8.5%``：这是**账户级要求回报**（机会成本），不是分市场 WACC。个人体系是账户级
  总规则、覆盖 A股/港股/美股，同一笔钱投美股就不投 A 股，故用同一条门槛线——这正是
  §6.8「不降低门槛」与「同一把尺子」的含义。
* ``g∞ = 3%``、``n1 = 3``（一致预期窗口长度，v1.56 起不外推）、``n2 = 5``。
* **分红率对美股用「股息 + 净回购」口径**：回购在无再投资需求的公司里与分红等价，只看
  股息会把苹果（股息率 12.1%、含回购 94.7%）这类公司的可分配现金严重低估。
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERSEAS_CSV = ROOT / "data/processed/overseas_watchlist_valuation.csv"
COMPANIES_DIR = ROOT / "data/companies"

R_DEFAULT = 0.085          # 账户级要求回报
G_TERMINAL = 0.03          # 永续增长
N_HIGH = 3                 # 高增长年数 = 一致预期窗口长度（v1.56）
N_DECAY = 5                # 线性衰减年数

# 分层系数（§6.5.7 v1.62：带宽只由这里来）。L1-L3 与 A 股同表；L4 是海外清单独有
# （A 股池无 L4 行），按 L1→L3 每档中枢下移 0.05-0.075 的既有梯度外推一档。
TIER_COEF = {
    "L1": (0.90, 1.15),
    "L2": (0.85, 1.05),
    "L3": (0.80, 1.00),
    "L4": (0.75, 0.95),
}


def peg_from_roe(roe: float) -> tuple[float, str]:
    """PEG 随 ROE 上移（OI-005 判据的连续化）。

    A 股逐票档案是「按 ROE 给 PEG 并写明理由」的人工判断（恒生电子 1.0／德赛西威 1.2／
    金山办公 1.25／同花顺 1.5）。海外清单要可复算，故把同一方向固化成分档，取值落在
    A 股既有判例的同一区间内，不新增更宽的取值。

    理由与 OI-005 同源：PEG 假设 PE 随 g 线性缩放，完全不含资本效率；ROE 越高，价值中
    来自存量特许经营权的比重越大，同样的 g 值更多钱。
    """
    if roe >= 0.40:
        return 1.50, f"ROE {roe:.1%} ≥40%，存量特许经营权占价值比重最高，PEG 取判例上限 1.5"
    if roe >= 0.25:
        return 1.35, f"ROE {roe:.1%} 落在 25-40%，PEG 取 1.35（介于金山办公 1.25 与同花顺 1.5 之间）"
    if roe >= 0.15:
        return 1.20, f"ROE {roe:.1%} 落在 15-25%，PEG 取 1.2（德赛西威判例同档）"
    return 1.00, f"ROE {roe:.1%} <15%，资本效率不支持成长溢价，PEG 取判例下限 1.0"


def implied_pe(payout: float, r: float, g: float) -> float:
    """戈登：PE = 分红率/(r − g)。仅在 g < r 时有意义。"""
    if g >= r:
        raise ValueError(f"g={g:.1%} ≥ r={r:.1%}，戈登失效，应改走 ddm3")
    return payout / (r - g)


def ddm3_value(eps0: float, payout1: float, payout_terminal: float, g1: float,
               r: float = R_DEFAULT, g_inf: float = G_TERMINAL,
               n1: int = N_HIGH, n2: int = N_DECAY) -> float:
    """三阶段股利折现现值（海天味业判例同式）。

    n1 年按 g1 增长 → 其后 n2 年 g 线性衰减到 g_inf → 永续。
    高增长段用建仓期分红率，终值段用 ``1 − g∞/ROE`` 推出的分红率。
    """
    pv = 0.0
    eps = eps0
    for t in range(1, n1 + 1):
        eps *= (1 + g1)
        pv += eps * payout1 / (1 + r) ** t
    g = g1
    step = (g1 - g_inf) / (n2 + 1)
    for t in range(n1 + 1, n1 + n2 + 1):
        g -= step
        eps *= (1 + g)
        frac = (t - n1) / n2                       # 分红率同步线性抬到终值水平
        payout_t = payout1 + (payout_terminal - payout1) * frac
        pv += eps * payout_t / (1 + r) ** t
    eps_term = eps * (1 + g_inf)
    tv = eps_term * payout_terminal / (r - g_inf)
    pv += tv / (1 + r) ** (n1 + n2)
    return pv


@dataclass
class Company:
    code: str
    name: str
    tier: str
    path: str                       # implied_pe | ddm3 | peg | unvaluable
    anchor_eps: float = 0.0         # 每股锚（交易货币）
    anchor_note: str = ""
    g: float = 0.0                  # 一致预期增速
    g_note: str = ""
    roe: float = 0.0
    roe_note: str = ""
    payout: float = 0.0             # 股息+净回购／归母
    payout_note: str = ""
    r: float = R_DEFAULT
    why_generic_fails: str = ""
    unvaluable_reason: str = ""
    key_metrics: str = ""
    review_triggers: str = ""
    cross_check: str = ""
    # 参考分（§5.7.4）
    q1: int = 0
    q2: int = 0
    q3: int = 0
    q4: int = 0
    deduction: int = 0
    q_reason: str = ""
    flags: str = ""

    def band(self) -> tuple[float | None, float | None, str, str]:
        """返回 (带下沿, 带上沿, 方法一句话, 完整推导)。"""
        if self.path == "unvaluable":
            return None, None, "无法估值", self.unvaluable_reason
        lo_c, hi_c = TIER_COEF[self.tier]
        if self.path == "peg":
            peg, peg_why = peg_from_roe(self.roe)
            pe = peg * self.g * 100
            fair = self.anchor_eps * pe
            method = f"PEG×ROE修正：PEG {peg} × 增速 {self.g:.1%} → PE {pe:.1f}x"
            deriv = (
                f"锚 = {self.anchor_note}（每股 {self.anchor_eps:.2f}）；"
                f"增速 {self.g:.1%}（{self.g_note}）；{peg_why}；"
                f"PE = {peg} × {self.g * 100:.0f} = {pe:.1f}x；"
                f"合理价 = {self.anchor_eps:.2f} × {pe:.1f} = {fair:.2f}，"
                f"× 分层系数 [{lo_c}, {hi_c}]（{self.tier}）= {fair * lo_c:.2f}~{fair * hi_c:.2f}。"
                f"**通用口径为何不成立**：{self.why_generic_fails}。{self.cross_check}"
            )
        elif self.path == "implied_pe":
            # 分红率用「可持续口径」= 1 − g/ROE，而不是当期实际派息率。理由：戈登式里的
            # 分红率是**稳态可分配比例**；处在投入期的公司当期派息率被资本开支压低，直接
            # 代入会把 PE 系统性打到荒谬的低位（阿里当期派息率约 25% 代入得 PE 7x，
            # 而其 ROE 与 g 隐含的可持续派息率是 50%、PE 14x）。终值期分红率 §6.5.7 本就
            # 规定用 `1 − g∞/ROE`，此处只是把同一条口径用在稳态段。
            payout = self.payout if self.payout else (1 - self.g / self.roe)
            pe = implied_pe(payout, self.r, self.g)
            fair = self.anchor_eps * pe
            src = self.payout_note if self.payout else f"可持续口径 1 − g/ROE = 1 − {self.g:.1%}/{self.roe:.1%}"
            method = f"派息折现隐含PE：分红率/(r−g) = {payout:.0%}/({self.r:.1%}−{self.g:.1%}) = {pe:.1f}x"
            deriv = (
                f"锚 = {self.anchor_note}（每股 {self.anchor_eps:.2f}）；"
                f"分红率 {payout:.0%}（{src}）；可持续增长 {self.g:.1%}（{self.g_note}）；"
                f"ROE {self.roe:.1%}（{self.roe_note}）；"
                f"r = {self.r:.1%}（账户级要求回报）→ PE = {payout:.2f}/({self.r:.3f}−{self.g:.3f}) = {pe:.1f}x；"
                f"合理价 = {self.anchor_eps:.2f} × {pe:.1f} = {fair:.2f}，"
                f"× 分层系数 [{lo_c}, {hi_c}]（{self.tier}）= {fair * lo_c:.2f}~{fair * hi_c:.2f}。"
                f"**通用口径为何不成立**：{self.why_generic_fails}。{self.cross_check}"
            )
        elif self.path == "ddm3":
            # 与 implied_pe 同理：未派息/派息被投入期压低的公司，高增长段也用可持续口径，
            # 否则前 n1 年的现金流被算成 0，等于假设这几年的利润凭空消失（拼多多判例）。
            payout1 = self.payout if self.payout else (1 - self.g / self.roe)
            payout_t = 1 - G_TERMINAL / self.roe if self.roe > G_TERMINAL else payout1
            payout_t = max(min(payout_t, 0.98), payout1)
            fair = ddm3_value(self.anchor_eps, payout1, payout_t, self.g, self.r)
            # 现值锚不叠加安全边际（海天味业判例）：DDM 已折现，系数收窄到 [0.90,1.10]
            lo_c, hi_c = (0.90, 1.10)
            pe_implied = fair / self.anchor_eps
            method = (f"三阶段DDM：{N_HIGH}年@{self.g:.1%} → {N_DECAY}年线性衰减 → 永续 {G_TERMINAL:.0%}，"
                      f"r={self.r:.1%}")
            psrc = self.payout_note if self.payout else f"可持续口径 1 − g/ROE = 1 − {self.g:.1%}/{self.roe:.1%}"
            deriv = (
                f"E0 = {self.anchor_note}（每股 {self.anchor_eps:.2f}）；"
                f"分红率 {payout1:.0%}（{psrc}）；ROE {self.roe:.1%}（{self.roe_note}）；"
                f"终值期分红率 = 1 − {G_TERMINAL:.0%}/{self.roe:.1%} = {payout_t:.1%}；"
                f"g1 = {self.g:.1%}（{self.g_note}，取一致预期窗口 {N_HIGH} 年不外推）；"
                f"现值 = {fair:.2f}（隐含 PE {pe_implied:.1f}x），"
                f"× [{lo_c}, {hi_c}]（现值锚不叠加安全边际）= {fair * lo_c:.2f}~{fair * hi_c:.2f}。"
                f"**通用口径为何不成立**：{self.why_generic_fails}。{self.cross_check}"
            )
        else:
            raise ValueError(f"未知路径 {self.path}")
        return round(fair * lo_c, 2), round(fair * hi_c, 2), method, deriv

    def score(self) -> float:
        return round(self.q1 * 0.25 + self.q2 * 0.40 + self.q3 * 0.20 + self.q4 * 0.15
                     - self.deduction, 2)


COMPANIES: list[Company] = []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只打印计算结果，不写文件")
    parser.add_argument("--as-of", default="2026-08-03")
    args = parser.parse_args()
    from overseas_dossier_inputs import COMPANIES as INPUTS  # noqa: E402
    print(f"{'代码':<9}{'名称':<16}{'档':<4}{'路径':<12}{'带下':>10}{'带上':>10}{'宽度':>7}{'参考分':>8}")
    widths = []
    for c in INPUTS:
        lo, hi, method, _ = c.band()
        w = hi / lo if lo and hi else None
        if w:
            widths.append(w)
        print(f"{c.code:<9}{c.name:<16}{c.tier:<4}{c.path:<12}"
              f"{(f'{lo:.2f}' if lo else '—'):>10}{(f'{hi:.2f}' if hi else '—'):>10}"
              f"{(f'{w:.3f}' if w else '—'):>7}{c.score():>8.2f}")
    if widths:
        print(f"\n带宽自检：{len(widths)} 条，最大 {max(widths):.3f}，"
              f"A 股池最大 1.278 —— {'✅ 未超' if max(widths) <= 1.278 else '❌ 超出'}")
    if not args.check:
        materialize(args.as_of)




# ---------------------------------------------------------------- 物化
NEW_COLS = [
    "band_derivation", "band_method", "band_derivation_text", "key_metrics",
    "review_triggers", "dossier_status", "dossier_dir", "decided_by",
    "q1_business_model_score", "q2_moat_score", "q3_capital_allocation_score",
    "q4_management_score", "credibility_deduction", "quality_score",
    "flags", "score_reason", "score_version", "scored_at",
]


def materialize(as_of: str) -> None:
    """把计算结果写回 §6.8 单文件（不新建分层表——§6.8「单文件承载」）。"""
    from overseas_dossier_inputs import COMPANIES as INPUTS

    rows = list(csv.DictReader(OVERSEAS_CSV.open(encoding="utf-8")))
    by_code = {c.code: c for c in INPUTS}
    assert set(by_code) == {r["security_code"] for r in rows}, "清单与输入不同集"

    fields = list(rows[0].keys()) + [c for c in NEW_COLS if c not in rows[0]]
    for row in rows:
        c = by_code[row["security_code"]]
        lo, hi, method, deriv = c.band()
        unval = lo is None
        row["fair_price_low"] = "" if unval else f"{lo}"
        row["fair_price_high"] = "" if unval else f"{hi}"
        row["valuation_tier"] = "无法估值" if unval else row["valuation_tier"]
        row["fair_price_basis"] = deriv
        row["valuation_method"] = method
        row["band_derivation"] = "unvaluable" if unval else "dossier"
        row["band_method"] = method
        row["band_derivation_text"] = deriv
        row["key_metrics"] = c.key_metrics
        row["tracking_metrics"] = c.key_metrics
        row["review_triggers"] = c.review_triggers
        row["dossier_status"] = "unvaluable_pending_input" if unval else "active"
        row["dossier_dir"] = f"data/companies/{c.code}_{c.name}"
        row["decided_by"] = "模型推导（用户可覆盖）"
        row["valuation_reviewed_at"] = as_of
        row["q1_business_model_score"] = c.q1
        row["q2_moat_score"] = c.q2
        row["q3_capital_allocation_score"] = c.q3
        row["q4_management_score"] = c.q4
        row["credibility_deduction"] = c.deduction
        row["quality_score"] = f"{c.score():.2f}"
        row["flags"] = c.flags
        row["score_reason"] = c.q_reason
        row["score_version"] = "v0.1-overseas"
        row["scored_at"] = as_of

    with OVERSEAS_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    for c in INPUTS:
        d = COMPANIES_DIR / f"{c.code}_{c.name}"
        d.mkdir(parents=True, exist_ok=True)
        lo, hi, method, deriv = c.band()
        band_txt = "**无法估值**（带已清空）" if lo is None else f"**{lo} ~ {hi}**"
        (d / "README.md").write_text(
            f"# {c.name}（{c.code}）估值档案\n\n"
            f"> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答"
            f"「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。\n\n"
            f"- 质量档：**{c.tier}**｜参考分 **{c.score():.2f}**（Q1 {c.q1} / Q2 {c.q2} / "
            f"Q3 {c.q3} / Q4 {c.q4}，可信度扣分 {c.deduction}）\n"
            f"- 旗标：{c.flags}\n\n## 合理价区间\n\n{band_txt}\n\n"
            f"**方法**：{method}\n\n**推导**：{deriv}\n\n"
            f"## 参考分理由（§5.7.4）\n\n{c.q_reason}\n\n"
            f"## 跟踪指标\n\n{c.key_metrics}\n\n## 复核触发\n\n{c.review_triggers}\n\n"
            f"---\n定档人：模型推导（用户可覆盖）｜复核日：{as_of}\n",
            encoding="utf-8")
    print(f"已写入 {OVERSEAS_CSV.name}（{len(rows)} 行，新增 {len(NEW_COLS)} 列）"
          f"，建目录 {len(INPUTS)} 个")


if __name__ == "__main__":
    main()

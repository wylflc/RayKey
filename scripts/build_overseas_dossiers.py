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
下面各条推导路径之一算出，不再有「先有档位、后凑带」的空间。

方法路径（每条都由 §6.5 的既有标签映射而来，脚本只是实现它们）
------------------------------------------------
* ``implied_pe``  稳态、g < r：``PE = 分红率/(r − g)``（戈登）
* ``ddm3``        分红率 ≥60%，或 g ≥ r 使戈登失效：三阶段股利折现
                  n1 年 g1（= 一致预期窗口长度，不外推）→ n2 年线性衰减 → 永续 g∞
* ``peg``         成长可见且分红率低：``PE = PEG × g``，PEG 按 ROE 上移（OI-005）
* ``mid_cycle``   周期股处在周期极值：中枢利润 × 戈登稳态 PE（v2.10 新增，见下）
* ``justified_pb`` §6.5.2 J 金融资本型：``PB = (ROE − g)/(COE − g)``，与自身 PB 中位取孰低
                  （v2.15 新增，见下）
* ``unvaluable``  **仅表示建档未完成**（§6.5.5.2）。已建档的公司不得取此路径——
                  通用模型失效是转入逐票差异化推导的触发条件，不是终止条件

v2.10：为什么删掉了「周期假设未决 → 无法估值」
---------------------------------------------
存储三家（美光/三星/SK海力士）原先都判无法估值，理由是「两情景相差 12-18 倍」。
但那两个情景一个假设 AI 需求完全不存在（FY2025 营收 × 10 年净利率中位），一个假设
峰值利润永续（单季净利年化）——**中间地带从未被算过**。``mid_cycle`` 就是把中间地带
算出来：中枢利润 = 中枢营收 × 自身 10 年净利率中位，倍数 = 戈登稳态 PE（用中枢 ROE
推出，g 取永续 3%——商品没有真实的结构性成长）。周期位置这个判断被压缩成**一个**具名
输入 ``mid_cycle_uplift``（中枢营收相对上一轮常态营收的结构性倍数），用户改一个数即可
覆盖全部结论，而不是面对一条没有带的行自己从头判断。

v2.15：为什么加了 justified_pb
------------------------------
海外清单 2026-08-06 新增伯克希尔，是本清单第一家**保险/金融控股**公司。§6.5.0 判定顺序
第 1 条把金融机构一律定为 J（资产负债表本身即经营主体），§6.5.2 J 行的口径是
``bvps × (ROE − g)/(COE − g) × [0.90, 1.10]``，与自身 PB 中位取孰低。此前清单里没有
金融股，脚本因此没有这条路径；加它是**实现一条既有标准**，不是新立标准。

数学上它与 ``implied_pe`` 同源：``PE = (1 − g/ROE)/(r − g)``，两边乘 ``EPS = ROE × BVPS``
即得 ``BVPS × (ROE − g)/(r − g)``。分开写有两个理由：①锚换成 BVPS 后不必先估一个
「归一化 EPS」——伯克希尔的 GAAP 净利含股票组合市值变动，是本清单里噪音最大的一个分子；
②J 的带系数是 [0.90, 1.10]（§6.5.2 J 行），不是分层系数。

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
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# §6.2.1.6 定档阈值只有一处实现，海外清单不另写一份（CLAUDE.md：标准不得重述）。
from build_a_share_core_valuation_pool import effective_valuation_tier  # noqa: E402

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


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def band_position(price: float | None, lo: float | None, hi: float | None) -> str:
    """§6.2.1.6 带位表述：带内X%／低于带底-X%／越带顶+X%。"""
    if price is None or lo is None or hi is None or hi <= lo:
        return "带位不可算"
    if price > hi:
        return f"越带顶+{(price / hi - 1) * 100:.1f}%"
    if price < lo:
        mid = (lo + hi) / 2
        return f"低于带底{(price / lo - 1) * 100:.1f}%（对带中值空间 +{(mid / price - 1) * 100:.1f}%）"
    return f"带内{(price - lo) / (hi - lo) * 100:.0f}%"


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
    path: str                       # implied_pe | ddm3 | peg | mid_cycle | justified_pb | unvaluable
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
    # 证据（事实，不含带算术）。`valuation_reason` 由它 + 本次计算结果拼出，见 materialize()：
    # 旧版把带算术手写进 valuation_reason，重建带时不刷新，21 家里 10 家因此一行两个带。
    evidence: str = ""
    sensitivity: str = ""            # §6.5.5 强制：锚±15% 或关键假设区间对应的档位
    # mid_cycle 专用
    base_revenue: float = 0.0        # 上一轮周期的常态营收（本币十亿/兆，与 mid_margin 同口径）
    mid_cycle_uplift: float = 0.0    # 中枢营收 = base_revenue × 本值（结构性增量，非价格）
    mid_margin: float = 0.0          # 自身 10 年净利率中位
    shares: float = 0.0              # 摊薄股本（与 base_revenue 同单位口径）
    cycle_note: str = ""
    # justified_pb 专用（§6.5.2 J）
    bvps: float = 0.0                # 每股净资产（交易货币）
    bvps_note: str = ""
    pb_median: float = 0.0           # 自身 PB 中位（J primary「取孰低」的另一腿）
    pb_median_note: str = ""
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
        elif self.path == "mid_cycle":
            # 周期股（H）在周期极值：表观 PE 的分母是峰值利润，PEG/DCF 都失效。
            # 锚 = 中枢利润（中枢营收 × 自身 10 年净利率中位），倍数 = 戈登稳态 PE
            # （用中枢 ROE 推出，g = 永续 3%：商品没有真实的结构性成长）。
            # 倍数被推导而非指定（§6.5.7 v1.54）；带宽仍只由分层系数承担（v1.62）。
            payout = 1 - G_TERMINAL / self.roe
            pe = payout / (self.r - G_TERMINAL)
            if self.base_revenue:
                mid_rev = self.base_revenue * self.mid_cycle_uplift
                mid_profit = mid_rev * self.mid_margin
                eps = mid_profit / self.shares
                anchor_txt = (
                    f"中枢营收 = 上轮常态营收 {self.base_revenue:,.4g} × 结构性增量 "
                    f"{self.mid_cycle_uplift:.2f}x = {mid_rev:,.4g}（{self.cycle_note}）；"
                    f"× 自身 10 年净利率中位 {self.mid_margin:.1%} = 中枢利润 {mid_profit:,.4g}；"
                    f"÷ 摊薄股本 {self.shares:,.4g} = 中枢 EPS {eps:,.2f}"
                )
            else:
                eps = self.anchor_eps
                anchor_txt = f"中枢 EPS {eps:,.2f}（{self.anchor_note}）"
            fair = eps * pe
            method = f"中枢利润×戈登稳态PE：中枢EPS {eps:,.2f} × PE {pe:.2f}x"
            deriv = (
                f"{anchor_txt}；中枢 ROE {self.roe:.2%}（{self.roe_note}）→ "
                f"可持续分红率 = 1 − {G_TERMINAL:.0%}/{self.roe:.2%} = {payout:.1%}，"
                f"稳态 PE = {payout:.3f}/({self.r:.1%}−{G_TERMINAL:.0%}) = {pe:.2f}x；"
                f"合理价 = {eps:,.2f} × {pe:.2f} = {fair:,.2f}，"
                f"× 分层系数 [{lo_c}, {hi_c}]（{self.tier}）= {fair * lo_c:,.2f}~{fair * hi_c:,.2f}。"
                f"**通用口径为何不成立**：{self.why_generic_fails}。{self.cross_check}"
            )
        elif self.path == "justified_pb":
            # §6.5.2 J：锚 = 每股净资产，倍数 = 隐含 PB (ROE − g)/(COE − g)，COE 取账户级 r。
            # J primary 明文「与自身 PB 中位取孰低」——这条不是保守裁量，是防止公式在
            # ROE 逼近 r 时把倍数推到与该公司历史区间脱节的位置。
            lo_c, hi_c = (0.90, 1.10)          # §6.5.2 J 行带系数，不用分层系数
            if self.roe <= G_TERMINAL and self.roe <= self.g:
                raise ValueError(f"ROE={self.roe:.2%} ≤ g={self.g:.2%}，隐含 PB 无意义")
            pb_model = (self.roe - self.g) / (self.r - self.g)
            pb = min(pb_model, self.pb_median) if self.pb_median else pb_model
            taken = "模型隐含" if pb == pb_model else f"自身 PB 中位 {self.pb_median}"
            fair = self.bvps * pb
            method = f"隐含PB：(ROE−g)/(COE−g) = ({self.roe:.2%}−{self.g:.1%})/({self.r:.1%}−{self.g:.1%}) = {pb_model:.3f}x，取孰低后 {pb:.3f}x"
            deriv = (
                f"锚 = 每股净资产 {self.bvps:,.2f}（{self.bvps_note}）；"
                f"ROE {self.roe:.2%}（{self.roe_note}）；可持续增长 {self.g:.1%}（{self.g_note}）；"
                f"COE = r = {self.r:.1%}（账户级要求回报，§6.8 口径1）→ "
                f"隐含 PB = ({self.roe:.4f}−{self.g:.3f})/({self.r:.3f}−{self.g:.3f}) = {pb_model:.3f}x；"
                f"自身 PB 中位 {self.pb_median}（{self.pb_median_note}）→ §6.5.2 J「取孰低」得 {pb:.3f}x（{taken}）；"
                f"合理价 = {self.bvps:,.2f} × {pb:.3f} = {fair:,.2f}，"
                f"× [{lo_c}, {hi_c}]（§6.5.2 J 行带系数）= {fair * lo_c:,.2f}~{fair * hi_c:,.2f}。"
                f"**通用口径为何不成立**：{self.why_generic_fails}。{self.cross_check}"
            )
        else:
            raise ValueError(f"未知路径 {self.path}")
        if self.sensitivity:
            deriv += f" **敏感度（§6.5.5）**：{self.sensitivity}"
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
    reviewed: dict[str, str] = {}
    for row in rows:
        c = by_code[row["security_code"]]
        lo, hi, method, deriv = c.band()
        unval = lo is None
        # 重跑不等于复核（v2.15）：脚本每次运行都会把全清单重算一遍，但只有**结论真的变了**
        # 的行才算当日做过一次复核。旧版对每一行无条件写 `valuation_reviewed_at = as_of`，
        # 于是「今天只加了 5 家」会被记成「26 家全部于今天复核」——既是对复核日的虚报，
        # 又让 §6.8 的日志门槛（只记 valuation_reviewed_at == as_of 的行）一次性放行全表。
        before = (row.get("fair_price_low", ""), row.get("fair_price_high", ""),
                  row.get("valuation_tier", ""), row.get("quality_score", ""))
        after = ("" if unval else f"{lo}", "" if unval else f"{hi}",
                 "无法估值" if unval else (
                     effective_valuation_tier(to_float(row.get("valuation_price")), lo, hi)
                     or row.get("valuation_tier", "")),
                 f"{c.score():.2f}")
        changed = before != after
        reviewed_at = as_of if changed else (row.get("valuation_reviewed_at") or as_of)
        reviewed[c.code] = reviewed_at

        row["fair_price_low"], row["fair_price_high"] = after[0], after[1]
        # 审定档由本次的带与复核时点价重算（§6.2.1.6），不沿用旧值：带一改而档不改，
        # 读表的人会拿新带去核对一个用旧带算出来的档。
        price = to_float(row.get("valuation_price"))
        row["valuation_tier"] = after[2]
        # `valuation_reason` = 证据（输入）+ 本次定档（生成）。带算术只在这里出现一次，
        # 因此不可能与 fair_price_low/high 脱节——旧版手写带，10/21 行已脱节。
        row["valuation_reason"] = (
            c.evidence + f"｜**本次定档（{reviewed_at}）**：{method}；带 "
            + ("—（建档未完成）" if unval else f"{lo:,.2f}~{hi:,.2f}")
            + f"；复核时点价 {row.get('valuation_price') or 'NA'}"
            f"（{row.get('valuation_price_as_of') or 'NA'}）→ **{row['valuation_tier']}**"
            + (f"，{band_position(price, lo, hi)}" if not unval else "") + "。"
        )
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
        row["valuation_reviewed_at"] = reviewed_at
        row["q1_business_model_score"] = c.q1
        row["q2_moat_score"] = c.q2
        row["q3_capital_allocation_score"] = c.q3
        row["q4_management_score"] = c.q4
        row["credibility_deduction"] = c.deduction
        row["quality_score"] = f"{c.score():.2f}"
        row["flags"] = c.flags
        row["score_reason"] = c.q_reason
        row["score_version"] = "v0.1-overseas"
        row["scored_at"] = reviewed_at

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
            f"---\n定档人：模型推导（用户可覆盖）｜复核日：{reviewed.get(c.code, as_of)}\n",
            encoding="utf-8")
    print(f"已写入 {OVERSEAS_CSV.name}（{len(rows)} 行，新增 {len(NEW_COLS)} 列）"
          f"，建目录 {len(INPUTS)} 个")


if __name__ == "__main__":
    main()

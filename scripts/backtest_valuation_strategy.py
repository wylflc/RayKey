#!/usr/bin/env python3
"""估值 × 走势规则的回测引擎（工作流 §12），含逐周期与组合层指标。

**现行基准参数只在 `scripts/sweep_backtest_configs.py` 的 `BASE`（工作流 §9.3.1.2）**——本文件的
argparse 缺省值多为研究口径或历史口径，单独运行本脚本时必须显式给全参数，不得把缺省值当作现行规则。
回测宇宙固定读 `data/processed/pit_attention/panel_moat_bank_v6b.csv`，逐日估值状态固定读
`data/processed/a_share_daily_states_adopted.csv`（§6.7 第 3 步产物）。

**分红送转必须落到账上，否则回测直接是错的**：持仓穿越 10 转 10 而不调股数，会凭空亏
一半；现金分红不入账则系统性低估收益。本脚本在除权日按
`股数 ×= (1 + 送转比)`、`现金 += 除权前股数 × 每股现金红利` 处理。

**三处结构性偏误，读数前必须知道**（v2.88 起把原「幸存者偏差 + 选样前视」拆开——
两者是不同的偏误，一个可测可修、一个在本仓库根本测不到）：

1. **选样前视（可测，给 `--universe-file` 即可压掉）**。回测标的是**今日的核心池成员**，而池由 2026 年的分层与建档选出。实测 2000-01-01 时这 261 只中**仅 34 只在市**
   （13%）、2005 年也只有 67 只（26%）。**代价已量化**：2010-05~2026-08 同区间，改用
   `data/archive/pit-judgment-2026-08/universe_panel_yearly.csv` 逐年时点名单后年化
   **23.68% → 13.41%（−10.27pp）**，其中「换池子」−4.99pp、「加时点」−5.28pp
   （回测日志 §12.25.3）。**不给 `--universe-file` 的读数一律含此前视。**
2. **幸存者偏差（数据侧已补，判定侧见协议）**。2026-08-11 起行情库含 344 只退市股（`data/raw/a_share_delisted_roster.csv`，
   深交所名册＋腾讯探测）、逐季财务 339 只、逐日状态 297 只；时点判定队列建在「现存＋退市」全口径上（168 只退市股有财务签名、
   入队判毕，1 只入选面板）。本脚本对退市持仓按协议 §8「末个交易日收盘价平仓」：名册内代码在末个交易日之后的第一个交易日按
   最后成交价整仓清出（`退市·末日收盘平仓`），不再冻结在账上。残余偏差（三表缺失→退市股只能走权益口径；判定者后视）见判定协议「退市股第二遍盲判」一节；OI-040 已于 2026-08-21 按用户裁定归档（v6b 仅含 1 只退市股、影响噪声级）。
3. **交易成本缺省不计**，须显式打开。`--fee-preset user` 即用户券商口径（佣金万一、最低
   5 元、印花税 0.05% 单边卖出、过户费 0.001% 双边）；`--fee-stamp-mode historical` 另按
   成交日取历史印花税率（2007-05-30~2008-04-23 曾达 0.3% 双边）。**不打开时高换手参数被系
   统性高估**，故 x、换仓阈值一类改变换手的参数必须开着成本比。

用法::

    python3 scripts/backtest_valuation_strategy.py --x 1 0.5 0.1 --since 2016-01-01
    python3 scripts/backtest_valuation_strategy.py --strategy trend --x 1
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import math
import statistics
import sys
import collections
from collections import defaultdict
from operator import mul as _mul
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DAILY_STATES = ROOT / "data/processed/a_share_daily_states_adopted.csv"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
RESEARCH_DIR = ROOT / "data/raw/research_reports"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
DELISTED_ROSTER = ROOT / "data/raw/a_share_delisted_roster.csv"   # OI-040：退市名册（代码 → 末个交易日）
DELISTED_LAST: dict[str, str] = {}


def load_delisted() -> dict[str, str]:
    """{代码: 末个交易日}。名册缺失即空——此时退市持仓只能冻结在最后成交价上（旧行为），并在结尾告警。"""
    if not DELISTED_ROSTER.exists():
        return {}
    with DELISTED_ROSTER.open(newline="", encoding="utf-8-sig") as handle:
        return {(r.get("security_code") or "").zfill(6): (r.get("last_trade_date") or "")
                for r in csv.DictReader(handle) if (r.get("last_trade_date") or "")}
RATES = ROOT / "data/reference/cost_of_equity_inputs.csv"
BENCHMARK = ROOT / "data/raw/ohlcv/INDEX_000300.csv"
OUT_DIR = ROOT / "data/processed/backtest"

INITIAL_CAPITAL = 3_000_000.0
MAX_POSITIONS = 10
TRADING_DAYS = 244

# ------------------------------------------------------------------ 交易成本
# 缺省全零 → 与历史全部回测逐位可复现。开启后买卖两侧都从现金里扣，不改成交股数。
# 印花税历史沿革（`--fee-stamp-mode historical`）：早年双边征收且税率高得多，
# 2007-05-30~2008-04-23 的 0.3% 双边对高换手配置是致命的，故必须能单独检验。
STAMP_HISTORY = [                     # (生效日, 税率, 是否双边)
    ("1900-01-01", 0.0040, True),
    ("2001-11-16", 0.0020, True),
    ("2005-01-24", 0.0010, True),
    ("2007-05-30", 0.0030, True),
    ("2008-04-24", 0.0010, True),
    ("2008-09-19", 0.0010, False),    # 起改单边征收
    ("2023-08-28", 0.0005, False),
]

FEES = {"commission": 0.0, "min_fee": 0.0, "transfer": 0.0,
        "stamp": 0.0, "stamp_mode": "flat", "paid": 0.0}


def _stamp_rate(day: str, side: str) -> float:
    """按成交日取印花税率。`side` 为 buy/sell。"""
    if FEES["stamp_mode"] != "historical":
        return FEES["stamp"] if side == "sell" else 0.0
    rate, both = 0.0, False
    for start, r, b in STAMP_HISTORY:
        if day >= start:
            rate, both = r, b
    return rate if (side == "sell" or both) else 0.0


def trade_fee(amount: float, day: str, side: str) -> float:
    """一笔成交的全部费用：佣金（有最低额）＋过户费＋印花税。金额为零则不收费。"""
    if amount <= 0 or not FEES["commission"] and not FEES["min_fee"] \
            and not FEES["transfer"] and FEES["stamp_mode"] == "flat" and not FEES["stamp"]:
        return 0.0
    fee = max(amount * FEES["commission"], FEES["min_fee"])
    fee += amount * FEES["transfer"]
    fee += amount * _stamp_rate(day, side)
    FEES["paid"] += fee
    return fee

# 安全边际按档位（风险惩罚归决策层，不塞进 r；研究开关）。**只作用于买入线。**
MOS_BY_TIER = {"L1": 0.10, "L2": 0.20, "L3": 0.30}
DEFAULT_TIER = "L2"


def _num(text: str | None) -> float | None:
    try:
        return float((text or "").strip())
    except ValueError:
        return None


# ------------------------------------------------------------------ 载入
def load_states(path: Path | None = None,
                codes: set[str] | None = None) -> dict[str, list[tuple[str, float, float, float]]]:
    """{日期: [(代码, 收盘, 内在价值, P/V), …]}——已按送转折算过的口径。

    `codes` 限定载入范围。全市场建带后逐日状态上千万行，全量驻留内存要好几 GB；
    给了时点股票库就只需要它的历年并集，其余行读了也用不上。
    """
    out: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    with (path or DAILY_STATES).open(newline="", encoding="utf-8") as handle:
        # 用 `csv.reader` + 列下标，不用 `DictReader`：后者每行都要新建一个 dict，
        # 逐日状态动辄六十万行，一次长跑光这一处就是 1.5 秒。**列名仍从表头取**，
        # 不写死顺序——建带脚本改过列序也不会读错。
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return out
        i_code, i_date = header.index("security_code"), header.index("date")
        i_close, i_iv = header.index("close"), header.index("intrinsic_value")
        i_ratio = header.index("valuation_ratio")
        append = out.__getitem__
        for row in reader:
            code = row[i_code]
            if codes is not None and code not in codes:
                continue
            append(row[i_date]).append((code, float(row[i_close]),
                                        float(row[i_iv]), float(row[i_ratio])))
    return out


class ResearchGate:
    """卖方研报的**预期方向门槛**（用户 2026-08-09：「只有近期研报预期在增长或几乎不变的公司才能买入」）。

    数据边界（决定了这个门槛能测多长，见 `fetch_a_share_research_reports.py` 文件头）
    ------------------------------------------------------------------------------
    * 研报全市场覆盖**始于 2017-01**；
    * **预测 EPS 字段只有 2024 年之后的研报才有值**，2017-2023 全空。

    因此两个口径的可测窗口完全不同，**必须分开报**：

    ``rating``  评级方向。近 `window` 天研报的 `emRatingValue` 均值 vs 前一个 `window`
                天的均值（0=中性 1=持有 2=增持 3=买入）。均值下滑超过 `tol` 即拦截。
                **2018 起可测**（需前置一个窗口做基期）。
    ``nodown``  近 `window` 天内出现过评级下调（`rating_change==1`）即拦截。比 ``rating``
                更硬，只认「有机构明确下调」这一件事，不受覆盖机构结构变化影响。
    ``target``  目标价方向。近窗口目标价中位数 vs 前窗口中位数，跌幅超 `tol` 即拦截。
                填充率 36% 且**贯穿 2017-2026**，是全窗口唯一可用的「预期水平」代理
                （预测 EPS 只有 2024+）。**必须做送转折算**——10 转 10 会把目标价腰斩，
                不折算就会被读成一次 −50% 的下修。折算办法见 `load_research`。
    ``eps``     前瞻 EPS 修正。`fwd12 = TY×(1−f) + NY×f`，`f` 为发布日在当年的进度——
                TY 指**发布当年**（2025-11 的茅台研报 TY≈76.5／NY≈81，12 月被下修到 72.7），
                跨年时按进度加权可保持连续，避免 12 月→1 月的财年标签跳变被误读成修正。
                取窗口内中位数比前窗口中位数，跌幅超 `tol` 即拦截。**仅 2025 起可测**。

    `missing` 决定「无研报覆盖」怎么办。**这一项会改变门槛的性质**：`block` 会把它变成
    一个隐含的规模／关注度过滤器（小盘股常年零覆盖），`pass` 才是纯粹的预期方向门槛。
    默认 `pass`——只在**有证据表明预期被下修**时才拦，没有证据不等于坏消息。
    """

    def __init__(self, ratings, downgrades, forecasts, targets=None, window: int = 180,
                 tol: float = 0.0, missing: str = "pass", permute: int = 0):
        self.ratings, self.downgrades, self.forecasts = ratings, downgrades, forecasts
        self.targets = targets or {}
        self.window, self.tol, self.missing = window, tol, missing
        self.blocked = collections.Counter()
        # 安慰剂：把每只股票的研报序列**按代码序错位 `permute` 位**。拦截强度、时间分布、
        # 覆盖稀疏性全都保留，唯独抹掉「这条信号说的是这家公司」。若安慰剂同样能提高收益，
        # 则增益来自「少买／被动持币」的机械效果，与研报内容无关。
        self.permute = {}
        if permute:
            codes = sorted(set(self.ratings) | set(self.targets) | set(self.downgrades))
            self.permute = {c: codes[(i + permute) % len(codes)] for i, c in enumerate(codes)} if codes else {}

    def _key(self, code: str) -> str:
        return self.permute.get(code, code)

    @staticmethod
    def _shift(day: str, days: int) -> str:
        return (date.fromisoformat(day) - timedelta(days=days)).isoformat()

    @staticmethod
    def _slice(series, lo: str, hi: str):
        """`series` 为按日期升序的 [(date, value), …]；取 **lo < date < hi，两端都开**。

        右端开区间是刻意的：研报的 `publishDate` 只到日，无从判断它在当日开盘前还是收盘后
        发布，而回测按收盘价成交。把当日研报排除掉，最多损失一天新鲜度，却能让「不含未来」
        这件事**无需辩护**。
        """
        i = bisect.bisect_right(series, (lo, float("inf")))
        j = bisect.bisect_left(series, (hi, float("-inf")))
        return [v for _, v in series[i:j]]

    def allows(self, mode: str, code: str, day: str) -> bool:
        mid, start = self._shift(day, self.window), self._shift(day, 2 * self.window)
        code = self._key(code)
        if mode in ("rating", "both"):
            series = self.ratings.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent:
                if self.missing == "block":
                    self.blocked["无覆盖"] += 1
                    return False
            elif prior and (statistics.fmean(recent) - statistics.fmean(prior)) < -self.tol:
                self.blocked["评级下滑"] += 1
                return False
        if mode == "nodown":
            series = self.downgrades.get(code)
            if series and self._slice(series, mid, day):
                self.blocked["评级下调"] += 1
                return False
            if self.missing == "block" and not (self.ratings.get(code)
                                                and self._slice(self.ratings[code], mid, day)):
                self.blocked["无覆盖"] += 1
                return False
        if mode in ("target", "both"):
            series = self.targets.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent or not prior:
                if self.missing == "block":
                    self.blocked["无目标价"] += 1
                    return False
            elif statistics.median(prior) > 0 and \
                    statistics.median(recent) / statistics.median(prior) - 1 < -self.tol:
                self.blocked["目标价下修"] += 1
                return False
        if mode == "eps":
            series = self.forecasts.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent or not prior:
                if self.missing == "block":
                    self.blocked["无预测"] += 1
                    return False
            elif statistics.median(prior) > 0 and \
                    statistics.median(recent) / statistics.median(prior) - 1 < -self.tol:
                self.blocked["预测下修"] += 1
                return False
        return True


def load_research(codes: set[str] | None = None, directory: Path | None = None, actions=None):
    """读研报原始档，装配成四张按日期升序的时点表。**只保留 publish_date，绝不引用当前一致预期。**

    目标价的送转折算：令 `C(d) = ∏(1+ratio)`（该股在 d 之前所有除权的送转比例连乘），
    则 `aim × C(d)` 在同一只股票内部是**同一把尺子**——发生 10 转 10 时，除权前定的
    目标价 100 与除权后定的 50 都会折成同一个数，不再产生假的 −50% 下修。
    """
    factors: dict[str, list[tuple[str, float]]] = {}
    for code, events in (actions or {}).items():
        cumulative, series = 1.0, []
        for day in sorted(events):
            cumulative *= (1.0 + events[day][1])
            series.append((day, cumulative))
        if series:
            factors[code] = series

    def factor_at(code: str, day: str) -> float:
        series = factors.get(code)
        if not series:
            return 1.0
        i = bisect.bisect_left(series, (day, float("-inf")))
        return series[i - 1][1] if i else 1.0

    ratings: dict[str, list[tuple[str, float]]] = defaultdict(list)
    downgrades: dict[str, list[tuple[str, float]]] = defaultdict(list)
    forecasts: dict[str, list[tuple[str, float]]] = defaultdict(list)
    targets: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for path in sorted((directory or RESEARCH_DIR).glob("reports_*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code, day = row["security_code"], row["publish_date"]
                if not code or len(day) != 10 or (codes is not None and code not in codes):
                    continue
                value = _num(row.get("rating_value"))
                if value is not None:
                    ratings[code].append((day, value))
                if (row.get("rating_change") or "").strip() == "1":
                    downgrades[code].append((day, 1.0))
                this_year, next_year = _num(row.get("predict_this_year_eps")), _num(row.get("predict_next_year_eps"))
                if this_year and next_year and this_year > 0 and next_year > 0:
                    fraction = (date.fromisoformat(day).timetuple().tm_yday - 1) / 365.0
                    forecasts[code].append((day, this_year * (1 - fraction) + next_year * fraction))
                aim = _num(row.get("aim_price"))
                if aim and aim > 0:
                    targets[code].append((day, aim * factor_at(code, day)))
    for table in (ratings, downgrades, forecasts, targets):
        for series in table.values():
            series.sort()
    return dict(ratings), dict(downgrades), dict(forecasts), dict(targets)


def load_prices(codes: set[str] | None = None) -> dict[str, dict[str, float]]:
    """持仓在**没有带**的日子也要按市价盯市，故行情单独载入。

    `codes` 限定范围。全市场 5,000+ 只行情读成 dict 要 3~4 GB——**在 8 GB 机器上，
    与逐日状态叠加会把系统拖死**（2026-08-08 实测：4 个回测并行导致两次黑屏）。
    只有出现在逐日状态里的代码才可能被买或被盯市，其余读了也用不上。
    """
    return _load_ohlcv_column("close", codes)


def load_opens(codes: set[str] | None = None) -> dict[str, dict[str, float]]:
    """逐票开盘价。仅 `--exec-delay 1 --exec-price open` 用得到，故按需载入。"""
    return _load_ohlcv_column("open", codes)


def _load_ohlcv_column(column: str, codes: set[str] | None) -> dict[str, dict[str, float]]:
    """逐票行情的某一列。收盘与开盘只差列名，合成一处，避免两边各改一遍。

    与 `load_states` 同理走 `csv.reader` + 列下标：一次长跑要读近百万行，
    `DictReader` 的建 dict 开销在这里同样是秒级的。
    """
    out: dict[str, dict[str, float]] = {}
    for path in sorted(OHLCV_DIR.glob("*.csv")):
        if path.stem.startswith("INDEX_") or (codes is not None and path.stem not in codes):
            continue
        series = {}
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None or column not in header or "date" not in header:
                out[path.stem] = series
                continue
            i_val, i_date = header.index(column), header.index("date")
            for row in reader:
                value = _num(row[i_val]) if i_val < len(row) else None
                if value and value > 0:
                    series[row[i_date]] = value
        out[path.stem] = series
    return out


def load_actions() -> dict[str, dict[str, tuple[float, float]]]:
    """{代码: {除权日: (每股现金红利, 送转比)}}。同日多条相加/连乘。"""
    out: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    if not ACTIONS.exists():
        return out
    with ACTIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = (row.get("ex_dividend_date") or "").strip()
            if not day:
                continue
            cash = _num(row.get("cash_per_share")) or 0.0
            ratio = _num(row.get("share_ratio")) or 0.0
            old_cash, old_ratio = out[row["security_code"]].get(day, (0.0, 0.0))
            out[row["security_code"]][day] = (old_cash + cash, (1 + old_ratio) * (1 + ratio) - 1)
    return out


def load_names() -> dict[str, str]:
    path = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r["security_name"] for r in csv.DictReader(handle)}


def load_tiers() -> dict[str, str]:
    """{代码: 档位}——买入线按档位分档时用（--use-mos）。"""
    path = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r["quality_tier"] for r in csv.DictReader(handle)}


def parse_tier_scale(text: str) -> dict[str, float] | None:
    """`"L1=1.25,L3=0.875"` → `{"L1": 1.25, "L3": 0.875}`；空串 → None（原行为）。"""
    text = (text or "").strip()
    if not text:
        return None
    out: dict[str, float] = {}
    for part in text.split(","):
        tier, _, value = part.partition("=")
        if tier.strip() and value.strip():
            out[tier.strip()] = float(value)
    return out or None


def load_universe(path: Path) -> list[tuple[str, set[str]]]:
    """时点股票库：把成员区间展开为 ``[(变更日, {在册代码})]``。

    CSV 是一行一个成员区间，不是每个 ``effective_from`` 一份完整快照。成员从
    ``effective_from`` 起生效、到 ``effective_to`` 当日仍有效；空结束日表示开放区间。
    相邻区间可能共享边界日，故用引用计数而不是简单集合增删，避免边界日后的误删。

    **生效日不可提前**——`Y` 年的年报要到 `Y+1` 年 4 月底才披露完，见
    `build_point_in_time_universe.py`。
    """
    changes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            code = row["security_code"]
            changes[row["effective_from"]][code] += 1
            effective_to = (row.get("effective_to") or "").strip()
            if effective_to:
                day_after = (date.fromisoformat(effective_to) + timedelta(days=1)).isoformat()
                changes[day_after][code] -= 1

    counts: dict[str, int] = defaultdict(int)
    snapshots: list[tuple[str, set[str]]] = []
    for day in sorted(changes):
        for code, delta in changes[day].items():
            counts[code] += delta
            if counts[code] <= 0:
                counts.pop(code, None)
        snapshots.append((day, set(counts)))
    return snapshots


def load_quota(path: Path) -> dict[str, list[tuple[str, str]]]:
    """配置通道的成员区间：{代码: [(起, 止)]}。与 `--universe-file` 同格式，`effective_to` 可空。

    与 `load_universe` 的差别是这里要按**代码**查「今天算不算成员」，而不是按日期取整档名单，
    故存成区间而不是逐档快照。
    """
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            out[row["security_code"].zfill(6)].append(
                (row["effective_from"], row.get("effective_to") or "9999-12-31"))
    return dict(out)


def interval_active(spans: list[tuple[str, str]], day: str) -> bool:
    """Return whether ``day`` is inside any inclusive membership interval."""
    return any(start <= day <= end for start, end in spans)


def load_benchmark() -> dict[str, float]:
    if not BENCHMARK.exists():
        return {}
    with BENCHMARK.open(newline="", encoding="utf-8") as handle:
        return {r["date"]: float(r["close"]) for r in csv.DictReader(handle) if _num(r.get("close"))}


def load_index_series(code: str) -> dict[str, float]:
    """大盘围栏用的指数收盘序列 {日期: 收盘}。文件缺失返回空 dict，由调用方决定是否拒绝跑。"""
    path = OHLCV_DIR / f"INDEX_{code}.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["date"]: float(r["close"]) for r in csv.DictReader(handle) if _num(r.get("close"))}


def load_risk_free() -> list[tuple[str, float]]:
    if not RATES.exists():
        return []
    with RATES.open(newline="", encoding="utf-8") as handle:
        return sorted((r["observed_on"], float(r["risk_free_rate"])) for r in csv.DictReader(handle))


def daily_returns(prices: dict[str, dict[str, float]],
                  actions: dict[str, dict[str, tuple[float, float]]]) -> dict[str, dict[str, float]]:
    """逐票日收益率。**必须按送转折算**，否则除权日会被当成一次 −50% 的暴跌算进相关性。"""
    out: dict[str, dict[str, float]] = {}
    for code, series in prices.items():
        days = sorted(series)
        ret = {}
        for prev, cur in zip(days, days[1:]):
            base = series[prev]
            cash, ratio = actions.get(code, {}).get(cur, (0.0, 0.0))
            if base > 0:
                ret[cur] = (series[cur] * (1 + ratio) + cash) / base - 1
        out[code] = ret
    return out


_MISS = object()   # `None` 是合法的相关性取值（重叠不足），故缓存未命中要用另一个哨兵


class Correlations:
    """按月缓存的两两相关性。**按需计算**——每天只用得到「候选前几十只 + 现有持仓」，
    全市场 261×261 全算是 3.4 万对 × 170 个月，纯 Python 跑不动也没必要。
    """

    def __init__(self, returns, window: int = 252, min_overlap: int = 120):
        self.returns = returns
        self.window = window
        self.min_overlap = min_overlap
        self._cache: dict[tuple, float | None] = {}
        self._std: dict[tuple, tuple] = {}
        # 逐票排好序的交易日，只排一次。原先每个 (code, month) 都重排一遍全序列，
        # 一次长跑里是十几万次 O(n log n)。
        self._days: dict[str, list[str]] = {c: sorted(r) for c, r in returns.items()}

    def _series(self, code: str, month: str):
        """返回 `(日期元组, 值列表, 去均值后的值列表, 模长, 日期→值的 dict)`。

        **为什么要备这么多份**：`get` 的快路径要「已对齐的去均值向量 + 模长」直接做点积，
        慢路径（两只票停牌日不同、日期集不等）仍要按 `common` 现算，需要 dict 版本。
        """
        key = (code, month)
        cached = self._std.get(key)
        if cached is None:
            series = self.returns.get(code, {})
            all_days = self._days.get(code, ())
            # 全序列已排序，故「本月之前」是一个前缀，用 bisect 切比逐个过滤快
            cut = bisect.bisect_left(all_days, month)
            days = all_days[max(0, cut - self.window):cut]
            if len(days) < self.min_overlap:
                cached = ((), (), (), 0.0, {})
            else:
                values = [series[d] for d in days]
                mean = sum(values) / len(values)
                centered = [v - mean for v in values]
                norm = sum(v * v for v in centered) ** 0.5
                cached = (tuple(days), values, centered, norm, dict(zip(days, values)))
            self._std[key] = cached
        return cached

    def get(self, a: str, b: str, day: str) -> float | None:
        """`day` 当月之前满一年的日收益率相关系数；重叠不足返回 None（**当作未知、不当作 0**）。"""
        if a == b:
            return 1.0
        month = day[:7]
        key = (month, a, b) if a < b else (month, b, a)
        cached = self._cache.get(key, _MISS)
        if cached is not _MISS:
            return cached
        days_a, _, ca, na, map_a = self._series(a, month)
        days_b, _, cb, nb, map_b = self._series(b, month)
        if len(days_a) < self.min_overlap or len(days_b) < self.min_overlap:
            self._cache[key] = None
            return None
        if days_a == days_b:
            # 快路径：两只票的交易日完全相同（同一交易日历、都没停牌），占绝大多数。
            # 此时按 `common` 求的均值就等于各自窗口的均值，故可直接用预算好的去均值向量点积。
            # `sum(map(mul, ...))` 走 C 层，比生成器表达式快数倍。
            value = sum(map(_mul, ca, cb)) / (na * nb) if na > 0 and nb > 0 else None
            self._cache[key] = value
            return value
        # 慢路径：日期集不等（有一方停牌），只能按交集现算。**按日期排序遍历**，
        # 不用集合迭代序——集合序受字符串哈希影响，同一份数据换个进程可能换个求和顺序。
        common = sorted(map_a.keys() & map_b.keys())
        if len(common) < self.min_overlap:
            self._cache[key] = None
            return None
        xs = [map_a[d] for d in common]
        ys = [map_b[d] for d in common]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        value = num / (dx * dy) if dx > 0 and dy > 0 else None
        self._cache[key] = value
        return value


# 档位排序偏置。用户 2026-08-08 提出「L1 空间 +20/+10 再跟 L2 排序」。
TIER_BONUS = {"L1": 0.20, "L2": 0.10, "L3": 0.0}
TIER_QUOTA = {"L1": 4, "L2": 5, "L3": 1}


def new_low_flags(series: dict[str, float], lookback: int = 20) -> dict[str, bool]:
    """{日期: 当日收盘是否创 `lookback` 日新低}。「止跌走稳」判据的原料。"""
    days = sorted(series)
    values = [series[d] for d in days]
    out = {}
    for i, v in enumerate(values):
        window = values[max(0, i - lookback + 1): i + 1]
        out[days[i]] = v <= min(window) + 1e-12
    return out


def stabilized(flags: dict[str, bool], days: list[str], index: dict[str, int],
               day: str, quiet: int = 5) -> bool:
    """**止跌走稳**：最近 `quiet` 个交易日内**一次都没有创过 20 日新低**。

    用户 2026-08-08 原述「下跌后止跌走稳才买，例如五日内不破新低」。选这个判据而不是
    「站上某条均线」，是因为它**只要求下跌停住、不要求已经转涨**——估值组本就是左侧买法，
    要求转涨等于把它变成走势组。
    """
    i = index.get(day)
    if i is None or i < quiet:
        return False
    return not any(flags.get(days[j], False) for j in range(i - quiet + 1, i + 1))


def moving_averages(series: dict[str, float], windows=(5, 10, 20, 60, 120, 240)) -> dict[str, dict[int, float]]:
    """逐日均线（**不复权收盘**直接平均；`--ma-basis raw` 的旧口径，只用于复现 v4.31 前的读数）。"""
    days = sorted(series)
    values = [series[d] for d in days]
    out: dict[str, dict[int, float]] = {}
    for window in windows:
        total = 0.0
        for index, value in enumerate(values):
            total += value
            if index >= window:
                total -= values[index - window]
            if index >= window - 1:
                out.setdefault(days[index], {})[window] = total / window
    return out


def exright_affine(days: list[str], events: dict[str, tuple[float, float]]) -> tuple[list[float], list[float]]:
    """每个交易日「当日口径 → 末日口径」的仿射映射 `q = A·p + B`（除权折算的累积形式）。

    除权日 `e` 的事件 `(D, r)` 把 `e` 之前任一日的价格折到 `e` 当日口径：`p → (p − D)/(1 + r)`
    （§11.4 交易所除权参考价公式，与 `apply_corporate_actions` 对持仓锚的折算同式）。自末日向前
    累乘即可得到每一日到末日的复合映射；同一映射反过来用，就能把末日口径的均值折回任意一日的口径。
    """
    n = len(days)
    scale, shift = [1.0] * n, [0.0] * n
    a, b = 1.0, 0.0
    for i in range(n - 1, -1, -1):
        scale[i], shift[i] = a, b
        event = events.get(days[i])
        if event:                               # 第 i 日除权：i 之前的日子多一层 (p − D)/(1 + r)
            cash, ratio = event
            a, b = a / (1.0 + ratio), b - a * cash / (1.0 + ratio)
    return scale, shift


def adjusted_close_series(series: dict[str, float], events: dict[str, tuple[float, float]]) -> dict[str, float]:
    """前复权收盘（锚在序列末日）：创新低等跨日比较要在同一口径下做（OI-054）。"""
    days = sorted(series)
    scale, shift = exright_affine(days, events)
    return {d: scale[i] * series[d] + shift[i] for i, d in enumerate(days)}


def adjusted_moving_averages(series: dict[str, float], events: dict[str, tuple[float, float]],
                             windows=(5, 10, 20, 60, 120, 240)) -> dict[str, dict[int, float]]:
    """逐日均线，**前复权口径、折回当日股本/分红基准**（OI-054，`--ma-basis adjusted`，缺省）。

    窗口内每个历史收盘先折算到**当日**口径再平均，结果与当日不复权收盘同尺度，可直接比较
    `收盘 > MA20 > MA60`、`min(锚, 当日 MA60)`——与实盘扫描器的前复权均线闸门同基。此前的
    `moving_averages` 在不复权价上直接平均：10 送 10 当天原始价腰斩而 MA20/MA60 要二十／六十个
    交易日才跟上，其间 `收 > MA20` 恒假（买入被挡）、`收 < MA20` 恒真（减持闸门常开），止损线
    `min(锚, 当日 MA60)` 里的均线项也偏高一倍。实现：先把全序列映射到末日口径算滚动均值，再用
    仿射映射的逆把每日均值折回该日口径（仿射映射与求均值可交换，故逐日折回与逐窗折算等价）。
    没有除权事件的股票与旧函数逐位相同。
    """
    days = sorted(series)
    scale, shift = exright_affine(days, events)
    adjusted = [scale[i] * series[d] + shift[i] for i, d in enumerate(days)]
    out: dict[str, dict[int, float]] = {}
    for window in windows:
        total = 0.0
        for index, value in enumerate(adjusted):
            total += value
            if index >= window:
                total -= adjusted[index - window]
            if index >= window - 1:
                out.setdefault(days[index], {})[window] = (total / window - shift[index]) / scale[index]
    return out


# ------------------------------------------------------------------ 组合
@dataclass
class Lot:
    """一个**建仓→清仓周期**。分批买入合并进同一周期，直到清空才结算。"""
    code: str
    entry_date: str
    entry_ratio: float          # 建仓当日 P/V
    entry_value: float          # 建仓当日内在价值
    entry_band_low: float
    entry_band_high: float
    entry_upside: float         # 建仓当日「空间」= V/P − 1
    shares: float = 0.0
    invested: float = 0.0       # 累计买入金额
    proceeds: float = 0.0       # 累计卖出金额 + 累计现金分红
    dividends: float = 0.0
    buys: int = 0
    sells: int = 0
    peak_price: float = 0.0     # 持有期内的价格峰值（**周期内最大回撤按价格算**）
    max_drawdown: float = 0.0   # 1 − 价格/峰值 的最大值
    peak_money: float = 0.0     # (持仓市值+已回收)/累计投入 的峰值
    max_money_drawdown: float = 0.0
    entry_stop: float = 0.0     # 建仓日止损价（见 entry_stop_price）
    entry_stop_ma: int = 0      # 实际采用的均线周期——买在 MA60 下方时会退回 20
    stop_breach_streak: int = 0 # 连续收盘跌破止损价的交易日数；站回止损价即归零
    trail_peak: float = 0.0     # 上移锚（`--trail-ratio`）用的持有期价格峰值；除权日同步折算；开关关时恒 0
    lock_level: float = 0.0     # 盈利锁定线（`--profit-lock`）：收益达 x 后抬到 持仓均价×η，只升不降；除权日与锚同式折算；开关关时恒 0
    lock_eta: float = 0.0       # 设定当前锁定线的 η（流水标签用）
    avg_cost: float = 0.0       # 持仓均价：买入按股数加权、减持不变、除权日与锚同式折算（`--addon-max-gain`／`--gain-sell` 用）
    peak_intrinsic: float = 0.0 # 持有期内内在价值的峰值——**基本面退出**按它的回撤触发
    exit_date: str = ""
    exit_reason: str = ""


@dataclass
class Portfolio:
    cash: float
    lots: dict[str, Lot] = field(default_factory=dict)
    closed: list[Lot] = field(default_factory=list)
    debt: float = 0.0                 # 融资余额（含已计提利息）
    interest_paid: float = 0.0        # 累计利息

    def gross(self, prices: dict[str, float]) -> float:
        """总资产 = 现金 + 持仓市值。担保比例的分子。"""
        total = self.cash
        for code, lot in self.lots.items():
            price = prices.get(code)
            if price:
                total += lot.shares * price
        return total

    def equity(self, prices: dict[str, float]) -> float:
        """**净资产 N = 总资产 − 融资负债**（§9.3.1.1）。无杠杆时与旧口径完全一致。"""
        return self.gross(prices) - self.debt

    def margin_ratio(self, prices: dict[str, float]) -> float:
        """担保比例 = 总资产 ÷ 融资负债。无负债时为无穷大。"""
        return float("inf") if self.debt <= 0 else self.gross(prices) / self.debt


def credit_room(portfolio: Portfolio, limit: float) -> float:
    """还能再融多少。"""
    return max(0.0, limit - portfolio.debt)


def buying_power(portfolio: Portfolio, limit: float) -> float:
    """可用于买入的总金额 = 现金 + 剩余授信。"""
    return portfolio.cash + credit_room(portfolio, limit)


def draw_credit(portfolio: Portfolio, need: float, limit: float) -> float:
    """现金不足时融资补足，返回实际可动用的现金额。"""
    if portfolio.cash >= need:
        return need
    draw = min(need - portfolio.cash, credit_room(portfolio, limit))
    if draw > 0:
        portfolio.cash += draw
        portfolio.debt += draw
    return min(need, portfolio.cash)


def repay_over_limit(portfolio: Portfolio, limit: float) -> float:
    """§10.2：「负债超过授信额度时不可新增买入，卖出款先偿还超额负债」——用手头现金先把负债压回当日额度内。
    只用现金、不强制卖券（强制平仓仍只在 130% 线）；现金不够时余下超额留待后续卖出款（换仓卖出同样先还）。"""
    excess = portfolio.debt - limit
    if excess <= 0 or portfolio.cash <= 0:
        return 0.0
    pay = min(portfolio.cash, excess)
    portfolio.cash -= pay
    portfolio.debt -= pay
    return pay


def repay_debt(portfolio: Portfolio, ratchet: bool) -> None:
    """日终把剩余现金优先偿还融资（`--margin-ratchet`，纯研究开关，见 §12.70）。"""
    if not ratchet or portfolio.debt <= 0 or portfolio.cash <= 0:
        return
    pay = min(portfolio.cash, portfolio.debt)
    portfolio.cash -= pay
    portfolio.debt -= pay


def force_liquidate(portfolio: Portfolio, day: str, marks: dict[str, float],
                    maintenance: float, recover_to: float, ledger: list | None) -> dict:
    """担保比例跌破维持线时的强制平仓。

    按持仓市值从大到小卖，直到担保比例回到 `recover_to`（警戒线）或无券可卖。
    **A 股实盘是券商代为强平、不由持有人择时**，故这里不看 P/V、不看走势，只看市值。
    """
    sold_value = 0.0
    order = sorted(portfolio.lots.items(),
                   key=lambda kv: -(kv[1].shares * marks.get(kv[0], 0.0)))
    for code, lot in order:
        if portfolio.margin_ratio(marks) >= recover_to or portfolio.debt <= 0:
            break
        price = marks.get(code)
        if not price:
            continue
        proceeds = lot.shares * price
        sold_value += proceeds
        close_lot(portfolio, code, day, price, "强制平仓", ledger)
        pay = min(portfolio.cash, portfolio.debt)
        portfolio.cash -= pay
        portfolio.debt -= pay
    return {"sold": sold_value, "ratio_after": portfolio.margin_ratio(marks)}


def apply_corporate_actions(portfolio: Portfolio, day: str,
                            actions: dict[str, dict[str, tuple[float, float]]],
                            adjust_stops: bool = True) -> float:
    """除权日调股数、派息入现金。**不做这步整个回测就是错的**（穿越 10 转 10 会凭空亏一半）。

    `adjust_stops`（OI-054，缺省开）：建仓日止损锚 `entry_stop` 与持有期峰价 `peak_price` 按 §11.4
    同式折算 `(原值 − D) ÷ (1 + 送转比)`——§9.3.5 对实盘早已如此规定（「除权除息按 §11.4 同因子
    调整锚」），回测侧此前漏做：10 送 10 当天原始价腰斩而锚不动，整仓被当成「跌破止损」清空。
    `frozen`（`--exright-stop frozen`）只用于复现 v4.31 前的读数。
    """
    credited = 0.0
    for code, lot in portfolio.lots.items():
        event = actions.get(code, {}).get(day)
        if not event:
            continue
        cash_per_share, ratio = event
        cash = lot.shares * cash_per_share
        portfolio.cash += cash
        lot.dividends += cash
        lot.proceeds += cash
        credited += cash
        lot.shares *= (1 + ratio)
        if lot.trail_peak > 0:          # 上移锚峰值按 §11.4 同式折算：(原值 − D) ÷ (1 + 送转比)
            lot.trail_peak = max(0.0, (lot.trail_peak - cash_per_share) / (1 + ratio))
        if lot.lock_level > 0:          # 盈利锁定线与锚同式折算；现金红利高于线价的极端情形只折送转
            adjusted_lock = (lot.lock_level - cash_per_share) / (1 + ratio)
            lot.lock_level = adjusted_lock if adjusted_lock > 0 else lot.lock_level / (1 + ratio)
        if lot.avg_cost > 0:           # 持仓均价与锚同式折算；现金红利高于均价的极端情形只折送转
            adjusted_cost = (lot.avg_cost - cash_per_share) / (1 + ratio)
            lot.avg_cost = adjusted_cost if adjusted_cost > 0 else lot.avg_cost / (1 + ratio)
        if adjust_stops:
            if lot.entry_stop > 0:
                adjusted = (lot.entry_stop - cash_per_share) / (1 + ratio)
                # 锚为 0 表示「无止损」（falsy 短路），折算不得把一条活着的止损线静默折没——
                # 现金红利高于锚价本身的极端情形只折送转、不扣现金
                lot.entry_stop = adjusted if adjusted > 0 else lot.entry_stop / (1 + ratio)
            if lot.peak_price > 0:
                lot.peak_price = max(0.0, (lot.peak_price - cash_per_share) / (1 + ratio))
    return credited


def entry_stop_price(ma: dict[int, float], close: float, stop_ma: int) -> tuple[float, int]:
    """建仓日的止损价，返回 (价格, 实际采用的均线周期)。

    用户 2026-08-08 规则：**优先用 MA60；但若建仓时股价已在 MA60 下方，则退回 MA20。**
    理由是买在 MA60 之下时，拿 MA60 当止损等于**建仓即触发**——止损价高于成本价，
    这条止损不是保护而是立刻把仓位打掉。退回 MA20 才可能落在成本价下方。

    **v4.26 起生产口径不再走到 MA20 退档**（用户 2026-08-20，§12.90）：信号日闸门
    `收盘>MA20>MA60` 成立后 T+1 跳空破 MA60 时，几乎必然也破 MA20——退档锚仍高于
    成本、次日即触发，没达成本函数声称的目的。生产 `BASE` 用 `--entry-below-ma60 skip`
    直接放弃该笔建仓；本分支保留给 `--stop-ma 20` 研究口径与极端缺数据兜底。
    """
    if stop_ma == 20:
        return ma.get(20, 0.0), 20
    ma60 = ma.get(60, 0.0)
    if ma60 and close >= ma60:
        return ma60, 60
    return ma.get(20, 0.0), 20


def update_stop_breach(price: float, stop: float, streak: int,
                       confirm_days: int = 1, deep_pct: float = 0.0) -> tuple[int, str]:
    """更新固定止损价的连续跌破状态，返回 ``(新计数, 触发类型)``。

    ``confirm_days`` 按该证券有收盘价的交易日计；收盘回到止损价或其上方即清零。
    ``deep_pct`` 是深跌旁路，例如 0.03 表示收盘低于止损价 3% 时无需等满确认日。
    缺省 ``confirm_days=1, deep_pct=0`` 与原先“首次跌破即止损”逐位等价。
    """
    if not stop or price >= stop:
        return 0, ""
    streak += 1
    if deep_pct and price <= stop * (1 - deep_pct):
        return streak, "deep"
    if streak >= confirm_days:
        return streak, "confirmed"
    return streak, ""


def lot_ratio_ready(counters: dict, code: str, lot_value: float, tranche: float) -> bool:
    """§9.3.3 比例冷却（用户 2026-08-10 指令）：一手价值是一档的 `x` 倍时，**成交一手后跳过随后
    `round(x) − 1` 次合格机会**，即每 `round(x)` 次合格才动一手。

    为什么按「合格次数」而不是自然日：冷却的目的是让**平均速度等于一档/次**，而合格机会本身
    是不连续的（走势条件断了就不合格）。按日历天计的话，一只票停牌或走势坏掉十天，冷却期照走，
    复合格当天就能立刻成交——冷却等于没起作用。原 `--min-lot-cooldown 5` 即此形态。

    取 `round(x)` 而非 `floor(x)+1`：目标是平均速度 ≈ 一档/次，`round` 的偏差 <5%
    （茅台 x=9.07 → 每 9 次一手 = 1.008 档/次；春风动力 x=2.04 → 每 2 次一手 = 1.02 档/次）。
    若按字面「跳过 x 次」则为每 10 次/每 3 次，速度掉到 0.91/0.68 档，对贵股系统性欠配。

    买卖共用一个计数器：同一只票不可能同日既在买入清单又在减持清单。
    """
    if tranche <= 0 or lot_value <= 0:
        return False
    if counters.get(code, 0) > 0:
        counters[code] -= 1
        return False
    counters[code] = max(1, round(lot_value / tranche)) - 1
    return True


def sell_shares(target: float, held: float, price: float, lot_size: int,
                clear_floor: float = 0.0) -> float:
    """分批卖出的股数：按手向下取整。**剩余不足一手则整笔卖出**——A 股允许零股卖出，
    但不允许留着买不回来的零头当仓位管理。`clear_floor`（股数）抬高清空阈值：
    `--residual-clear tranche` 传入一档股数，余仓不足一档即整笔卖出（OI-092③ 研究口径，
    §9.3.2 第 4 步现行为不足一手）。返回 0 表示本次不动。"""
    if not lot_size:
        return min(held, target)
    want = min(held, target)
    lots_n = int(want // lot_size)
    if lots_n <= 0:
        return 0.0
    shares = lots_n * lot_size
    return held if held - shares < max(lot_size, clear_floor) else shares


def log_partial_sell(ledger: list | None, day: str, code: str, shares: float,
                     price: float, reason: str) -> None:
    """部分减持也要进流水。**此前只有 `close_lot` 记账**，故流水缺掉全部「减一档」，
    拿它重建逐日持仓会得到系统性偏高的股数——实测重建出的前三大合计可达 123.8%，
    而回测是无杠杆的。流水是「人工核对用」的凭证，缺一半就不能用来对账。
    """
    if ledger is None:
        return
    ledger.append({"date": day, "security_code": code, "action": "卖出",
                   "shares": f"{shares:.0f}", "price": f"{price:.3f}",
                   "amount": f"{shares * price:.0f}", "pv_ratio": "",
                   "intrinsic_value": "", "reason": reason})


def close_lot(portfolio: Portfolio, code: str, day: str, price: float, reason: str,
              ledger: list | None = None) -> None:
    lot = portfolio.lots.pop(code)
    if ledger is not None:
        ledger.append({"date": day, "security_code": code, "action": "卖出",
                       "shares": f"{lot.shares:.0f}", "price": f"{price:.3f}",
                       "amount": f"{lot.shares * price:.0f}", "pv_ratio": "",
                       "intrinsic_value": "", "reason": reason})
    portfolio.cash += lot.shares * price - trade_fee(lot.shares * price, day, "sell")
    lot.proceeds += lot.shares * price
    lot.shares = 0.0
    lot.exit_date, lot.exit_reason = day, reason
    lot.sells += 1
    portfolio.closed.append(lot)


# ------------------------------------------------------------------ 回测
def run(strategy: str, x: float, states, prices, actions, mas, since: str, until: str,
        capital: float, width: float = 0.10, tiers: dict[str, str] | None = None,
        credit_ratio: float = 0.0, credit_cap: float = 0.0, margin_rate: float = 0.0,
        maintenance: float = 1.30, recover_to: float = 1.50, margin_ratchet: bool = False,
        use_mos: bool = False, price_stop: bool = False, value_stop: float = 0.0,
        stop_ma: int = 20, trend_stop: bool = True, entry_filter: str = "none",
        lump_sum: float = 0.0, swap: bool = False, swap_margin: float = 0.10,
        max_positions: int = MAX_POSITIONS, lows=None, day_index=None,
        max_corr: float = 0.0, corr=None, corr_conflict: str = "skip",
        corr_strength_days: int = 126, tier_mode: str = "none",
        scan_depth: int = 40, min_upside: dict[str, float] | None = None,
        position_cap: float = 0.0, only_tiers: set[str] | None = None,
        universe: list[tuple[str, set[str]]] | None = None,
        trend_tranche: bool = False, trend_ma: tuple[int, ...] = (20, 60),
        trend_tol: float = 0.0, exec_delay: int = 0, exec_price: str = "close",
        sell_trend_ma: tuple[int, ...] = (), sell_full: bool = False, stop_min_days: int = 0,
        stop_confirm_days: int = 1, stop_deep_pct: float = 0.0,
        stop_line: str = "entry", entry_below_ma60: str = "ma20_stop",
        stop_basis: str = "exec", residual_clear: str = "lot",
        stop_partial: bool = False, stop_tranche: float = 1.0,
        liquidate_ma: int = 0, liquidate_days: int = 3,
        opens: dict[str, dict[str, float]] | None = None,
        sell_line_override: float | None = None, trend_exit_ma: int = 0,
        rank_by_upside: bool = True, buy_floor: float = 0.0,
        entry_mode: str = "trend", dev_ma: int = 60,
        dev_buy_max: float = 1.10, dev_sell_min: float = 0.0,
        hold_strong: str = "off", hold_strong_ma: tuple[int, ...] = (),
        rank_mode: str = "pv", quantile_window: int = 0,
        quantile_min_obs: int = 250, research_gate: str = "off",
        research: "ResearchGate | None" = None,
        swap_bypass_corr: bool = False, stats: dict | None = None,
        cluster_swap: bool = False, cluster_delta: float = 0.85,
        cluster_min_upside: float = 0.20, swap_partial: bool = False,
        lot_size: int = 0, rebuy: str = "off", ledger: list | None = None,
        min_lot_cooldown: int = 0, lot_ratio_cooldown: bool = False,
        quota_members: dict | None = None, quota_pct: float = 0.0,
        quota_swappable: bool = False,
        gate: str = "pv", buy_pct: float = 0.05, sell_pct: float = 0.60,
        pct_stop_when_rich: bool = False,
        addon_trend: str = "full", no_value_sell: bool = False,
        swap_require_weak: bool = False, swap_weak_ma: int = 20,
        swap_out_min_pv: float = 0.0,
        mkt: dict[str, float] | None = None, mkt_crash_days: int = 0,
        mkt_crash_pct: float = 0.10, mkt_trend_ma: int = 0,
        mkt_action: str = "block", mkt_release_ma: int = 20,
        mkt_block_scope: str = "all", trail_ratio: float = 0.0,
        profit_lock: tuple[tuple[float, float], ...] = (),
        tier_buy_scale: dict[str, float] | None = None,
        tier_sell_scale: dict[str, float] | None = None,
        exright_stop: str = "adjust", addon_max_gain: float = 0.0,
        gain_sell: float = 0.0, gain_sell_mode: str = "gated",
        swap_trigger: str = "power", credit_over_limit: str = "repay",
        candidate_log=None) -> dict:
    """`width` 即带的半宽 w：买入线 `P/V ≤ 1−w`、减持线 `P/V ≥ 1+w`。

    `tier_buy_scale`／`tier_sell_scale`（研究开关，§12.95「护城河放到决策层」）：按档位给买入线／
    减持线乘一个倍数（如 L1 ×1.25 = 强护城河少要安全边际、L3 ×0.875 = 多要），排序与换仓不动。
    缺省 None ＝ 原行为逐位不变。档位来自 2026 年人工分档，含后视，读数只能作上界。

    `use_mos`：买入线改按档位的安全边际取 `1 − MOS_档`（L1 0.90／L2 0.80／L3 0.70）。
    **MOS 只管买、不管卖**——安全边际是「便宜到什么程度才敢下手」，卖出仍按带上沿。
    估值层给 r、决策层给 MOS 的分工在此落地（研究开关，BASE 不用）。

    `price_stop`：给估值组也装上走势组那套「跌破建仓日 MA20 即清仓」。
    `value_stop`：**基本面退出**——内在价值自持有期峰值回落超过该比例即清仓。
    它直接盯 V 而不盯价格，是对「业绩下滑→越跌越贵」那条链路的正面处理：
    实测现行规则下这条链路虽然存在（64 次减持里 10 次由 V 下修触发），但**太慢**
    ——徐工机械那一笔从建仓到被判贵走了 9 年半。
    """
    portfolio = Portfolio(cash=capital)
    fees0 = FEES["paid"]        # 本次 run 的费用 = 结束时累计 − 起始累计
    stats = stats if stats is not None else collections.Counter()
    # 割肉后的「欠账」：被 `trend_exit_ma` 清掉的股数记在此处，等该股重新满足买入条件时
    # 按 `rebuy` 口径补回。**lump=一次性买回相同股数；gradual=交回常规定投**（即不记账）。
    cut_shares: dict[str, float] = {}
    last_buy: dict[str, str] = {}      # 每股最近一次买入日，供「买不起一档就买一手」的冷却期判定
    days = sorted(d for d in states if since <= d <= until)
    last_price: dict[str, float] = {}   # 停牌日没有行情，须沿用最后成交价盯市
    equity_curve: list[tuple[str, float, float, int]] = []
    buy_count = sell_count = 0
    turnover = 0.0
    tiers = tiers or {}
    # 减持线可独立于带宽设定：`--sell-line 1.30` 表示涨到 P/V=1.30 才开始减持，
    # 用来检验「让利润跑得更远」是否有效（实测 P/V≥1.10 清空的 17 笔中位 +28.6%、胜率 88%）。
    sell_line = sell_line_override if sell_line_override else 1.0 + width
    rich_tag = f"分位≥{sell_pct:.0%}" if gate == "self-pct" else f"P/V≥{sell_line:.2f}"
    # `self-pct-buy` = **非对称闸门**：买入用自身分位（把绝对口径永远够不着的白马放进来——
    # 迈瑞 17 年没有一天 `P/V≤1.00`，却有 43% 的日子在自身 3 年 10 分位以下），
    # 卖出/止损/换仓一律退回原始比值口径（现行减持线（§9.3.1）多年只触发个位数次，等于让赢家跑）。
    # 动机见 §12.61：分位是一把均值回归的尺子，擅长「找到谁便宜」，不擅长「决定何时离场」。
    pct_buy_gate = gate in ("self-pct", "self-pct-buy")
    # 时点股票库：`members` 随日期切换。第一档生效前**一只都不可买**——那段时间还没有
    # 任何「当时可得」的名单，凭空放行等于用未来的股票库交易。
    uni_idx, members = 0, (set() if universe else None)
    # 相对便宜度排序：把当日 P/V 换算成「相对该股自身历史」的读数再排序。
    # 用户 2026-08-09：单一 P/V 升序使可选集退化为深度价值股（价值股 P/V 常年 0.3~0.6，
    # 成长股修正估值后也只到 0.8 上下，永远排在后面——实测中际旭创 2025-05 合格但列第 27）。
    #
    # 两种口径：
    #   `quantile` 百分位——**已实测在底部饱和**（§12.9.26：2025-05-09 合格集前十的分位
    #              全部是 0.00，中际旭创并列第 17），端点处退化为无信息并列。
    #   `ratio`    当前 P/V ÷ 历史中位 P/V——**连续量，跌破历史最低后仍可继续减小**，
    #              故在端点不饱和。中际旭创 0.88/历史中位 vs 招行 0.30/历史中位，可公平比较。
    #
    # **严格无前视**：历史只含当日之前已观测到的 P/V，逐日插入；窗口版同步淘汰最老一条，
    # 使排序表恰好等于窗口内容。观测不足 `quantile_min_obs` 时退回原始 P/V，不猜。
    from bisect import bisect_left, insort
    from collections import deque as _deque
    pv_order: dict[str, object] = defaultdict(_deque)   # 插入序，用于淘汰
    pv_sorted: dict[str, list[float]] = defaultdict(list)

    def push_pv(code: str, ratio: float) -> None:
        order, arr = pv_order[code], pv_sorted[code]
        order.append(ratio)
        insort(arr, ratio)
        if quantile_window and len(order) > quantile_window:
            old = order.popleft()
            del arr[bisect_left(arr, old)]

    def score_of(code: str, ratio: float) -> float:
        arr = pv_sorted[code]
        if rank_mode == "pv" or len(arr) < quantile_min_obs:
            return ratio
        if rank_mode == "quantile":
            return bisect_left(arr, ratio) / len(arr)
        n = len(arr)
        median = arr[n // 2] if n % 2 else (arr[n // 2 - 1] + arr[n // 2]) / 2
        return ratio / median if median > 0 else ratio

    def strong_bull(code: str, day: str) -> bool:
        """完全多头排列：MA20>MA60>MA120>MA240（窗口可配）。**当日可判、无前视**。

        用于豁免强势股的减持与换出——**根因是报告期之间 `V` 冻结**：中际旭创 2025-05-26
        收盘 92.4／V=108.2／P/V=0.85，三周后收盘 125.2 而 V 仍是 108.2，P/V 被价格单方面
        推到 1.16 触发清空；此后该股再涨 560%。均线排列与内在价值无关，故可独立成立。
        """
        if not hold_strong_ma:
            return False
        ma = mas.get(code, {}).get(day, {})
        if not all(w in ma for w in hold_strong_ma):
            return False
        return all(ma[a] > ma[b] for a, b in zip(hold_strong_ma, hold_strong_ma[1:]))

    def buy_line(code: str) -> float:
        if use_mos:
            return 1.0 - MOS_BY_TIER.get(tiers.get(code, DEFAULT_TIER), width)
        line = 1.0 - width
        if tier_buy_scale:
            line *= tier_buy_scale.get(tiers.get(code, DEFAULT_TIER), 1.0)
        return line

    # ---- 分位表预热：把 `since` 之前**已经发生过**的观测先灌进去。
    # 不预热的话每个起点都要空等 `quantile_min_obs` 天才有第一只可买票，而这段空窗
    # 占全程的比例**随起点而变**（2020-11 起点要空掉全程的 17%、2009-11 起点只空 6%），
    # 于是多起点符号数量的是「起点离今天多远」而不是「规则好不好」——§12.1 第①层直接失效。
    # **不是前视**：灌进去的全是 `since` 之前的历史，交易仍从 `since` 当天才开始。
    if pct_buy_gate or rank_mode != "pv":
        warm = sorted(d for d in states if d < since)
        if quantile_window:
            warm = warm[-quantile_window:]      # 逐股再由 push_pv 按窗口淘汰，取这么多天即够
        for d in warm:
            for _code, _c, _v, _ratio in states[d]:
                push_pv(_code, _ratio)
        stats["分位表预热·交易日"] = len(warm)

    prev_day = None
    margin_events: list[dict] = []
    lot_counters: dict[str, int] = {}   # §9.3.3 比例冷却，买卖共用
    min_ratio, min_ratio_day = float("inf"), ""
    credit_limit = 0.0
    prev_trading = {n: d for d, n in zip(days, days[1:])}
    # `residual_clear`（OI-092③）：减档后余仓清空阈值。`lot`（现行，§9.3.2 第 4 步）＝不足一手
    # 才清空；`tranche`（研究口径，§12.126 A/B 主读数 −0.44 不采纳）＝传一档股数给 `sell_shares`、
    # 不足一档即清空。`budget` 在日循环内每日重算，lambda 晚绑定读的正是当日值。
    res_floor = (lambda p: budget / p) if residual_clear == "tranche" else (lambda p: 0.0)
    below_ma_run: dict[str, int] = {}      # 连续跌破 `liquidate_ma` 的天数，逐日累计
    # ---- 大盘围栏（用户 2026-08-20）：指数序列只在开关打开时参与；关时本段不产生任何分支。
    mkt_on = bool(mkt) and bool(mkt_crash_days or mkt_trend_ma)
    mkt_state = False                      # 当前是否处于围栏态（触发后持续到解除条件成立）
    if mkt_on:
        mk_days = sorted(mkt)
        mk_close = [mkt[d] for d in mk_days]

        def mk_idx(d: str) -> int | None:
            """信号日对应的指数下标：取 ≤ 信号日的最后一个指数交易日（两边都是 A 股日历，一般相等）。"""
            i = bisect.bisect_right(mk_days, d) - 1
            return i if i >= 0 else None

        def mk_ma(i: int, n: int) -> float | None:
            return sum(mk_close[i - n + 1:i + 1]) / n if n and i + 1 >= n else None
    for day in days:
        apply_corporate_actions(portfolio, day, actions, adjust_stops=(exright_stop == "adjust"))

        # ---- 融资计息（不需要价格，故放在循环头）----
        if portfolio.debt > 0 and margin_rate > 0 and prev_day:
            accrue = portfolio.debt * margin_rate * max(1, _days_between(prev_day, day)) / 365.0
            portfolio.debt += accrue
            portfolio.interest_paid += accrue
        prev_day = day
        if universe:
            while uni_idx < len(universe) and universe[uni_idx][0] <= day:
                members = universe[uni_idx][1]
                uni_idx += 1
        # 成交时序（用户 2026-08-10）：`exec_delay=1` = 「T 日收盘算信号、T+1 日成交」。
        # **实现为「移信号」而非「移价格」**——在 T 日用 T−1 的判据、在 T 日成交，
        # 于是现金、股数、盯市全部落在同一天。**先前按「记在 T 日、用 T+1 的价」实现是错的**：
        # 花的钱是 T+1 的价而持仓按 T 日收盘盯市，跳空大的日子会在净值曲线上造出一对假涨跌，
        # 2015-06 崩盘段实测把最大回撤由 33% 放大到 56%——那是记账错配，不是执行代价。
        sig_day = prev_trading.get(day) if exec_delay else day
        if sig_day is None:
            equity_curve.append((day, portfolio.equity({}), portfolio.cash, 0, portfolio.debt,
                                 portfolio.margin_ratio({})))
            continue
        today = {code: (close, value, ratio) for code, close, value, ratio in states[sig_day]}
        # `liquidate_ma` 的连续天数计数（用户 2026-08-10）：**对全池逐日累计**，不能只对持仓算
        # ——一只票可能在计数中途被卖光又买回，只对持仓算会把计数错误地清零。
        if liquidate_ma:
            for c, r in today.items():
                ma_l = mas.get(c, {}).get(sig_day, {}).get(liquidate_ma)
                if ma_l is None:
                    below_ma_run[c] = 0
                else:
                    below_ma_run[c] = below_ma_run.get(c, 0) + 1 if r[0] < ma_l else 0
        # ---- 自身分位闸门（用户 2026-08-15 的重构口径）----
        # **每只股票只跟自己比**：把当日估值指标换算成「在该股自身历史里的分位」，
        # 买入闸 = 分位 ≤ `buy_pct`、卖出闸 = 分位 ≥ `sell_pct`。
        # 与既有 `--rank-mode quantile` 的根本差别：那个分位**只用于排序**，
        # 谁能进合格集仍由原始 `P/V` 比线决定（§12.9.26 测的是排序不是闸门）；
        # 本模式让分位**直接当闸门**，横截面的绝对水平不再参与任何判定。
        #
        # **历史不足即不可买**，不像 `score_of` 那样回落到原始比值——回落会让新股
        # 凭「无历史」绕过闸门，那正是本模式要消除的横截面比较。
        pcts: dict[str, float] = {}
        if pct_buy_gate:
            for code, r in today.items():
                arr = pv_sorted[code]
                if len(arr) >= quantile_min_obs:
                    pcts[code] = bisect_left(arr, r[2]) / len(arr)
        scores = {code: score_of(code, r[2]) for code, r in today.items()} if rank_mode != "pv" else {}
        # **先算分位再入库**：当日这一条不参与自己的分位，故判据只用 t 之前的观测，严格无前视。
        if rank_mode != "pv" or pct_buy_gate:
            for code, r in today.items():
                push_pv(code, r[2])

        def is_rich(code: str, ratio: float | None) -> bool:
            """「贵」的判据。分位口径下与原始比值口径下是两套完全不同的尺子。"""
            if gate == "self-pct":
                p = pcts.get(code)
                return p is not None and p >= sell_pct
            line = sell_line
            if tier_sell_scale:
                line *= tier_sell_scale.get(tiers.get(code, DEFAULT_TIER), 1.0)
            return ratio is not None and ratio >= line
        # 停牌股当日无价，**必须沿用最后成交价**——否则它会整只从净值里消失，
        # 复牌当天再凭空出现，资金曲线上是一对假的暴跌+暴涨。
        marks = {}
        for code in portfolio.lots:
            price = prices.get(code, {}).get(day) or (today[code][0] if code in today else None)
            if price:
                last_price[code] = price
            if code in last_price:
                marks[code] = last_price[code]
        # OI-040／协议 §8：退市 ≠ 归零也 ≠ 永远冻结——名册内代码过了末个交易日即按最后成交价整仓清出
        # （失败退市者末价已含退市整理期崩塌，吸收合并者末价≈换股对价；本仓库无换股比例，不跟踪存续主体）。
        for code in [c for c in portfolio.lots if c in DELISTED_LAST and day > DELISTED_LAST[c] and c in last_price]:
            turnover += portfolio.lots[code].shares * last_price[code]
            close_lot(portfolio, code, day, last_price[code], ledger=ledger, reason="退市·末日收盘平仓")
            marks.pop(code, None)
            stats["退市·末日收盘平仓"] += 1
        # ---- 成交价口径（用户 2026-08-10）：`exec_delay=1` 表示「T 日收盘算信号、T+1 日成交」。
        # 买入/减持/换仓判据（合格集、`P/V`、走势与减持闸门）用 T 日收盘——信号本来就定义在
        # T 日收盘上；止损判据按 `--stop-basis`（现行 exec：成交日收盘对成交日均线）、建仓跳过
        # 按 `--entry-below-ma60`（现行 skip：T 日收盘对成交日 MA60）各有自己的时点口径
        # （OI-092 A/B，§12.126）；盯市净值用当日收盘（停牌沿用末价）。
        # T+1 无价（停牌/最后一日）时回落到 T 日收盘并计数，不静默丢弃该笔。
        def fill_price(code: str, fallback: float | None) -> float | None:
            if exec_delay == 0:
                return fallback                      # 现行口径：成交价即 T 日收盘
            src = (opens or {}) if exec_price == "open" else prices
            got = src.get(code, {}).get(day)
            if got and got > 0:
                return got
            stats["成交日无价·回落信号日收盘"] += 1
            return fallback

        # ---- 融资：按当日净资产重定授信额度，并查担保比例 ----
        if credit_ratio > 0:
            net_now = portfolio.equity(marks)
            # 授信随当日净资产重定、封顶 credit_cap（§10.2，用户 2026-08-22 裁定 OI-081）：
            # `repay`（缺省）＝额度就是 min(净资产×比例, 上限)，负债超出的部分在当日常规卖出（止损／减持／出名单）
            # 之后先用现金偿还（`repay_over_limit`），换仓卖出款同样先还（用户 2026-08-22 裁定），剩余现金＋剩余授信才可买入；
            # `keep`＝v4.39 前的旧口径——额度取 max(已用负债, …)，下调不强制还款，只用于复现旧读数。
            credit_limit = min(max(net_now, 0.0) * credit_ratio, credit_cap)
            if credit_over_limit == "keep":
                credit_limit = max(portfolio.debt, credit_limit)
            ratio_now = portfolio.margin_ratio(marks)
            if portfolio.debt > 0 and ratio_now < min_ratio:
                min_ratio, min_ratio_day = ratio_now, day
            if portfolio.debt > 0 and ratio_now < maintenance:
                res = force_liquidate(portfolio, day, marks, maintenance, recover_to, ledger)
                marks = {c: p for c, p in marks.items() if c in portfolio.lots}
                margin_events.append({
                    "date": day, "ratio_before": ratio_now, "ratio_after": res["ratio_after"],
                    "sold": res["sold"], "equity_before": net_now,
                    "equity_after": portfolio.equity(marks), "debt_after": portfolio.debt,
                })
                stats["**爆仓·强制平仓**"] += 1

        equity = portfolio.equity(marks)
        if equity <= 0:
            stats["**穿仓·净资产归零**"] += 1
            break
        budget = equity * x

        # ---- 大盘围栏状态机（用户 2026-08-20）。判据全取**信号日**指数；动作落在成交日，与个股同序。
        fence_on = False
        if mkt_on:
            i_mk = mk_idx(sig_day)
            if i_mk is not None:
                crash_hit = bool(mkt_crash_days) and i_mk >= mkt_crash_days and \
                    mk_close[i_mk] / mk_close[i_mk - mkt_crash_days] - 1 <= -mkt_crash_pct
                ma_t = mk_ma(i_mk, mkt_trend_ma) if mkt_trend_ma else None
                bear_hit = ma_t is not None and mk_close[i_mk] < ma_t
                if not mkt_state:
                    if crash_hit or bear_hit:
                        mkt_state = True
                        stats["大盘围栏·触发"] += 1
                        if mkt_action == "liquidate":
                            # 整仓清空：按成交日价、计手续费、进流水，与止损清仓同一出口。
                            for code in list(portfolio.lots):
                                price = fill_price(code, marks.get(code))
                                if not price:
                                    continue
                                turnover += portfolio.lots[code].shares * price
                                close_lot(portfolio, code, day, price, ledger=ledger,
                                          reason="大盘围栏·清仓")
                                sell_count += 1
                                stats["大盘围栏·清仓"] += 1
                            marks = {c: p for c, p in marks.items() if c in portfolio.lots}
                else:
                    # 解除：速度围栏要「触发不再成立 且 指数站回 MA(R)」；趋势围栏要「指数回到 MA(M) 上」。
                    ma_r = mk_ma(i_mk, mkt_release_ma) if mkt_crash_days else None
                    crash_clear = (not mkt_crash_days) or (not crash_hit and ma_r is not None
                                                           and mk_close[i_mk] > ma_r)
                    trend_clear = (not mkt_trend_ma) or (not bear_hit)
                    if crash_clear and trend_clear:
                        mkt_state = False
                        stats["大盘围栏·解除"] += 1
            fence_on = mkt_state
            if fence_on:
                stats["大盘围栏·禁买日"] += 1

        # ---- 周期内回撤。**必须按价格算，不能按持仓市值算**：分批买入会推高市值、分批卖出
        # 会压低市值，两者都与价格无关。首版按市值算，结果三环集团 +8.5% 收益却报出
        # 「周期内最大回撤 99.2%」——那 99% 全是减仓造成的，不是股价跌的。
        # 另记一条**资金口径**回撤 (持仓市值+已回收)/累计投入，用来看这笔钱最差时浮亏多少。
        for code, lot in portfolio.lots.items():
            price = marks.get(code)
            if not price:
                continue
            lot.peak_price = max(lot.peak_price, price)
            if trail_ratio:
                lot.trail_peak = max(lot.trail_peak, price)   # 上移锚的峰值：只在开关开时维护
            if lot.peak_price > 0:
                lot.max_drawdown = max(lot.max_drawdown, 1 - price / lot.peak_price)
            current_value = today.get(code, (None, None, None))[1]
            if current_value:
                lot.peak_intrinsic = max(lot.peak_intrinsic, current_value)
            if lot.invested > 0:
                money = (lot.shares * price + lot.proceeds) / lot.invested
                lot.peak_money = max(lot.peak_money, money)
                lot.max_money_drawdown = max(lot.max_money_drawdown, 1 - money / lot.peak_money)

        # ---- 卖出（先卖后买：卖出释放的现金当日即可用，与「有资金就买」一致）
        for code in list(portfolio.lots):
            lot, price = portfolio.lots[code], fill_price(code, marks.get(code))
            if not price:
                continue
            ratio = today.get(code, (None, None, None))[2]
            # 移出股票库 → **逐步清仓**（用户 2026-08-08：「对于被移除股票库的公司，逐步清仓」）。
            # 按与减持同一速度卖，不一次性砸出——一年一次的换库若全额出清，会在每年 5 月
            # 制造一次集中抛售，测出来的是流动性冲击而不是规则优劣。
            if members is not None and code not in members:
                shares = sell_shares(budget / price, lot.shares, price, lot_size, res_floor(price))
                if (not shares and lot_ratio_cooldown and lot_size
                        and lot.shares >= lot_size
                        and lot_ratio_ready(lot_counters, code, price * lot_size, budget)):
                    shares = lot_size if lot.shares - lot_size >= lot_size else lot.shares
                    stats["高价股·按手减持"] += 1
                if shares > 0:
                    if shares >= lot.shares * 0.999:
                        turnover += lot.shares * price
                        close_lot(portfolio, code, day, price, ledger=ledger, reason="移出股票库·逐步清仓")
                    else:
                        log_partial_sell(ledger, day, code, shares, price, "移出股票库·减一档")
                        lot.shares -= shares
                        portfolio.cash += shares * price - trade_fee(shares * price, day, "sell")
                        lot.proceeds += shares * price
                        lot.sells += 1
                        turnover += shares * price
                    sell_count += 1
                continue
            # 走势退出：**跟随均线**而非建仓日固定价。用户 2026-08-09：「把跌破120日均线作为
            # 减仓阈值」。与 `--price-stop` 的区别是后者盯建仓当日那条静态止损价，此处盯当日均线。
            # 偏离度卖出：涨到中期均线的 `dev_sell_min` 倍以上即清仓。用户 2026-08-09：
            # 「涨的比中期均线高很多就卖出」。与 P/V 减持线的区别是它盯**价格相对自身均线的位置**，
            # 与内在价值无关，故在估值带失真时仍可用。
            if dev_sell_min:
                ma_now = mas.get(code, {}).get(day, {})
                base = ma_now.get(dev_ma)
                if base and price >= base * dev_sell_min:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"偏离MA{dev_ma}达{dev_sell_min:.0%}清仓")
                    sell_count += 1
                    continue
            if trend_exit_ma:
                ma_now = mas.get(code, {}).get(day, {})
                if trend_exit_ma in ma_now and price < ma_now[trend_exit_ma]:
                    if rebuy == "lump":
                        cut_shares[code] = cut_shares.get(code, 0.0) + lot.shares
                        stats["割肉记账"] += 1
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"跌破MA{trend_exit_ma}清仓")
                    sell_count += 1
                    continue
            # `stop_min_days`（用户 2026-08-12）：止损的最短持有期。逐笔分析显示 73% 的平仓是
            # 建仓后**中位 3 天**即触发的止损，卖出后该股半年/1年/3年中位仍 +0.9%/+2.9%/+16.6%
            # ——即这条止损主要在切掉刚建的仓，而非在保护已有利润。本开关用于检验「给仓位一点时间」。
            # `pct_stop_when_rich`（用户 2026-08-15：「抄底之后不止损，只有这个股票被踢出池子才止损」）：
            # 止损**只对已经贵起来的仓位生效**。语义是「便宜时下跌是加仓机会不是离场理由，
            # 只有涨到自身历史高分位之后才用均线保护利润」。**出名单清仓那条不受影响**
            # ——它在本分支之前判、且是基本面退出，正是用户说的「被踢出池子才止损」那条路径。
            stop_enabled = ((strategy == "trend" and trend_stop) or price_stop) and bool(lot.entry_stop)
            # `stop_line`（用户 2026-08-19 实验）：`min_entry_current` 把生效止损线改为
            # **min(建仓日冻结线, 当日同周期均线)**——均线跌到冻结线之下时止损跟随下移（放宽），
            # 均线上移不抬线（`entry` 为旧冻结口径；现行为 `min_entry_current`（BASE））。周期取该仓实际采用的
            # `entry_stop_ma`（买在 MA60 下方退 MA20 的仓，比较的也是当日 MA20，不混周期）。
            # `stop_basis`（OI-092②）：`exec`（现行，§9.3.1 止损行）＝成交日收盘对成交日均线、
            # 同日判同日卖；`signal`（研究口径，§12.126 A/B 主读数 −0.42 不采纳）＝T 日收盘对
            # T 日均线判、T+1 按成交价卖。信号日无收盘（停牌）则当日不判，跌破计数保持不动。
            judge_day = sig_day if stop_basis == "signal" else day
            judge_price = today.get(code, (None,))[0] if stop_basis == "signal" else price
            stop_level = lot.entry_stop
            if stop_line == "min_entry_current" and lot.entry_stop and lot.entry_stop_ma:
                ma_cur = mas.get(code, {}).get(judge_day, {}).get(lot.entry_stop_ma, 0.0)
                if ma_cur:
                    stop_level = min(stop_level, ma_cur)
            # `trail_ratio`（用户 2026-08-20：「给止损锚设一个上移机制，主要针对盈利比较大的股票，
            # 锚_2 = max(锚_2, 当日股价×k)，止损价 = max(锚_2, min(锚, MA60))」）：锚_2 = k × 持有期峰价
            # （逐日取 max 即等价于 k × 峰值），只升不降，除权日同步折算。k 越小，线越晚才咬住——
            # k=2/3 要涨到比原锚高 50% 才开始生效，天然只作用于盈利大的仓位。
            stop_tag = f"建仓日MA{lot.entry_stop_ma}"
            if trail_ratio and lot.trail_peak > 0:
                trail_level = lot.trail_peak * trail_ratio
                if trail_level > stop_level:
                    stop_level, stop_tag = trail_level, f"上移锚{trail_ratio:g}×峰价"
            # `profit_lock`（用户 2026-08-24 实验：「收益超过 x% 后，止损线上调为成本线×η」）：信号日收盘 ≥ 持仓均价×(1+x)
            # 即把锁定线抬到 持仓均价×η——只升不降（加仓抬高均价后按新均价重判，满足条件才再抬），除权日与锚同式折算；
            # 生效止损线 = max(现行 min(锚, 当日均线)[, 上移锚], 锁定线)。阶梯 x1:η1,x2:η2 逐级抬高。与 `--trail-ratio`
            # 的区别：锁定线盯**成本**不盯峰价，涨得再多也只守住 η×成本，不随峰值上移。
            if profit_lock and lot.avg_cost > 0:
                sig_close = today.get(code, (None,))[0] or price
                for gain_x, eta in profit_lock:
                    if sig_close >= lot.avg_cost * (1.0 + gain_x) and lot.avg_cost * eta > lot.lock_level:
                        lot.lock_level, lot.lock_eta = lot.avg_cost * eta, eta
                if lot.lock_level > stop_level:
                    stop_level, stop_tag = lot.lock_level, f"盈利锁定{lot.lock_eta:g}×成本"
            stop_trigger = ""
            if stop_enabled and judge_price:
                lot.stop_breach_streak, stop_trigger = update_stop_breach(
                    judge_price, stop_level, lot.stop_breach_streak,
                    stop_confirm_days, stop_deep_pct,
                )
            elif not stop_enabled:
                lot.stop_breach_streak = 0
            if pct_stop_when_rich and not is_rich(code, ratio):
                if stop_level and price < stop_level:
                    stats["止损·因仍便宜而不触发"] += 1   # 只数**真的被压住**的那些，不数每一天
            elif stop_enabled and stop_trigger \
                    and (not stop_min_days or _days_between(lot.entry_date, day) >= stop_min_days):
                if stop_trigger == "deep":
                    trigger_reason = f"低于止损价{stop_deep_pct:.0%}·深跌旁路"
                elif stop_confirm_days == 1:
                    # 保留缺省配置的原始成交原因文本，避免只因新增研究开关就污染产物 diff。
                    trigger_reason = "跌破"
                else:
                    trigger_reason = f"连续{lot.stop_breach_streak}日跌破"
                stats[f"止损触发·{stop_trigger}"] += 1
                if stop_tag.startswith("上移锚"):
                    stats["止损触发·上移锚"] += 1
                if stop_tag.startswith("盈利锁定"):
                    stats["止损触发·盈利锁定"] += 1
                # `stop_partial`（用户 2026-08-14：「卖出改为定投式减仓」）：止损由**整仓清空**
                # 改为**与定投同速、每日减一档**。这是当前策略里最后一条整仓路径——出名单清仓、
                # `P/V` 减持、换仓三条早已是按档减，故本开关等于把卖出端整体对称到买入端。
                # **`entry_stop` 只在建仓那天设一次、加仓不重设**（见 `if lot is None` 分支），
                # 故语义是「只要还在建仓日均线之下就每天减一档」，价格站回线上即自动停手。
                if stop_partial:
                    # `stop_tranche` 是减仓速度的倍数：1.0 = 与定投同速，∞ = 退回整仓清空。
                    # 用它做剂量-反应，检验「减得慢」到底是不是 STP 变差的原因。
                    shares = sell_shares(budget * stop_tranche / price, lot.shares, price, lot_size, res_floor(price))
                    if (not shares and lot_ratio_cooldown and lot_size
                            and lot.shares >= lot_size
                            and lot_ratio_ready(lot_counters, code, price * lot_size, budget)):
                        shares = lot_size if lot.shares - lot_size >= lot_size else lot.shares
                        stats["高价股·按手减持"] += 1
                    if shares > 0:
                        if shares >= lot.shares * 0.999:
                            turnover += lot.shares * price
                            close_lot(portfolio, code, day, price, ledger=ledger,
                                      reason=f"{trigger_reason}{stop_tag}·减完清空")
                        else:
                            log_partial_sell(ledger, day, code, shares, price,
                                             f"{trigger_reason}{stop_tag}·减一档")
                            lot.shares -= shares
                            portfolio.cash += shares * price - trade_fee(shares * price, day, "sell")
                            lot.proceeds += shares * price
                            lot.sells += 1
                            turnover += shares * price
                        sell_count += 1
                        stats["止损·减一档"] += 1
                    continue
                turnover += lot.shares * price     # 必须在 close_lot 之前取——它会把 shares 清零
                close_lot(portfolio, code, day, price, ledger=ledger,
                          reason=f"{trigger_reason}{stop_tag}止损")
                sell_count += 1
                continue
            # 基本面退出：内在价值自峰值回落超阈值即清仓。**盯 V 不盯价**，故一只票可以
            # 在股价没怎么跌的时候就被卖掉——那正是「业绩塌了但市场还没反应」的情形。
            if value_stop and lot.peak_intrinsic > 0:
                current_value = today.get(code, (None, None, None))[1]
                if current_value and current_value <= lot.peak_intrinsic * (1 - value_stop):
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"内在价值自峰值回落≥{value_stop:.0%}")
                    sell_count += 1
                    continue
            # 强势多头豁免减持：空间缩小不卖，等趋势自己走坏或财报更新带改变格局。
            if (hold_strong in ("sell", "both") and strong_bull(code, day)):
                continue
            # `sell_trend_ma`（用户 2026-08-10）：**卖出端的右侧化**。买入端要求
            # `收盘 > MA20 > MA60`（贵了才卖不够，还要等趋势真的坏掉），卖出端原本是纯估值触发
            # ——`P/V ≥ 减持线` 当日即开始按一档减。本参数把它改为**还须同时呈空头排列**才减，
            # 例如 `(5, 20)` 即 `收盘 < MA5 < MA20`。空元组 = 原行为。
            # **只闸这一条路径**：出 §5 名单的清仓与换仓卖出不受影响——前者是基本面退出、
            # 后者是资金驱动，都与趋势无关；闸住它们等于在该走的时候不走。
            # 判据用**信号日**的收盘与均线（与买入端同源），不是成交价。
            # `liquidate_ma` / `liquidate_days`（用户 2026-08-10）：**贵 + 中期趋势确认走坏 → 一次清仓**。
            # 与 `--trend-exit-ma` 的两点区别：①**须同时 `P/V ≥ 减持线`**（只对已经贵的票生效，
            # 便宜票跌破年线是加仓机会不是清仓理由）；②**要求连续 N 日**跌破，不是单日破线，
            # 以滤掉一次性插针。它在减一档之前判——既然要清，就不必先减一档。
            if (liquidate_ma and is_rich(code, ratio)
                    and below_ma_run.get(code, 0) >= liquidate_days):
                turnover += lot.shares * price
                close_lot(portfolio, code, day, price, ledger=ledger,
                          reason=f"{rich_tag}且连续{liquidate_days}日破MA{liquidate_ma}·清仓")
                sell_count += 1
                stats[f"贵+破MA{liquidate_ma}·一键清仓"] += 1
                continue
            # `no_value_sell`（用户 2026-08-15：「删除超过 P/V 之后的减仓规则」）：
            # **整条估值减持路径关闭**（§9.3.2 第 4 步第②条）。此后卖出只剩三条：
            # ⓪建仓日均线止损、②出 §5 名单逐步清仓、③换仓。
            # **注意现行减持线（§9.3.1）多年只触发个位数次**，故这条的直接影响本就很小；
            # 真正的意义是把「贵了要不要减」这个判断从机械规则里彻底移除。
            # `gain_sell`（用户 2026-08-22 实验）：**信号日收盘 ≥ 持仓均价 × (1 + G) 也算「该减」**——
            # 与 `P/V ≥ 减持线` 走同一条减一档路径。`gated`＝同样过走势闸门（`sell_trend_ma`）；
            # `ungated`＝不过闸门，涨幅达标即每日减一档直到跌回线下或减完。0＝关（逐位不变）。
            value_rich = (not no_value_sell) and is_rich(code, ratio)
            gain_hit = bool(gain_sell) and lot.avg_cost > 0 and \
                (today.get(code, (None,))[0] or price) >= lot.avg_cost * (1.0 + gain_sell)
            if not value_rich and not gain_hit:
                continue
            sell_tag = rich_tag if value_rich else f"涨幅≥{gain_sell:.0%}"
            if sell_trend_ma and not (gain_hit and gain_sell_mode == "ungated"):
                sig_close = today.get(code, (None,))[0]
                ma_s = mas.get(code, {}).get(sig_day, {})
                if not sig_close or not all(w in ma_s for w in sell_trend_ma):
                    continue                       # 均线不全 → 不减，等数据齐
                seq = [sig_close] + [ma_s[w] for w in sell_trend_ma]
                if not all(a < b for a, b in zip(seq, seq[1:])):
                    stats["减持被走势闸门挡下" if value_rich else "涨幅减持被走势闸门挡下"] += 1
                    continue
            if value_rich or gain_hit:
                # `sell_full`（用户 2026-08-12）：触发即整仓卖出，不按一档减。
                # 与 `--dev-sell-min` / `--liquidate-ma` 的区别是它仍只看 P/V 与走势闸门，
                # 不另加均线条件——即「符合卖出条件就一次性卖完」的直译。
                if sell_full:
                    stats["P/V≥减持线·整仓卖出" if value_rich else f"{sell_tag}·整仓卖出"] += 1
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger,
                              reason=f"{sell_tag}整仓卖出")
                    sell_count += 1
                    continue
                stats["P/V≥减持线·减一档" if value_rich else f"{sell_tag}·减一档"] += 1
                shares = sell_shares(budget / price, lot.shares, price, lot_size, res_floor(price))
                if (not shares and lot_ratio_cooldown and lot_size
                        and lot.shares >= lot_size
                        and lot_ratio_ready(lot_counters, code, price * lot_size, budget)):
                    shares = lot_size if lot.shares - lot_size >= lot_size else lot.shares
                    stats["高价股·按手减持"] += 1
                if shares <= 0:
                    continue
                if shares >= lot.shares * 0.999:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"{sell_tag}清空")
                else:
                    log_partial_sell(ledger, day, code, shares, price, f"{sell_tag}·减一档")
                    lot.shares -= shares
                    portfolio.cash += shares * price - trade_fee(shares * price, day, "sell")
                    lot.proceeds += shares * price
                    lot.sells += 1
                    turnover += shares * price
                sell_count += 1

        # ---- 常规卖出之后、换仓与买入之前：负债超出当日额度的部分先用现金偿还（§10.2，OI-081）
        if credit_over_limit == "repay" and credit_ratio > 0:
            if repay_over_limit(portfolio, credit_limit) > 0:
                stats["超额授信·卖出款先还"] += 1

        # ---- 买入：合格集为空则持币（用户 2026-08-08 裁定），**不硬凑前十**
        pool = states[sig_day] if members is None else [r for r in states[sig_day] if r[0] in members]
        # 配置通道的当日成员（见下方买入段）。**必须在换仓之前算好**——换仓要用它把通道持仓
        # 排除在卖出源之外，而换仓在买入之前跑。
        quota_today: set[str] = set()
        if quota_pct > 0 and quota_members:
            quota_today = {c for c, spans in quota_members.items()
                           if interval_active(spans, sig_day)}
        # 拆解用：`quota_swappable` 打开后通道持仓照样可被换仓卖出，
        # 于是「通道买入」与「通道免换仓」两个机制可以单独计价（用户 2026-08-15 那轮的必需检验）。
        quota_hold_today = set() if quota_swappable else quota_today
        # `rank_by_upside=False`：空间只作**阈值**不作排序，合格集内按代码排序（中性顺序），
        # 即「只要空间够 + 走势好就买」，不再优先买最便宜的。用户 2026-08-09 提出的对照口径。
        def _key(r):
            if not rank_by_upside:
                return r[0]
            if pct_buy_gate:
                return (pcts[r[0]], r[0])     # 组内也按「相对自身多便宜」排，不再比绝对水平
            return scores.get(r[0], r[3]) if rank_mode != "pv" else r[3]
        if pct_buy_gate:
            # **闸门即分位**：没有足够历史的（`pcts` 里没有）一律不可买。
            eligible = sorted((r for r in pool
                               if (p := pcts.get(r[0])) is not None and p <= buy_pct), key=_key)
            stats["分位闸·当日合格"] += len(eligible)
        else:
            eligible = sorted((r for r in pool if r[3] <= buy_line(r[0])), key=_key)
        # 大盘围栏态：合格集置空 → 换仓、簇内升级、相关性补位、定投买入全部无源可买；
        # 卖出端（止损/减持/出名单）不受影响。只在开关打开时才可能为真。
        if fence_on:
            # `new` 范围：只拦新建仓，已持仓按原规则继续定投——检验「熊市里给老仓加仓」是不是围栏的代价来源。
            eligible = ([] if mkt_block_scope == "all"
                        else [r for r in eligible if r[0] in portfolio.lots])
        # `buy_floor`（用户 2026-08-14：「扩大买入阈值的范围，例如 0.8-1.2」的双边读法）：
        # 买入由单边上限改为**区间** `[buy_floor, buy_line]`，即**过分便宜的也不买**。
        # 动机是在「公平 P/V」口径下，`P/V` 远低于 1 未必是错杀，也可能是市场看对了
        # （基本面正在坏、带还没反映）。0 表示不设下限，即原行为。
        if buy_floor > 0:
            kept = [r for r in eligible if r[3] >= buy_floor]
            stats["买入下限挡下"] += len(eligible) - len(kept)
            eligible = kept
        # 分档最低空间门槛（用户 2026-08-08：L1 >30%、L2 >40%；**L3 未指定，本脚本按 L2 取 40%**
        # ——L3 风险更高，门槛不该比 L2 松）。空间 = V/P − 1 = 1/(P/V) − 1。
        if min_upside:
            eligible = [r for r in eligible
                        if (1.0 / r[3] - 1.0) >= min_upside.get(tiers.get(r[0], DEFAULT_TIER), 0.0)]
        if only_tiers:
            eligible = [r for r in eligible if tiers.get(r[0], DEFAULT_TIER) in only_tiers]
        # 研报预期门槛：**卡在所有买入路径的上游**——`eligible` 同时供定投买入与换仓选目标，
        # 在此过滤即等于「每次买入节点都要过一次」，加仓也一样受约束（用户 2026-08-09 原话）。
        if research_gate != "off" and research is not None:
            eligible = [r for r in eligible if research.allows(research_gate, r[0], day)]
        # 入场模式：trend=收盘>MA20>MA60（方向）；deviation=收盘 ≤ MA60×dev_buy_max（位置）；
        # both=两者同时满足。**方向与位置是两件事**——方向判断趋势是否成立，位置判断是否追高。
        # **均线必须取 `sig_day`**：`r[1]` 来自 `states[sig_day]`，即信号日收盘；原先拿 `day`
        # （成交日）的 MA 与它相比，在 `--exec-delay 1` 下等于用 T+1 的收盘去判 T 日的信号
        # ——**后视**。改为两侧同取 `sig_day`，与走势闸门同源（v2.91 修，2026-08-14）。
        if strategy == "trend" and entry_mode in ("deviation", "both"):
            kept = []
            for r in eligible:
                base = mas.get(r[0], {}).get(sig_day, {}).get(dev_ma)
                if base and r[1] <= base * dev_buy_max:
                    kept.append(r)
            eligible = kept
        if strategy == "trend" and entry_mode in ("trend", "both"):
            # `trend_tol`（用户 2026-08-10）：走势条件的容差。判据由 `收盘 > MA20` 放宽为
            # `收盘 > MA20 × (1 − tol)`，`MA20 > MA60` 同样处理。**动机是执行时点差而非选股**——
            # 信号定义在收盘，而用户在盘中下单，收盘前跨越均线的票在盘中看不到（判例：
            # 特宝生物 2026-08-10 当日 +4.31%，尾盘才收在 MA20 上方 +0.26%）。
            # **注意容差不消除边界，只是把边界挪个位置**：新线附近照样有票在盘中与收盘之间翻转。
            # 本参数能回答的是「放松到这个程度策略本身还成不成立」，不是「能不能消除时点差」。
            k = 1.0 - trend_tol
            # `addon_trend="ma-only"`（用户 2026-08-15）：**已有持仓的加仓放宽走势条件**——
            # 只要 `MA20 > MA60`（趋势还在）就继续定投，不再要求 `收盘 > MA20`。
            # 新建仓不受影响，仍须 `收盘 > MA20 > MA60`。
            # 语义是「建仓那一刻要确认趋势成立，此后回踩不打断定投」；
            # **它必然放大回撤**——回踩途中继续投钱，而止损仍是唯一的截断（见 §9.3.5）。
            def _trend_ok(r):
                ma = mas.get(r[0], {}).get(sig_day)
                if not ma or not all(w in ma for w in trend_ma):
                    return False
                if len(trend_ma) >= 2 and not ma[trend_ma[0]] > ma[trend_ma[1]] * k:
                    return False
                if addon_trend == "ma-only" and r[0] in portfolio.lots:
                    return True                      # 已持仓：只看均线排列，不看价格位置
                return r[1] > ma[trend_ma[0]] * k
            eligible = [r for r in eligible if _trend_ok(r)]
        if candidate_log is not None:
            # 研究开关（`--candidate-log`，2026-08-23 集中度核对）：记下当日合格集前十的排序，供
            # 「rank 1 vs rank 2~5 前向收益」事件研究。**按严格判据**（收盘>MA20>MA60）记，
            # 不沿用持仓加仓的 ma-only 放宽，使记录与组合路径无关；相关性过滤在其后、也不进记录。
            _k = 1.0 - trend_tol
            _strict = []
            for r in eligible:
                _ma = mas.get(r[0], {}).get(sig_day) or {}
                if strategy == "trend" and entry_mode in ("trend", "both") and trend_ma \
                        and not (trend_ma[0] in _ma and r[1] > _ma[trend_ma[0]] * _k):
                    continue
                _strict.append(r)
            for _rank, r in enumerate(_strict[:10], 1):
                candidate_log.writerow([sig_day, day, _rank, r[0], f"{r[1]:.4f}", f"{r[2]:.4f}",
                                        f"{r[3]:.4f}", int(r[0] in portfolio.lots), len(_strict)])
        if entry_filter == "stabilized" and lows is not None:
            eligible = [r for r in eligible
                        if stabilized(lows.get(r[0], {}), day_index[0].get(r[0], []),
                                      day_index[1].get(r[0], {}), day)]
        # ---- 簇内升级模式（用户 2026-08-09 提出的完整方案）
        # 与既有「换仓 + 相关性过滤」的根本差别：**相关性在这里是「替换谁」的判据，
        # 不是「排除谁」的过滤器**。既有口径下高相关候选会触发卖出**空间最小的持仓**
        # （可能与它毫不相关），等于用分散度换便宜；此处改为卖出**与它同簇的那只**，
        # 敞口结构不变、只把簇内的持仓换成更便宜的一只。持仓个数不设上限，由簇的数量自然决定。
        #
        # 每日三步：
        #   ① 备选 = 空间 ≥ `cluster_min_upside` 的合格候选（空间作门槛，不作排序上限）
        #   ② 在备选内部两两去相关（**不看持仓**），得到当日买入备选
        #   ③ 逐个决定：与某持仓相关性 > `cluster_delta` 且更便宜 → 换掉那只；
        #      与任何持仓都不强相关 → 直接建仓或加仓；簇内已有更便宜的 → 本日不买
        if cluster_swap and eligible:
            cands = [r for r in eligible if (1.0 / r[3] - 1.0) >= cluster_min_upside]
            picks: list = []
            for r in cands[:scan_depth]:
                if corr is not None and max_corr and any(
                        (v := corr.get(r[0], q[0], day)) is not None and v > max_corr for q in picks):
                    continue
                picks.append(r)
            final = []
            cluster_reduced: set[str] = set()
            for r in picks:
                code = r[0]
                if code in portfolio.lots:
                    final.append(r)                      # 已持仓：继续加仓
                    continue
                cand_score = scores.get(code, r[3]) if rank_mode != "pv" else r[3]
                kin = []
                if corr is not None:
                    for held in portfolio.lots:
                        if held not in today:
                            continue
                        v = corr.get(code, held, day)
                        if v is not None and v > cluster_delta:
                            kin.append((scores.get(held, today[held][2])
                                        if rank_mode != "pv" else today[held][2], held))
                if not kin:
                    final.append(r)                      # 无同簇持仓：直接建仓
                    continue
                worst_ratio, worst = max(kin)            # 同簇里最贵的那只
                if worst_ratio - cand_score < swap_margin:
                    continue                             # 簇内已有更便宜的，本日不买
                price = fill_price(worst, marks.get(worst))
                if not price:
                    continue
                # v2.78：簇内升级同样支持「减一档」（用户 2026-08-10 澄清口径）。
                # 原实现是整仓卖出，与 v2.74 已否定的换仓整仓卖出同形——两者砸掉的都是
                # §12.3 里正在复利的仓位。`cluster_reduced` 保证同一只每日至多被削一档。
                lot_w = portfolio.lots[worst]
                if swap_partial and worst not in cluster_reduced:
                    shares = sell_shares(budget / price, lot_w.shares, price, lot_size, res_floor(price))
                    if (not shares and lot_ratio_cooldown and lot_size
                            and lot_w.shares >= lot_size
                            and lot_ratio_ready(lot_counters, worst, price * lot_size, budget)):
                        shares = lot_size if lot_w.shares - lot_size >= lot_size else lot_w.shares
                    if not shares:
                        continue                     # 一手都减不动 → 本日不升级
                    cluster_reduced.add(worst)
                    if shares < lot_w.shares * 0.999:
                        stats["簇内升级·减一档"] += 1
                        lot_w.shares -= shares
                        portfolio.cash += shares * price - trade_fee(shares * price, day, "sell")
                        lot_w.proceeds += shares * price
                        lot_w.sells += 1
                        turnover += shares * price
                    else:
                        turnover += lot_w.shares * price
                        close_lot(portfolio, worst, day, price, ledger=ledger,
                                  reason=f"同簇升级·余额不足一档清仓：让位给{code}")
                elif swap_partial:
                    continue                         # 本日已削过这只，不重复
                else:
                    turnover += lot_w.shares * price
                    close_lot(portfolio, worst, day, price, ledger=ledger,
                              reason=f"同簇升级：让位给更便宜的{code}")
                sell_count += 1
                final.append(r)
            eligible = final
        # 换仓：想买却买不下（没钱或槽位满）时，把**空间最小**的持仓换成**空间更大**的候选。
        # `swap_margin` 是防抖阈值——两者 P/V 差不到这个数就不换，否则每天的微小排名波动
        # 都会触发一次双边交易。
        # `swap_targets`：本日因「空间更大」而触发了卖出的候选。**换仓块在相关性过滤之前执行**，
        # 故它可以为一只随后被相关性挡掉的候选腾位——卖了却买不进，钱转投下一个不相关的候选。
        # 用户 2026-08-09 追问的正是这个口径。`swap_bypass_corr` 打开后，已经为之腾过位的候选
        # 豁免相关性检查：既然已经付出了卖出的代价，就该买到它。
        swap_targets: set[str] = set()
        reduced_today: set[str] = set()      # 同一只每日最多被换仓减一档，防止一天削十次
        # 簇内升级之后仍保留原换仓作为**兜底**：用户方案里「没有强相关持仓就直接建仓或加仓」
        # 隐含了「有钱」这个前提，而簇内升级是自筹资金的（卖一只买一只），**不产生新增现金**。
        # 缺了兜底，资金打满后组合就冻住——实测换手由 200.9% 塌到 17.6%、买入 2145→474 笔。
        # 超额授信期间（常规卖出款还过仍超额）：剩余授信为 0、现金为 0 → 不可能新增买入；换仓照常触发，
        # 但换仓卖出款**同样先还超额负债**（用户 2026-08-22 裁定：「这是融资的代价——净资产下跌、想换仓，
        # 就会出现卖出后因授信降低而无法买入；必须先保证负债不超过净资产×授信比例，才可以进行任何其他买入」）。
        # 实际效果：超额期间每日卖出一档弱势持仓去还款、买不进新票，直到负债回到额度内——这是杠杆账户
        # 在回撤里的真实去杠杆过程（2019-05 起点实测期末 2,762 → 763 万）。曾试过的「换仓款留给置换买入」
        # 口径已按用户裁定撤回。
        if credit_over_limit == "repay" and credit_ratio > 0 and portfolio.debt > credit_limit + 1e-6:
            stats["超额授信·当日无新增买入"] += 1
        if swap and eligible:
            for code, close, value, ratio in eligible[:max_positions]:
                if code in portfolio.lots:
                    continue
                # `swap_trigger`（OI-081，用户 2026-08-22 裁定）：`power`（缺省）＝按 §10.2 可用资金
                # （现金＋剩余授信）不足一档才换仓——授信还有余量时先融资买；`cash`＝v4.39 前旧口径，
                # 只看现金、不计剩余授信，只用于复现旧读数。
                funds = buying_power(portfolio, credit_limit) if swap_trigger == "power" else portfolio.cash
                blocked = funds < (lump_sum or budget) or len(portfolio.lots) >= max_positions
                if not blocked:
                    break
                # 配置通道的持仓**不作为换仓的卖出源**——否则通道刚买进来就会被主排序换掉，
                # 额度形同虚设（§12.56.2 实测：换仓正是终结长期赢家的那条路径）。
                # 分位口径下换仓比的是**分位**，`swap_margin` 的单位随之变成分位点
                # （0.15 = 15 个分位点），不再是 `P/V` 的差值。历史不足而算不出分位的持仓
                # **不作为卖出源**——判不了贵贱就不该被判成「最贵的那个」而被换掉。
                # `swap_require_weak`（用户 2026-08-15）：**只换走势已经走坏的持仓**——
                # 卖出源须同时满足 `收盘 < MA20`。动机是 §12.56.2 那条实测：
                # 换仓是终结长期赢家的唯一路径，而「更便宜的候选出现」与「这只该卖」是两件事。
                # 加上这个条件后，涨势中的持仓不会仅仅因为排名靠后就被换掉。
                # **判据用信号日的收盘与均线**，与买入端、减持闸门同源。
                held = [((pcts[c] if gate == "self-pct" else
                          (scores.get(c, today[c][2]) if rank_mode != "pv" else today[c][2])), c)
                        for c in portfolio.lots if c in today
                        and (gate != "self-pct" or c in pcts)
                        and (not swap_require_weak
                             or ((_m := mas.get(c, {}).get(sig_day, {})).get(swap_weak_ma) is not None
                                 and today[c][0] < _m[swap_weak_ma]))
                        # `swap_out_min_pv`（用户 2026-08-15：「只有高估严重了才允许换仓，
                        # 而不是仅仅排序变了就轻易地换」）：卖出源还须自身 `P/V ≥ 阈值`。
                        # 与 `swap_margin`（候选须比持仓便宜出边际）正交——那是**相对**条件，
                        # 这是**绝对**条件：持仓本身不算贵时，谁更便宜都不换。缺省 0 = 关。
                        and (not swap_out_min_pv or today[c][2] >= swap_out_min_pv)
                        and c not in quota_hold_today
                        and not (hold_strong in ("swap", "both") and strong_bull(c, day))]
                # `gain_sell`（用户 2026-08-22 实验）：**涨幅 ≥ G 的持仓也是换仓卖出源**——不比 P/V 边际，
                # 取涨幅最大的一只让位（当日已减过的不重复选）；`gated` 沿用 `swap_require_weak` 的弱势要求，
                # `ungated` 不要求。没有这类持仓时回到现行的「最贵且弱势」选法。
                gain_src = []
                if gain_sell:
                    for c, l in portfolio.lots.items():
                        if (c not in today or l.avg_cost <= 0 or c in quota_hold_today
                                or c in reduced_today or today[c][0] < l.avg_cost * (1.0 + gain_sell)):
                            continue
                        if gain_sell_mode == "gated" and swap_require_weak:
                            _m = mas.get(c, {}).get(sig_day, {})
                            if _m.get(swap_weak_ma) is None or today[c][0] >= _m[swap_weak_ma]:
                                continue
                        gain_src.append((today[c][0] / l.avg_cost, c))
                swap_tag = ""
                if gain_src:
                    worst = max(gain_src)[1]
                    swap_tag = f"·涨幅≥{gain_sell:.0%}让位"
                    stats[f"涨幅≥{gain_sell:.0%}·换仓让位"] += 1
                else:
                    if not held:
                        break
                    worst_ratio, worst = max(held)
                    cand_score = (pcts[code] if gate == "self-pct" else
                                  (scores.get(code, ratio) if rank_mode != "pv" else ratio))
                    if worst_ratio - cand_score < swap_margin:
                        break
                price = fill_price(worst, marks.get(worst))
                if not price:
                    break
                # `swap_partial`（用户 2026-08-09）：换仓由**整仓卖出**改为**按定投同速减一档**。
                # **仅在「只差钱、槽位没满」时适用**——槽位满时减仓不腾出槽位，新标的照样买不进
                # （买入循环里 `code not in lots and len(lots) >= max_positions` 会挡下），
                # 只会每天空转地削持仓。故槽位满时仍整仓卖出。
                lot_worst = portfolio.lots[worst]
                partial = swap_partial and len(portfolio.lots) < max_positions and worst not in reduced_today
                shares = (sell_shares(budget / price, lot_worst.shares, price, lot_size, res_floor(price))
                          if partial else lot_worst.shares)
                if (partial and not shares and lot_ratio_cooldown and lot_size
                        and lot_worst.shares >= lot_size
                        and lot_ratio_ready(lot_counters, worst, price * lot_size, budget)):
                    shares = (lot_size if lot_worst.shares - lot_size >= lot_size
                              else lot_worst.shares)
                    stats["高价股·按手换仓"] += 1
                if partial and shares < lot_worst.shares * 0.999:
                    stats["换仓·减一档"] += 1
                    lot_worst.shares -= shares
                    portfolio.cash += shares * price - trade_fee(shares * price, day, "sell")
                    lot_worst.proceeds += shares * price
                    lot_worst.sells += 1
                    turnover += shares * price
                    log_partial_sell(ledger, day, worst, shares, price, f"换仓·减一档{swap_tag}：让位给{code}")
                    reduced_today.add(worst)
                else:
                    stats["换仓·整仓卖出"] += 1
                    turnover += lot_worst.shares * price
                    close_lot(portfolio, worst, day, price, ledger=ledger, reason=f"换仓{swap_tag}：让位给空间更大的{code}")
                sell_count += 1
                swap_targets.add(code)
        # 换仓卖出款同样先还超额负债（§10.2，用户 2026-08-22 裁定），再进入买入段
        if credit_over_limit == "repay" and credit_ratio > 0:
            if repay_over_limit(portfolio, credit_limit) > 0:
                stats["超额授信·换仓款先还"] += 1
        # ---- 档位排序偏置（用户 2026-08-08）
        if tier_mode == "bonus":
            eligible.sort(key=lambda r: -(1.0 / r[3] + TIER_BONUS.get(tiers.get(r[0], DEFAULT_TIER), 0.0)))
        elif tier_mode == "quota":
            # 各档位各自排序，再按配额取——避免某一档因整体估值水平不同而被系统性挤出
            picked, used = [], collections.Counter()
            for r in eligible:
                t = tiers.get(r[0], DEFAULT_TIER)
                if used[t] < TIER_QUOTA.get(t, 0):
                    picked.append(r)
                    used[t] += 1
            picked += [r for r in eligible if r not in picked]
            eligible = picked

        # ---- 相关性过滤：**贪心**地沿排序往下走，与已选/已持仓相关性超阈值的跳过，
        # 顺位补下一名（用户 2026-08-08：「第一和第五相关性很强则跳过第五，考虑第 21 名」）。
        # OI-037（用户 2026-08-19 指令）：`--corr-conflict` 提供另两种处理——与**在手持仓**
        # 强相关时不一律跳过，而是与最相关的那只二选一：`swap_space` 比便宜（候选 `P/V`
        # 低出 `swap_margin` 才换）、`swap_strength` 比走势（近 N 日送转折算收益率更高者留），
        # 换出方减一档、余仓不足一手清仓——与 §9.3.2 换仓同一卖出机制。
        # 与**已选候选**（未持仓）冲突仍一律跳过：两只都没买时没有「换」的对象。
        if max_corr and corr is not None and not cluster_swap:
            def trailing_return(code: str, upto: str, n: int) -> float | None:
                rets = corr.returns.get(code)
                days = corr._days.get(code)
                if not rets or not days:
                    return None
                cut = bisect.bisect_right(days, upto)
                if cut < n:
                    return None
                acc = 1.0
                for d in days[cut - n: cut]:
                    acc *= 1.0 + rets[d]
                return acc - 1.0

            chosen, anchors = [], list(portfolio.lots)
            corr_reduced: set[str] = set()
            for r in eligible[:scan_depth]:
                if len(chosen) >= max_positions:
                    break
                if r[0] in portfolio.lots:
                    chosen.append(r)          # 已持仓的继续加仓，不受相关性约束
                    continue
                held_conf = [(v, other) for other in anchors if other != r[0]
                             and (v := corr.get(r[0], other, day)) is not None and v > max_corr]
                cand_conf = any((v := corr.get(r[0], x[0], day)) is not None and v > max_corr
                                for x in chosen if x[0] not in portfolio.lots)
                if not held_conf and not cand_conf:
                    chosen.append(r)
                    continue
                if r[0] in swap_targets:
                    stats["换仓目标被相关性挡下"] += 1
                    if swap_bypass_corr:
                        chosen.append(r)
                        continue
                if corr_conflict == "skip" or cand_conf or not held_conf:
                    continue
                _, h = max(held_conf)                     # 与候选最相关的在手持仓
                if h in corr_reduced or h in quota_hold_today or h not in portfolio.lots:
                    continue
                lot_h = portfolio.lots[h]
                price_h = fill_price(h, marks.get(h))
                if not price_h:
                    continue
                if corr_conflict == "swap_space":
                    ratio_h = today[h][2] if h in today else None
                    decided = ratio_h is not None and (ratio_h - r[3]) >= swap_margin
                else:                                     # swap_strength
                    rc = trailing_return(r[0], day, corr_strength_days)
                    rh = trailing_return(h, day, corr_strength_days)
                    decided = rc is not None and rh is not None and rc > rh
                if not decided:
                    continue
                shares = sell_shares(budget / price_h, lot_h.shares, price_h, lot_size, res_floor(price_h))
                if not shares:
                    continue
                corr_reduced.add(h)
                if shares < lot_h.shares * 0.999:
                    stats[f"相关性冲突·{corr_conflict}·减一档"] += 1
                    lot_h.shares -= shares
                    portfolio.cash += shares * price_h - trade_fee(shares * price_h, day, "sell")
                    lot_h.proceeds += shares * price_h
                    lot_h.sells += 1
                    turnover += shares * price_h
                else:
                    stats[f"相关性冲突·{corr_conflict}·余仓不足清仓"] += 1
                    turnover += lot_h.shares * price_h
                    close_lot(portfolio, h, day, price_h, ledger=ledger,
                              reason=f"相关性冲突·{corr_conflict}：让位给{r[0]}")
                    anchors.remove(h)
                sell_count += 1
                chosen.append(r)
            eligible = chosen

        # ---- 配置通道（用户 2026-08-15 指令；OI-046 末段那条唯一未实测的方向）----
        # 给一批「白马/成长」单开一条**与 `P/V` 排序并行**的固定额度：成员只要**走势闸门开着**
        # 就可以买，**不要求过买入线、不进主排序、不受相关性过滤**，直到该组市值占净资产
        # 达到 `quota_pct` 为止；额度用满后成员回落为普通候选。
        # **这等于一个组合里跑两套逻辑**，故只在显式给 `--quota-pct` 时启用（缺省关闭）。
        #
        # 实现上**不另写一套下单逻辑**——只把够格的成员插到 `eligible` 最前面，整手取整、
        # 比例冷却、单票上限、建仓日止损、流水记账全部沿用下面那个循环。多写一套的风险
        # 远大于收益（§13 第 5 条：同一阈值写两遍，迟早两边不一样）。
        quota_room = 0.0
        if quota_today and not fence_on:
            held = sum(lot.shares * marks[c] for c, lot in portfolio.lots.items()
                       if c in quota_today and c in marks)
            quota_room = equity * quota_pct - held
            if quota_room > 0:
                k = 1.0 - trend_tol
                picks = [r for r in pool if r[0] in quota_today
                         and (ma := mas.get(r[0], {}).get(sig_day))
                         and all(w in ma for w in trend_ma)
                         and r[1] > ma[trend_ma[0]] * k
                         and (len(trend_ma) < 2 or ma[trend_ma[0]] > ma[trend_ma[1]] * k)]
                picks.sort(key=lambda r: r[3])          # 组内仍按 P/V 升序，只是不与主池竞争
                already = {r[0] for r in picks}
                eligible = picks + [r for r in eligible if r[0] not in already]
                stats["配置通道·当日候选"] += len(picks)

        for code, close, value, ratio in eligible[:max_positions]:
            if buying_power(portfolio, credit_limit) <= 0:
                break
            # 配置通道的额度用完就不再按通道买；该成员此后只能走普通路径（即需过买入线）。
            over_line = ((pcts.get(code) is None or pcts[code] > buy_pct) if pct_buy_gate
                         else ratio > buy_line(code))
            if code in quota_today:
                if quota_room <= 0 and over_line:
                    continue
            elif quota_pct > 0 and over_line:
                continue                      # 通道把成员插到了队首，非成员仍须过买入线
            # 走势组默认一笔建仓（总资产 ÷ 持仓上限）且不加仓；`trend_tranche` 打开后改为
            # **与估值组同一套定投**——只要当日仍满足「P/V 合格 且 收盘>MA20>MA60」就继续买入
            # 总资产 × x%。用户 2026-08-09：「走势满足要求的情况下分批进行建仓」。
            fill = fill_price(code, close) or close
            tranche = trend_tranche and strategy == "trend"
            if ((strategy == "trend" and not tranche) or lump_sum) and code in portfolio.lots:
                continue                      # 一笔建仓：不加仓
            # 建仓跳过（用户 2026-08-20）：只判**新建仓**，加仓不设锚、不受影响；该笔放弃后
            # 资金顺位给下一名（与 §10.1 过滤同型）。成交日停牌回落信号日价的情形不在此列
            # （exec 日无均线行）。`skip`（现行，§9.3.1 走势行）：T 日收盘对成交日 MA60；
            # `skip_fill`（OI-092① 研究口径，§12.126 A/B 主读数 −0.76 不采纳）：成交日收盘
            # （`fill`）对成交日 MA60，触发频次远高于 skip。
            if entry_below_ma60 in ("skip", "skip_fill") and code not in portfolio.lots:
                ma60_exec = (mas.get(code, {}).get(day) or {}).get(60, 0.0)
                ref = fill if entry_below_ma60 == "skip_fill" else close
                if ma60_exec and ref < ma60_exec:
                    stats["建仓日收盘<当日MA60·跳过"] += 1
                    continue
            # `addon_max_gain`（用户 2026-08-22 实验）：**信号日收盘 ≥ 持仓均价 × (1 + G) 不再加仓**，
            # 资金顺位下一名；新建仓不受影响。0＝关（逐位不变）。
            if addon_max_gain and code in portfolio.lots:
                _held = portfolio.lots[code]
                if _held.avg_cost > 0 and close >= _held.avg_cost * (1.0 + addon_max_gain):
                    stats[f"加仓·涨幅≥{addon_max_gain:.0%}·跳过"] += 1
                    continue
            avail = buying_power(portfolio, credit_limit)
            if lump_sum:
                amount = min(equity * lump_sum, avail)
            else:
                amount = min(budget if (strategy == "valuation" or tranche)
                             else equity / max_positions, avail)
            if amount <= 0 or code not in portfolio.lots and len(portfolio.lots) >= max_positions:
                continue
            # 单票上限：**只挡加仓、不强制减持**——已有仓位因上涨超限是「买入上限」管不着的，
            # 强行削回去等于给策略偷加了一条止盈规则。
            if position_cap:
                held_value = portfolio.lots[code].shares * close if code in portfolio.lots else 0.0
                room = equity * position_cap - held_value
                if room <= 0:
                    continue
                amount = min(amount, room)
            # A 股买入必须是 100 股整数倍。`lot_size` 打开后按手向下取整，**买不足一手就跳过**
            # ——这才是真实可执行的口径。一档金额买不起一手的高价股（茅台一手 13 万）会被自然排除，
            # 这不是缺陷而是事实：一档金额本来就装不下这类标的。
            if lot_size:
                lots_n = int(amount // (fill * lot_size))
                if lots_n <= 0:
                    # 高价股（茅台一手 13 万）一档金额买不起一手。**不因此放弃建仓**，改为
                    # 每次买一手、隔 `min_lot_cooldown` 个交易日再买下一手（用户 2026-08-09 指令）。
                    # 冷却期是必需的：不设的话一手会天天买，等于把该股的定投速度放大到一档以上。
                    # v2.77 起冷却由「自然日」改为「合格次数」（`lot_ratio_ready`，§9.3.3）；
                    # `--min-lot-cooldown` 保留为旧口径，两者互斥，都不给则不建仓（原行为）。
                    if lot_ratio_cooldown:
                        ready = lot_ratio_ready(lot_counters, code, fill * lot_size, budget)
                    else:
                        prior = last_buy.get(code)
                        ready = (min_lot_cooldown
                                 and (prior is None or _days_between(prior, day) >= min_lot_cooldown))
                    if ready and buying_power(portfolio, credit_limit) >= fill * lot_size:
                        lots_n = 1
                        stats["高价股·按手建仓"] += 1
                    else:
                        stats["买不足一手·跳过"] += 1
                        continue
                shares = lots_n * lot_size
                amount = shares * fill
            else:
                shares = amount / fill
            # 割肉买回：**只在该股重新合格的那一天触发一次**，买回被割掉的全部股数（现金不足则买满为止）。
            # 与常规定投的区别是它不受一档限制——割肉时卖掉的是整仓，补回也应是整仓。
            if rebuy == "lump" and cut_shares.get(code) and code not in portfolio.lots:
                want = cut_shares.pop(code)
                if lot_size:
                    want = int(want // lot_size) * lot_size
                afford = (min(want, buying_power(portfolio, credit_limit) / fill)
                          if fill > 0 else 0.0)
                if lot_size:
                    afford = int(afford // lot_size) * lot_size
                if afford > 0:
                    shares, amount = afford, afford * fill
                    stats["割肉买回"] += 1
            lot = portfolio.lots.get(code)
            if lot is None:
                # 止损价取**成交日**均线。成交日停牌时 `mas[code][day]` 整条缺失，
                # `ma.get(20, 0.0)` 会返回 0，而 `lot.entry_stop` 为 0 时止损分支被 falsy 短路
                # ——**该仓从此永远不受止损约束，且没有任何提示**（§13 第 3 条的静默失效）。
                # 实测 2002 起点 1,697 个周期里有 4 个如此。成交价此时已回落到信号日收盘，
                # 故止损价一并回落到信号日均线，两者同源。
                ma = mas.get(code, {}).get(day) or mas.get(code, {}).get(sig_day, {})
                if not mas.get(code, {}).get(day):
                    stats["成交日无均线·止损价回落信号日"] += 1
                lot = Lot(code=code, entry_date=day, entry_ratio=ratio, entry_value=value,
                          entry_band_low=(1 - width) * value, entry_band_high=(1 + width) * value,
                          entry_upside=value / fill - 1, peak_intrinsic=value)
                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(
                    ma, fill if entry_below_ma60 == "skip_fill" else close, stop_ma)
                portfolio.lots[code] = lot
            lot.avg_cost = ((lot.avg_cost * lot.shares + amount) / (lot.shares + shares)
                            if lot.shares + shares > 0 else 0.0)   # 持仓均价：买入加权、减持不变
            lot.shares += shares
            lot.invested += amount
            lot.buys += 1
            if code in quota_today:
                quota_room -= amount          # 额度按**买入金额**扣，与上面按市值算余额同一把尺
                stats["配置通道·成交"] += 1
            fee = trade_fee(amount, day, "buy")
            draw_credit(portfolio, amount + fee, credit_limit)   # 现金不足即动用授信
            portfolio.cash -= amount + fee
            last_buy[code] = day
            if ledger is not None:
                # **price 必须记 `fill` 不是 `close`**：`close` 是信号日收盘，而这笔单成交在
                # `fill`（`--exec-delay 1` 下即成交日收盘）。流水是「人工核对用」的凭证，
                # 记错价会让对账人得出与实际不同的成本；成交本身一直用的是 `fill`（`shares = amount/fill`），
                # 故本次修正只改打印列，不改任何回测结果。
                ledger.append({"date": day, "security_code": code, "action": "买入",
                               "shares": f"{shares:.0f}", "price": f"{fill:.3f}",
                               "amount": f"{amount:.0f}", "pv_ratio": f"{ratio:.4f}",
                               "intrinsic_value": f"{value:.3f}",
                               "reason": "定投加仓" if lot.buys > 1 else "首次建仓"})
            buy_count += 1
            turnover += amount

        # **收盘净值必须对当日新建的仓位也取到价**：`marks` 是开盘前按当时持仓建的，
        # 当天新买的票不在里面，`equity()` 会把它们记作 0——现金花掉了、股票却不算数，
        # 次日再凭空出现。首版即此错，实测造成单日 −39.2% 紧接 +41.6% 的假波动
        # （组合年化波动被抬到 70%+，54 个交易日单日振幅 >20%）。
        for code in portfolio.lots:
            if code not in marks:
                price = today[code][0] if code in today else prices.get(code, {}).get(day)
                if price:
                    last_price[code] = price
                if code in last_price:
                    marks[code] = last_price[code]
        # `--margin-ratchet`（纯研究开关，§12.70）：日终剩余现金先还融资，不留到下一笔买入。
        repay_debt(portfolio, margin_ratchet)
        # **无单票上限的实际后果必须可量**（§9.3.1 单票机械上限由 `--position-cap` 给出，不给即无上限）：逐日记下最大单股权重
        # 与前三大合计，写进净值曲线。不记的话「集中度」只能靠事后从流水重建，而流水按构造
        # 缺部分减持（本次一并补上），重建值会系统性偏高。
        eq_now = portfolio.equity(marks)
        weights = sorted((lot.shares * marks[c] / eq_now
                          for c, lot in portfolio.lots.items() if c in marks and eq_now > 0),
                         reverse=True)
        equity_curve.append((day, eq_now, portfolio.cash, len(portfolio.lots),
                             portfolio.debt, portfolio.margin_ratio(marks),
                             weights[0] if weights else 0.0, sum(weights[:3])))

    # 收尾：按最后一日收盘价清算未平仓，使逐周期收益可比
    if days:
        last = days[-1]
        for code in list(portfolio.lots):
            price = prices.get(code, {}).get(last)
            if price:
                close_lot(portfolio, code, last, price, "回测截止清算")
    return {"equity": equity_curve, "closed": portfolio.closed, "fees": FEES["paid"] - fees0,
            "buys": buy_count, "sells": sell_count, "turnover": turnover,
            "margin_events": margin_events, "min_margin_ratio": min_ratio,
            "min_margin_day": min_ratio_day, "interest_paid": portfolio.interest_paid,
            "final_debt": portfolio.debt}


# ------------------------------------------------------------------ 指标
def period_returns(curve: list[tuple[str, float, float, int]], key) -> list[tuple[str, float]]:
    """分期收益。**基数是上一期末**，不是本期首日——否则跨期当日的涨跌被两边同时排除，
    逐期链乘对不上全期总收益（2002 起点上曾差出 572x vs 692x，见回测日志 §12.24.5）。"""
    last: dict[str, float] = {}
    for day, equity, *_rest in curve:
        last[key(day)] = equity
    base = curve[0][1] if curve else 0.0
    out: list[tuple[str, float]] = []
    for label in sorted(last):
        out.append((label, last[label] / base - 1 if base else float("nan")))
        base = last[label]
    return out


def max_drawdown(curve) -> tuple[float, str, str]:
    peak, worst, start, end, peak_day = -1.0, 0.0, "", "", ""
    for day, equity, *_r in curve:
        if equity > peak:
            peak, peak_day = equity, day
        elif peak > 0:
            drop = 1 - equity / peak
            if drop > worst:
                worst, start, end = drop, peak_day, day
    return worst, start, end


def month_end_indices(curve) -> list[int]:
    """每个自然月最后一个交易日在净值曲线里的下标（滚动窗口的锚点）。

    曲线末尾那个月只有在「本月剩余日历日全是周末」时才算月末——`--until 2026-08-07` 这种
    截断处的残月不是月末，不能当窗口末日（否则最后一个窗口短了三周还按整月记）。
    """
    idx = [i for i in range(len(curve) - 1) if curve[i][0][:7] != curve[i + 1][0][:7]]
    if curve:
        last = date.fromisoformat(curve[-1][0])
        days_in_month = calendar.monthrange(last.year, last.month)[1]
        if all(date(last.year, last.month, d).weekday() >= 5
               for d in range(last.day + 1, days_in_month + 1)):
            idx.append(len(curve) - 1)
    return idx


def rolling_windows(curve, years: int = 3,
                    risk_free: list[tuple[str, float]] | None = None) -> list[dict]:
    """滚动 `years` 年窗口，**月末锚定**：窗口末日 = 每个自然月最后一个交易日，窗口首日 =
    `years×12` 个月前同月的最后一个交易日（收益从首日收盘算起），年化指数用实际日历年数
    （天数/365.25），回撤与 Sharpe 用窗口内**逐日**净值（月末净值会低估日内回撤，本策略带授信
    与 130% 平仓线，日度才真实）。每个窗口给 {end, start, cagr, mdd, calmar, sharpe}。

    用户 2026-08-23 裁定由「起点后每 20 个交易日推一格、窗长 5×244 个交易日」改为月末锚定：
    去掉 244 天/年的假设（A 股一年 242~250 个交易日，旧窗长与 5 个日历年差 ±2 周），并让
    23 个起点、各臂的窗口末日完全对齐——同一日历窗口可以跨起点去重比较。

    **与全期 Calmar 的区别要说清**：`summarize` 里的 `Calmar = 全期CAGR / 全期最大回撤`，
    它只有**一个**观测值，且分母是整段历史里最深的那一次——起点稍微一动就可能换成另一次
    崩盘，数值随之跳变（§12.9.2 已实测过这种路径敏感）。滚动口径给出**一串**观测值，
    可以看中位数与分布，比单点稳得多。但窗口 59/60 重叠，不是独立样本（§12.1 第 5 款）。
    """
    ends = month_end_indices(curve)
    by_month = {curve[i][0][:7]: i for i in ends}
    rf_dates = [d for d, _ in risk_free] if risk_free else []
    rf_vals = [r for _, r in risk_free] if risk_free else []
    rf_all = statistics.fmean(rf_vals) if rf_vals else 0.0
    out: list[dict] = []
    for i in ends:
        end_day = curve[i][0]
        y, m = int(end_day[:4]), int(end_day[5:7])
        j = by_month.get(f"{y - years:04d}-{m:02d}")
        if j is None:
            continue
        first, last = curve[j][1], curve[i][1]
        if first <= 0 or last <= 0:
            continue
        start_day = curve[j][0]
        span = (date.fromisoformat(end_day) - date.fromisoformat(start_day)).days / 365.25
        cagr = (last / first) ** (1 / span) - 1
        peak, worst, prev, rets = -1.0, 0.0, 0.0, []
        for _d, equity, *_r in curve[j:i + 1]:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, 1 - equity / peak)
            if prev > 0:
                rets.append(equity / prev - 1)
            prev = equity
        vol = statistics.pstdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) > 2 else float("nan")
        if rf_dates:
            lo, hi = bisect.bisect_left(rf_dates, start_day), bisect.bisect_right(rf_dates, end_day)
            rf = statistics.fmean(rf_vals[lo:hi]) if hi > lo else rf_all
        else:
            rf = 0.0
        out.append({"end": end_day, "start": start_day, "cagr": cagr, "mdd": worst,
                    "calmar": cagr / worst if worst > 0 else float("nan"),
                    "sharpe": (cagr - rf) / vol if vol == vol and vol > 0 else float("nan")})
    return out


def summarize(name: str, result: dict, capital: float, benchmark: dict[str, float],
              risk_free: list[tuple[str, float]]) -> dict:
    curve = result["equity"]
    if not curve:
        return {}
    final = curve[-1][1]
    years = len(curve) / TRADING_DAYS
    cagr = (final / capital) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    rets = [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve)) if curve[i - 1][1] > 0]
    vol = statistics.pstdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) > 2 else float("nan")
    worst, dd_start, dd_end = max_drawdown(curve)
    rf = statistics.fmean([r for _, r in risk_free]) if risk_free else 0.0
    sharpe = (cagr - rf) / vol if vol and not math.isnan(vol) and vol > 0 else float("nan")
    exposure = statistics.fmean([1 - c / e for _d, e, c, *_r in curve if e > 0])

    closed = result["closed"]
    wins = [l for l in closed if l.proceeds > l.invested]
    profits = [l.proceeds - l.invested for l in closed]
    holding = [_days_between(l.entry_date, l.exit_date) for l in closed if l.exit_date]

    bench = ""
    if benchmark:
        pair = [(d, benchmark[d]) for d, *_ in curve if d in benchmark]
        if len(pair) > 1:
            # 基准年化须用**基准自身覆盖到的天数**，不能套策略的 years（两者起点可能不同）
            bench_years = len(pair) / TRADING_DAYS
            bench_cagr = (pair[-1][1] / pair[0][1]) ** (1 / bench_years) - 1
            bench = f"{bench_cagr:.2%}（同期超额 {cagr - bench_cagr:+.2%}）"

    # ---- 滚动口径（用户 2026-08-15 指定三条读数：滚动 3 年 / 滚动 5 年 / 逐年；
    # 2026-08-23 改月末锚定并补 P25／最差／滚动 Sharpe，§12.1 第 2 款）。
    # **不再用「某年至今的总收益」判优劣**——那条读数被起点单点决定，
    # 一次崩盘落在窗口内外就能翻转结论（§12.1 多起点纪律的动机就是它）。
    # 主读数 = 滚 5 年 CAGR 中位；坏情形 = 滚 5 年 CAGR P25（140 个月末窗里 P10 只有 14 个观测，
    # P25 更稳）；最差值只有描述意义（它就是历史上最差那一段 5 年，各臂几乎同一事件）；
    # 滚 5 回撤中位作闸门、负窗口占比作否决项（现行授信下几乎恒为 0，没有排序区分力）。
    def _stats(windows):
        g = sorted(w["cagr"] for w in windows)
        d = sorted(w["mdd"] for w in windows)
        c = sorted(w["calmar"] for w in windows if w["calmar"] == w["calmar"])
        sh = sorted(w["sharpe"] for w in windows if w["sharpe"] == w["sharpe"])
        nan = float("nan")
        return {"年化中位": statistics.median(g) if g else nan,
                "年化P25": g[len(g) // 4] if g else nan,
                "年化P10": g[len(g) // 10] if g else nan,
                "年化最差": g[0] if g else nan,
                "回撤中位": statistics.median(d) if d else nan,
                "Calmar中位": statistics.median(c) if c else nan,
                "Calmar_P10": c[len(c) // 10] if c else nan,
                "Calmar_P90": c[-max(1, len(c) // 10)] if c else nan,
                "Sharpe中位": statistics.median(sh) if sh else nan,
                "为负的窗口占比": (sum(1 for v in g if v < 0) / len(g)) if g else nan,
                "窗口数": len(windows)}
    s3 = _stats(rolling_windows(curve, years=3, risk_free=risk_free))
    s5 = _stats(rolling_windows(curve, years=5, risk_free=risk_free))
    # 滚动 10 年：**只有 2009-11 那几条长跑够长**，23 个起点里 2016-11 之后的起点一个 10 年
    # 窗口都凑不出，故该列在多数臂上是空的——**空不等于差，读表时不要把 nan 当成 0**。
    s10 = _stats(rolling_windows(curve, years=10, risk_free=risk_free))
    # 逐年：**只取完整自然年**。起点在 11 月、终点在 8 月，首尾两个残年会把
    # 「两个月的涨幅」当成一年的年化混进中位数里，那是口径错误不是业绩。
    yearly = period_returns(curve, key=lambda d: d[:4])
    first_y, last_y = curve[0][0][:4], curve[-1][0][:4]
    full = [(y, v) for y, v in yearly
            if not (y == first_y and curve[0][0][5:] > "01-10")
            and not (y == last_y and curve[-1][0][5:] < "12-20")]
    yg = sorted(v for _y, v in full)
    return {"策略": name, "期末资产": final,
            "滚动3年Calmar中位": s3["Calmar中位"],
            "滚动3年Calmar_P10": s3["Calmar_P10"],
            "滚动3年Calmar_P90": s3["Calmar_P90"],
            "滚动3年Sharpe中位": s3["Sharpe中位"],
            "滚动3年回撤中位": s3["回撤中位"],
            "滚动3年年化中位": s3["年化中位"],
            "滚动3年年化P25": s3["年化P25"],
            "滚动3年为负的窗口占比": s3["为负的窗口占比"],
            "滚动窗口数": s3["窗口数"],
            "滚动5年年化中位": s5["年化中位"],
            "滚动5年年化P25": s5["年化P25"],
            "滚动5年年化P10": s5["年化P10"],
            "滚动5年年化最差": s5["年化最差"],
            "滚动5年回撤中位": s5["回撤中位"],
            "滚动5年Calmar中位": s5["Calmar中位"],
            "滚动5年Sharpe中位": s5["Sharpe中位"],
            "滚动5年为负的窗口占比": s5["为负的窗口占比"],
            "滚动5年窗口数": s5["窗口数"],
            "滚动10年年化中位": s10["年化中位"],
            "滚动10年年化P10": s10["年化P10"],
            "滚动10年回撤中位": s10["回撤中位"],
            "滚动10年为负的窗口占比": s10["为负的窗口占比"],
            "滚动10年窗口数": s10["窗口数"],
            "逐年收益中位": statistics.median(yg) if yg else float("nan"),
            "逐年收益均值": statistics.fmean(yg) if yg else float("nan"),
            "逐年最差": yg[0] if yg else float("nan"),
            "逐年最好": yg[-1] if yg else float("nan"),
            "逐年为正比例": (sum(1 for v in yg if v > 0)/len(yg)) if yg else float("nan"),
            "完整自然年数": len(yg),
            "总收益": final / capital - 1, "年化": cagr,
            "年化波动": vol, "最大回撤": worst, "回撤区间": f"{dd_start}~{dd_end}",
            "Calmar": cagr / worst if worst else float("nan"), "Sharpe": sharpe,
            # 融资尾部（2026-08-22 授信比例扫描起加，纯追加列；无杠杆时 0／inf）
            "强平次数": len(result.get("margin_events") or []),
            "最低担保比例": result.get("min_margin_ratio", float("inf")),
            "平均仓位": exposure, "周期数": len(closed),
            "胜率": len(wins) / len(closed) if closed else float("nan"),
            "盈亏比": (statistics.fmean([p for p in profits if p > 0]) /
                    abs(statistics.fmean([p for p in profits if p <= 0]))
                    if any(p > 0 for p in profits) and any(p <= 0 for p in profits) else float("nan")),
            "平均持有天数": statistics.fmean(holding) if holding else float("nan"),
            "买入笔数": result["buys"], "卖出笔数": result["sells"],
            "年均换手": (result["turnover"] / years / statistics.fmean([e for _d, e, *_r in curve])
                     if years else float("nan")),
            "累计手续费": result.get("fees", 0.0),
            "手续费占初始本金": result.get("fees", 0.0) / capital if capital else float("nan"),
            "基准年化": bench}


def _days_between(a: str, b: str) -> int:
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


TRADE_FIELDS = ["security_code", "security_name", "entry_date", "exit_date", "holding_days",
                "buys", "sells", "invested", "proceeds", "dividends", "return_pct",
                "max_drawdown_in_cycle", "max_money_drawdown", "entry_stop", "entry_stop_ma", "entry_pv_ratio", "entry_upside", "entry_intrinsic_value",
                "entry_band_low", "entry_band_high", "exit_reason"]


def write_trades(path: Path, lots, names: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for lot in sorted(lots, key=lambda l: l.entry_date):
            writer.writerow({
                "security_code": lot.code, "security_name": names.get(lot.code, ""),
                "entry_date": lot.entry_date, "exit_date": lot.exit_date,
                "holding_days": _days_between(lot.entry_date, lot.exit_date) if lot.exit_date else "",
                "buys": lot.buys, "sells": lot.sells,
                "invested": f"{lot.invested:.2f}", "proceeds": f"{lot.proceeds:.2f}",
                "dividends": f"{lot.dividends:.2f}",
                "return_pct": f"{lot.proceeds / lot.invested - 1:.6f}" if lot.invested else "",
                "max_drawdown_in_cycle": f"{lot.max_drawdown:.6f}",
                "max_money_drawdown": f"{lot.max_money_drawdown:.6f}",
                "entry_stop": f"{lot.entry_stop:.4f}", "entry_stop_ma": lot.entry_stop_ma or "",
                "entry_pv_ratio": f"{lot.entry_ratio:.4f}", "entry_upside": f"{lot.entry_upside:.4f}",
                "entry_intrinsic_value": f"{lot.entry_value:.4f}",
                "entry_band_low": f"{lot.entry_band_low:.4f}",
                "entry_band_high": f"{lot.entry_band_high:.4f}",
                "exit_reason": lot.exit_reason})


def write_equity(path: Path, curve) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "net_equity", "cash", "positions", "cash_ratio",
                         "debt", "margin_ratio", "top1_weight", "top3_weight"])
        for day, equity, cash, count, *rest in curve:
            debt = rest[0] if rest else 0.0
            ratio = rest[1] if len(rest) > 1 else float("inf")
            top1 = rest[2] if len(rest) > 2 else 0.0
            top3 = rest[3] if len(rest) > 3 else 0.0
            writer.writerow([day, f"{equity:.2f}", f"{cash:.2f}", count,
                             f"{cash / equity:.4f}" if equity else "",
                             f"{debt:.2f}", "" if ratio == float("inf") else f"{ratio:.4f}",
                             f"{top1:.4f}", f"{top3:.4f}"])


def write_periods(path: Path, curve) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["period_type", "period", "return_pct"])
        for label, value in period_returns(curve, lambda d: d[:4]):
            writer.writerow(["annual", label, f"{value:.6f}"])
        for label, value in period_returns(curve, lambda d: d[:7]):
            writer.writerow(["monthly", label, f"{value:.6f}"])


def main() -> int:
    parser = argparse.ArgumentParser(description="OI-034 估值组/走势组回测")
    parser.add_argument("--strategy", choices=("valuation", "trend", "both"), default="both")
    parser.add_argument("--x", type=float, nargs="+", default=[1.0, 0.5, 0.1],
                        help="每次调仓占总资产的百分比，可给多个做参数扫描")
    parser.add_argument("--since", default="2000-01-01")
    # 缺省不设截止——跑满逐日状态文件的末行（OI-092④：此前硬编码日期，行情库前进后会静默截断）。
    parser.add_argument("--until", default="9999-12-31")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    mg = parser.add_argument_group("融资（杠杆）")
    mg.add_argument("--credit-ratio", type=float, default=0.0,
                    help="授信额度 ÷ 净资产。用户口径：净资产300万授权200万 → 0.667。0=不用杠杆")
    mg.add_argument("--credit-cap", type=float, default=10_000_000.0,
                    help="授信绝对上限（元），默认 1000 万")
    mg.add_argument("--margin-rate", type=float, default=0.035, help="融资年利率")
    mg.add_argument("--maintenance-ratio", type=float, default=1.30, help="平仓线（担保比例）")
    mg.add_argument("--recover-ratio", type=float, default=1.50,
                    help="强平后需恢复到的担保比例")
    mg.add_argument("--margin-ratchet", action="store_true",
                    help="日终剩余现金先还融资，不留到下一笔买入。**纯研究开关**，用于复现 §12.70 的融资场景\n                         A/B（实测近中性、略负）；不对应任何生效规则——同名的账户级机制已于 2026-08-17 退役")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--width", type=float, nargs="+", default=[0.10],
                        help="带的半宽 w：买入线 1−w、减持线 1+w。可给多个做敏感度")
    parser.add_argument("--use-mos", action="store_true",
                        help="买入线改按档位安全边际 1−MOS（L1 0.90/L2 0.80/L3 0.70）")
    parser.add_argument("--tier-buy-scale", default="", metavar="L1=1.25,L3=0.875",
                        help="研究开关（§12.95）：买入线按档位乘倍数，未列档位为 1.0；缺省空＝原行为")
    parser.add_argument("--tier-sell-scale", default="", metavar="L1=1.5",
                        help="研究开关（§12.95）：减持线按档位乘倍数，未列档位为 1.0；缺省空＝原行为")
    parser.add_argument("--price-stop", action="store_true", help="估值组也用建仓日均线止损")
    parser.add_argument("--stop-ma", type=int, choices=(20, 60), default=20,
                        help="止损均线周期（现行 60）；建仓价已在该均线下方时的处理由 --entry-below-ma60 决定")
    parser.add_argument("--value-stop", type=float, default=0.0,
                        help="基本面退出：内在价值自峰值回落超该比例即清仓，如 0.25")
    parser.add_argument("--no-trend-stop", dest="trend_stop", action="store_false",
                        help="走势组取消建仓日均线止损")
    parser.add_argument("--entry-filter", choices=("none", "stabilized"), default="none",
                        help="stabilized=止跌走稳（近 5 个交易日未创 20 日新低）才允许买入")
    parser.add_argument("--lump-sum", type=float, default=0.0,
                        help="一笔建仓，占总资产的百分比（如 5）；给了就不再定投加仓")
    parser.add_argument("--swap", action="store_true",
                        help="买不下时卖出空间最小的持仓，换空间更大的候选")
    parser.add_argument("--no-swap", dest="swap", action="store_false",
                        help="关掉换仓。`scripts/sweep_backtest_configs.py` 的 BASE 里带着 --swap，"
                             "而 store_true 无法在配置行里撤销，故需要这条显式的关")
    parser.add_argument("--swap-margin", type=float, default=0.10, help="换仓的 P/V 最小改善，防抖")
    parser.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    parser.add_argument("--max-corr", type=float, default=0.0,
                        help="相关性上限，如 0.7；与已选/已持仓相关性超过它的候选跳过、顺位补下一名")
    parser.add_argument("--corr-window", type=int, default=252, help="相关性回看交易日数")
    parser.add_argument("--corr-conflict", choices=("skip", "swap_space", "swap_strength"),
                        default="skip",
                        help="OI-037：与在手持仓强相关时的处理——skip=跳过（生产口径）；"
                             "swap_space=候选 P/V 低出 swap-margin 即换出相关持仓一档；"
                             "swap_strength=近 N 日走势更强者留（N 由 --corr-strength-days 给）")
    parser.add_argument("--corr-strength-days", type=int, default=126,
                        help="swap_strength 的走势回看交易日数（63≈3个月/126≈6个月/252≈1年）")
    parser.add_argument("--scan-depth", type=int, default=40, help="相关性过滤时最多往下扫多少名")
    parser.add_argument("--tier-mode", choices=("none", "bonus", "quota"), default="none",
                        help="bonus=L1空间+20pp/L2+10pp 后再排序；quota=各档位分别排序并给买入额度")
    parser.add_argument("--min-upside", nargs=3, type=float, metavar=("L1", "L2", "L3"),
                        default=None, help="分档最低空间门槛，如 0.30 0.40 0.40")
    parser.add_argument("--position-cap", type=float, default=0.0,
                        help="单票买入上限占总资产比例，如 0.10；只挡加仓不强制减持")
    parser.add_argument("--only-tiers", default="", help="只买这些档位，逗号分隔，如 L1")
    parser.add_argument("--daily-states", type=Path, help="逐日估值状态文件，缺省 a_share_daily_states_adopted.csv（§6.7 第 3 步产物）")
    parser.add_argument("--universe-file", type=Path,
                        help="时点股票库（现行 panel_moat_bank_v6b.csv，由 build_moat_panel.py 装配）。"
                             "给了它就只在当期成员里选股，移出的持仓逐步清仓")
    parser.add_argument("--quota-file", type=Path,
                        help="配置通道的成员区间（与 --universe-file 同格式）。"
                             "配 --quota-pct 使用；OI-046 末段那条「不经由 P/V 排序的独立配置通道」")
    parser.add_argument("--quota-pct", type=float, default=0.0, metavar="P",
                        help="配置通道占净资产的比例，如 0.20。成员只要走势闸门开着就买、"
                             "不要求过买入线、不进主排序、不被换仓卖出。0=关闭（缺省）")
    parser.add_argument("--quota-swappable", action="store_true",
                        help="配置通道的持仓照常可被换仓卖出（只保留「买得进」不保留「留得住」），用于拆解两个机制各值多少")
    parser.add_argument("--rank-mode", choices=("pv", "quantile", "ratio"), default="pv",
                        help="pv=原始 P/V 升序；quantile=历史分位（已实测底部饱和）；ratio=当前 P/V÷历史中位（连续量，端点不饱和）")
    parser.add_argument("--quantile-window", type=int, default=0,
                        help="分位数回看交易日数，0=自上市以来全历史")
    parser.add_argument("--quantile-min-obs", type=int, default=250,
                        help="历史观测少于该数时退回原始 P/V 排序，不猜；"
                             "`--gate self-pct` 下含义更硬：不足即**不可买**，不回落")
    # ---- 自身分位闸门（用户 2026-08-15 的重构口径：每只股票只跟自己比）----
    parser.add_argument("--gate", choices=("pv", "self-pct", "self-pct-buy"), default="pv",
                        help="pv=买卖闸门用原始比值比线（现行）；"
                             "self-pct=买卖闸都用该股自身历史分位；"
                             "self-pct-buy=**只有买入闸**用分位，卖出/止损/换仓仍按原始比值")
    parser.add_argument("--buy-pct", type=float, default=0.05, metavar="Q",
                        help="self-pct 下的买入闸：分位 ≤ Q 才可买（窗口由 --quantile-window 定）")
    parser.add_argument("--sell-pct", type=float, default=0.60, metavar="Q",
                        help="self-pct 下的卖出闸：分位 ≥ Q 才允许减持/换出/止损")
    parser.add_argument("--pct-stop-when-rich", action="store_true",
                        help="止损只对分位 ≥ --sell-pct 的仓位生效，即「抄底之后不止损」")
    # ---- 用户 2026-08-15 第二批：加仓放宽、删估值减持、换仓加走势条件 ----
    parser.add_argument("--addon-trend", choices=("full", "ma-only"), default="full",
                        help="full=加仓与新建仓同条件（缺省）；"
                             "ma-only=**已有持仓**只要 MA20>MA60 就继续定投，不再要求 收盘>MA20")
    parser.add_argument("--no-value-sell", action="store_true",
                        help="删掉「`P/V` 过减持线就减一档」整条路径（§9.3.2 第 4 步第②条）。"
                             "此后卖出只剩：建仓日均线止损、出名单清仓、换仓")
    # 三个「反向开关」：BASE 串里已含 --no-value-sell / --swap-require-weak / --swap 这类
    # store_true，扫描器只能**追加**参数、无法删除，故各配一个同 dest 的反向旗（后出现者胜）。
    parser.add_argument("--value-sell", dest="no_value_sell", action="store_false",
                        help="反向开关：重新启用减持线（覆盖此前的 --no-value-sell）")
    parser.add_argument("--swap-require-weak", action="store_true",
                        help="换仓的卖出源须同时 `收盘 < MA{--swap-weak-ma}`，"
                             "即只换走势已走坏的持仓，涨势中的不因排名靠后被换掉")
    parser.add_argument("--no-swap-require-weak", dest="swap_require_weak", action="store_false",
                        help="反向开关：取消换仓的弱势要求（覆盖此前的 --swap-require-weak）")
    parser.add_argument("--swap-out-min-pv", type=float, default=0.0, metavar="X",
                        help="换仓的**绝对**门槛：只有自身 P/V ≥ X 的持仓才允许被换出"
                             "（「高估严重才换，排序变了不轻易换」）。缺省 0 = 关")
    parser.add_argument("--swap-weak-ma", type=int, default=20,
                        help="配 --swap-require-weak 用的均线周期，缺省 20")
    parser.add_argument("--hold-strong", choices=("off", "swap", "sell", "both"), default="off",
                        help="强势多头排列的持仓豁免：swap=不被换出／sell=不减持／both=两者")
    parser.add_argument("--hold-strong-ma", nargs="+", type=int, default=[20, 60, 120, 240],
                        help="多头排列所用均线，需严格递减，如 `20 60 120 240`")
    parser.add_argument("--entry-mode", choices=("trend", "deviation", "both"), default="trend",
                        help="trend=收盘>MA20>MA60；deviation=收盘≤中期均线×上限；both=两者同时")
    parser.add_argument("--dev-ma", type=int, default=60, help="偏离度所用的中期均线")
    parser.add_argument("--dev-buy-max", type=float, default=1.10,
                        help="买入上限：收盘 ≤ 中期均线 × 该倍数才买")
    parser.add_argument("--dev-sell-min", type=float, default=0.0,
                        help="卖出下限：收盘 ≥ 中期均线 × 该倍数即清仓（0=不启用）")
    parser.add_argument("--trend-exit-ma", type=int, default=0,
                        help="持仓收盘跌破该均线即清仓（0=不启用）；盯当日均线，非建仓日静态止损价")
    parser.add_argument("--no-rank", dest="rank_by_upside", action="store_false",
                        help="空间只作阈值不作排序：合格集内按代码中性排序，不优先买最便宜的")
    parser.add_argument("--liquidate-ma", type=int, default=0,
                        help="一键清仓的均线（0=不启用）：`P/V ≥ 减持线` 且连续 N 日跌破它即整仓卖出。"
                             "120=半年线、240=年线。与 --trend-exit-ma 的区别是它须同时满足 P/V 条件")
    parser.add_argument("--liquidate-days", type=int, default=3,
                        help="一键清仓要求的连续跌破天数")
    # 大盘围栏（用户 2026-08-20：「发现大盘下跌幅度过大或连续大跌，进行清仓保护，看能否切断回撤」）。
    # **纯研究开关，缺省全关、关时逐位不变**。两种触发（可同时开）、两种动作：
    #   速度围栏：指数 N 日跌幅 ≥ P → 进入围栏态；解除须「触发不再成立 且 指数收盘 > MA(R)」。
    #   趋势围栏：指数收盘 < 自身 MA(M) → 进入围栏态；收盘回到 MA(M) 之上即解除。
    #   block     = 围栏态内禁止一切买入（新建仓、加仓、换仓目标），持仓仍按原规则止损/减持；
    #   liquidate = 进入围栏态当日整仓清空（按成交日价），其后同 block。
    # 判据一律用**信号日**的指数收盘与均线（与个股闸门同源，T+1 成交），不看成交日。
    mk = parser.add_argument_group("大盘围栏（研究开关，缺省关闭）")
    mk.add_argument("--mkt-index", default="000300",
                    help="围栏所用指数代码，读 data/raw/ohlcv/INDEX_<代码>.csv（缺省沪深300）")
    mk.add_argument("--mkt-crash-days", type=int, default=0, metavar="N",
                    help="速度围栏：指数 N 个交易日跌幅 ≥ --mkt-crash-pct 即触发（0=关）")
    mk.add_argument("--mkt-crash-pct", type=float, default=0.10, metavar="P",
                    help="速度围栏的跌幅阈值（比例，0.10 即 10%%）")
    mk.add_argument("--mkt-trend-ma", type=int, default=0, metavar="M",
                    help="趋势围栏：指数收盘 < 自身 MA(M) 即触发（0=关）")
    mk.add_argument("--mkt-action", choices=("block", "liquidate"), default="block",
                    help="围栏态动作：block=只禁买；liquidate=进入围栏态当日整仓清空＋禁买")
    mk.add_argument("--mkt-release-ma", type=int, default=20, metavar="R",
                    help="速度围栏的解除条件之一：指数收盘 > MA(R)（趋势围栏按 MA(M) 自然解除）")
    mk.add_argument("--mkt-block-scope", choices=("all", "new"), default="all",
                    help="围栏态禁买范围：all=新建仓与加仓都禁；new=只禁新建仓，已持仓仍可按原规则加仓")
    parser.add_argument("--sell-trend-ma", nargs="*", type=int, default=[],
                        help="减持的前置走势闸门：给 `5 20` 表示还须 收盘<MA5<MA20 才按一档减。"
                             "空=原行为（纯估值触发）。只闸 P/V 减持，不闸出名单清仓与换仓")
    parser.add_argument("--exec-delay", type=int, choices=(0, 1), default=0,
                        help="0=T 日收盘算信号当日成交；1=T 日收盘算信号、T+1 日成交（现行）")
    parser.add_argument("--exec-price", choices=("close", "open"), default="close",
                        help="--exec-delay 1 时的成交价取 T+1 的开盘还是收盘")
    parser.add_argument("--trend-tol", type=float, nargs="+", default=[0.0],
                        help="走势条件容差 t：判据放宽为 收盘 > MA20×(1−t) 且 MA20 > MA60×(1−t)。"
                             "0.005 即 0.5%%。可给多个做敏感度")
    parser.add_argument("--trend-ma", nargs="+", type=int, default=[20, 60],
                        help="走势触发的均线，如 `20 60` 表示 收盘>MA20>MA60；`5 20` 表示 收盘>MA5>MA20；单个值表示只要求站上该均线")
    parser.add_argument("--buy-floor", type=float, default=0.0, metavar="X",
                        help="买入下限：`P/V < X` 的候选也不买，即买入区间变成 [X, 买入线]。"
                             "0=不设下限（原行为）。用于检验「过分便宜的是错杀还是市场看对了」")
    parser.add_argument("--sell-line", type=float, default=0.0,
                        help="减持线（P/V），缺省 1+w；设为 1.30 即涨到 30%% 溢价才减持")
    parser.add_argument("--trend-tranche", action="store_true",
                        help="走势组改为分批建仓：只要当日仍满足均线与估值条件就按 x%% 继续买入")
    parser.add_argument("--research-gate",
                        choices=("off", "rating", "nodown", "target", "eps", "both"),
                        default="off", help="研报预期方向门槛，见 ResearchGate 文档串")
    parser.add_argument("--research-window", type=int, default=180, help="研报回看天数（对比窗口同长）")
    parser.add_argument("--research-tol", type=float, default=0.0,
                        help="容忍的下滑幅度：rating 为评级均值降幅，eps 为预测降幅比例")
    parser.add_argument("--research-missing", choices=("pass", "block"), default="pass",
                        help="无研报覆盖时放行还是拦截。**block 会把它变成规模过滤器**")
    parser.add_argument("--lot-ratio-cooldown", action="store_true",
                        help="§9.3.3 比例冷却：一手价值是一档的 x 倍时，成交一手后跳过 round(x)−1 次合格机会（买卖共用）")
    parser.add_argument("--min-lot-cooldown", type=int, default=0, metavar="D",
                        help="高价股一档买不起一手时，改为每 D 个自然日买一手；0 表示跳过不买")
    parser.add_argument("--trade-log", type=Path, help="导出逐笔成交流水（人工核对用）")
    parser.add_argument("--candidate-log", type=Path,
                        help="研究开关：逐信号日记录合格集前十的排序（严格走势判据，与组合路径无关），供 rank 1 vs rank 2~5 前向收益事件研究；只在单跑分析时用")
    parser.add_argument("--no-artifacts", dest="artifacts", action="store_false",
                        help="不落 *_trades/_equity/_periods 三份逐条产物，只写 summary。"
                             "参数扫描一律加它——逐年收益与净值曲线只在单跑分析时才用得到")
    parser.add_argument("--rebuy", choices=("off", "lump", "gradual"), default="off",
                        help="割肉后的买回口径：lump=重新合格当日一次性买回相同股数；gradual=交回常规定投")
    parser.add_argument("--lot-size", type=int, default=0, metavar="N",
                        help="最小交易单位（A股填 100）。打开后买入按手向下取整、买不足一手则跳过")
    parser.add_argument("--stop-min-days", type=int, default=0, metavar="D",
                        help="建仓日均线止损的最短持有期：不足 D 个自然日不触发（0=原行为）")
    parser.add_argument("--stop-confirm-days", type=int, default=1, metavar="N",
                        help="固定止损价须连续 N 个有收盘价的交易日被跌破才触发；1=原行为")
    parser.add_argument("--stop-deep-pct", type=float, default=0.0, metavar="P",
                        help="深跌旁路：收盘低于止损价 P 比例时立即触发，不等确认日；0=关闭，3%%填0.03")
    parser.add_argument("--trail-ratio", type=float, default=0.0, metavar="K",
                        help="上移锚（用户 2026-08-20 实验）：锚_2 = K × 持有期峰价（只升不降，除权同步折算），"
                             "生效止损线 = max(锚_2, 现行止损线)。0=关（逐位不变）；例如 0.667")
    parser.add_argument("--profit-lock", default="", metavar="X:ETA[,X:ETA...]",
                        help="盈利锁定（用户 2026-08-24 实验）：信号日收盘 ≥ 持仓均价×(1+X) 后，止损线抬到 持仓均价×ETA（只升不降，"
                             "除权同步折算），生效止损线 = max(现行线, 锁定线)；阶梯用逗号分隔。空=关（逐位不变）。例 1.0:1.5")
    parser.add_argument("--addon-max-gain", type=float, default=0.0, metavar="G",
                        help="研究开关（用户 2026-08-22）：信号日收盘 ≥ 持仓均价×(1+G) 的持仓不再加仓；0=关。例 0.5")
    parser.add_argument("--gain-sell", type=float, default=0.0, metavar="G",
                        help="研究开关（用户 2026-08-22）：信号日收盘 ≥ 持仓均价×(1+G) 即触发减一档并可作换仓卖出源；0=关。例 1.0")
    parser.add_argument("--gain-sell-mode", choices=("gated", "ungated"), default="gated",
                        help="gated=涨幅减持／换仓同样过走势闸门（收<MA20 / 弱势）；ungated=不过闸门")
    parser.add_argument("--swap-trigger", choices=("cash", "power"), default="power",
                        help="换仓触发口径（OI-081）：power=现金＋剩余授信不足一档才换（§10.2 可用资金，缺省）；"
                             "cash=只看现金（v4.39 前旧口径，复现旧读数用）")
    parser.add_argument("--credit-over-limit", choices=("repay", "keep"), default="repay",
                        help="负债超过当日授信额度的处理（OI-081）：repay=卖出款先偿还超额、不可新增买入（§10.2，缺省）；"
                             "keep=额度取 max(已用负债, 额度)、不强制还款（v4.39 前旧口径，复现旧读数用）")
    parser.add_argument("--stop-line", choices=("entry", "min_entry_current"), default="entry",
                        help="止损线口径：entry=建仓日冻结线（旧）；min_entry_current=min(建仓日线, "
                             "当日同周期均线)——均线下移时止损跟随下移、上移不抬线（用户 2026-08-19 实验）")
    parser.add_argument("--entry-below-ma60", choices=("ma20_stop", "skip", "skip_fill"),
                        default="ma20_stop",
                        help="新建仓成交日收盘 < 当日 MA60（信号日过闸后跳空所致）的处理："
                             "ma20_stop=照买、锚退 MA20（旧行为）；skip=放弃该笔、资金顺位下一名"
                             "（用户 2026-08-20：此时几乎必然也低于 MA20，退档锚仍高于成本、买入即割）。"
                             "skip 判 T 日收盘对成交日 MA60（现行，§9.3.1 走势行）；"
                             "skip_fill 判成交日收盘对成交日 MA60（OI-092① 研究口径，§12.126 不采纳）")
    parser.add_argument("--stop-basis", choices=("exec", "signal"), default="exec",
                        help="止损判据时点（OI-092②）：exec=成交日收盘对成交日均线、同日判同日卖"
                             "（现行，§9.3.1 止损行）；signal=T 日收盘对 T 日均线判、T+1 按成交价卖"
                             "（研究口径，§12.126 不采纳）")
    parser.add_argument("--residual-clear", choices=("lot", "tranche"), default="lot",
                        help="减档后余仓清空阈值（OI-092③）：lot=不足一手才清（现行，§9.3.2 第 4 步）；"
                             "tranche=不足一档即清空（研究口径，§12.126 不采纳）")
    parser.add_argument("--ma-basis", choices=("adjusted", "raw"), default="adjusted",
                        help="均线与创新低判据的价格口径（OI-054）：adjusted=前复权、折回当日口径（缺省，与实盘"
                             "扫描器同基）；raw=不复权直接平均（v4.31 前旧口径，除权后 20/60 个交易日内均线错位）")
    parser.add_argument("--exright-stop", choices=("adjust", "frozen"), default="adjust",
                        help="除权日对建仓止损锚与持有期峰价的处理（OI-054）：adjust=按 §11.4 同式折算（缺省，"
                             "§9.3.5 实盘规则）；frozen=不动（v4.31 前旧口径，送转日会把整仓当跌破清空）")
    parser.add_argument("--sell-full", action="store_true",
                        help="P/V≥减持线（且过走势闸门）时整仓卖出，而非按一档减")
    parser.add_argument("--stop-partial", action="store_true",
                        help="建仓日均线止损改为「定投式减仓」：每日减一档而非整仓清空（用户 2026-08-14）")
    parser.add_argument("--stop-tranche", type=float, default=1.0, metavar="K",
                        help="--stop-partial 的减仓速度倍数：1=与定投同速，3=每日减三档；只在 --stop-partial 下生效")
    parser.add_argument("--swap-partial", action="store_true",
                        help="换仓由整仓卖出改为按定投同速减一档（仅在只差钱、槽位未满时）")
    parser.add_argument("--cluster-swap", action="store_true",
                        help="簇内升级模式：相关性用作「替换谁」的判据而非排除过滤器，持仓数不设上限")
    parser.add_argument("--cluster-delta", type=float, default=0.85,
                        help="判定「同簇」的相关性阈值；超过它才视为可互相替换")
    parser.add_argument("--cluster-min-upside", type=float, default=20.0, metavar="PCT",
                        help="备选的最低空间（百分数），空间=V/P−1")
    parser.add_argument("--swap-bypass-corr", action="store_true",
                        help="已为之腾过位的换仓目标豁免相关性检查——卖都卖了就该买到它")
    parser.add_argument("--research-permute", type=int, default=0, metavar="N",
                        help="安慰剂：研报序列按代码序错位 N 位，保留拦截强度、抹掉个股信息")
    parser.add_argument("--label-suffix", default="")
    fg = parser.add_argument_group("交易成本（缺省全零，与既往回测逐位可复现）")
    fg.add_argument("--fee-preset", choices=("none", "user"), default="none",
                    help="user＝用户券商口径：佣金万一、最低 5 元、印花税 0.05%% 单边卖出、过户费 0.001%% 双边")
    fg.add_argument("--commission", type=float, default=0.0, help="佣金费率，万一即 0.0001")
    fg.add_argument("--min-fee", type=float, default=0.0, help="单笔佣金最低额（元）")
    fg.add_argument("--stamp", type=float, default=0.0, help="印花税率（单边卖出），现行 0.0005")
    fg.add_argument("--transfer", type=float, default=0.0, help="过户费率（双边），现行 0.00001")
    fg.add_argument("--fee-stamp-mode", choices=("flat", "historical"), default="flat",
                    help="historical＝按成交日取历史印花税率（含早年双边征收），用于检验高换手配置在真实税率下是否还成立")
    args = parser.parse_args()

    if args.stop_confirm_days < 1:
        sys.exit("--stop-confirm-days 须为 ≥1 的交易日数")
    if not 0 <= args.stop_deep_pct < 1:
        sys.exit("--stop-deep-pct 是比例，须落在 [0,1)，例如 3% 填 0.03")
    profit_lock: tuple[tuple[float, float], ...] = ()
    if args.profit_lock:
        steps = []
        for item in args.profit_lock.split(","):
            try:
                x_s, eta_s = item.split(":")
                x, eta = float(x_s), float(eta_s)
            except ValueError:
                sys.exit(f"--profit-lock 格式须为 X:ETA[,X:ETA...]，收到 {args.profit_lock!r}")
            if x <= 0 or eta <= 0 or eta >= 1 + x:
                sys.exit(f"--profit-lock 每级须满足 X>0、0<ETA<1+X（否则设线当天即触发），收到 {item!r}")
            steps.append((x, eta))
        profit_lock = tuple(sorted(steps))

    if args.fee_preset == "user":       # 用户 2026-08-12 提供的券商口径
        args.commission = args.commission or 0.0001
        args.min_fee = args.min_fee or 5.0
        args.stamp = args.stamp or 0.0005
        args.transfer = args.transfer or 0.00001
    FEES.update(commission=args.commission, min_fee=args.min_fee, stamp=args.stamp,
                transfer=args.transfer, stamp_mode=args.fee_stamp_mode)

    print(f"载入…（逐日估值状态、行情、除权除息、均线）")
    universe = load_universe(args.universe_file) if args.universe_file else None
    quota = load_quota(args.quota_file) if args.quota_file else None
    if args.quota_pct > 0 and not quota:
        sys.exit("给了 --quota-pct 却没给 --quota-file：配置通道无成员，等于没开——拒绝静默跑空")
    if args.gate.startswith("self-pct"):
        if not 0 < args.buy_pct < 1 or not 0 < args.sell_pct <= 1:
            sys.exit("--buy-pct/--sell-pct 是分位，须落在 (0,1]；给成 1.00/2.50 那是比值口径的线")
        if args.buy_pct >= args.sell_pct:
            sys.exit(f"买入分位 {args.buy_pct} ≥ 卖出分位 {args.sell_pct}：买卖闸重叠，会当天买当天卖")
        # 这几个开关的判据全是**原始比值**（`1/(P/V)−1` 那套空间口径），在分位口径下含义不明。
        # 静默地按比值算会得到一份看不出错的污染读数，故直接拒绝组合。
        bad = [n for n, v in (("--buy-floor", args.buy_floor), ("--min-upside", args.min_upside),
                              ("--cluster-swap", args.cluster_swap), ("--use-mos", args.use_mos),
                              ("--tier-mode", args.tier_mode != "none")) if v]
        if bad:
            sys.exit(f"{'、'.join(bad)} 的判据是原始比值口径，与 --gate self-pct 不能同时用")
        # `--width`/`--sell-line` 在分位口径下**完全不参与判定**。BASE 里一定带着这两个开关，
        # 不喊一声的话很容易以为「买 1.00 减 2.50」还在生效——那正是 §12.1 记着的两次作废教训。
        if args.gate == "self-pct":
            print(f"⚠ --gate self-pct：买卖闸改用**自身分位** ≤{args.buy_pct:.0%} / ≥{args.sell_pct:.0%}"
                  f"（窗口 {args.quantile_window or '全历史'} 交易日、最少 {args.quantile_min_obs} 个观测）；"
                  f"\n  --width({args.width})/--sell-line({args.sell_line}) 本次**不参与任何判定**，"
                  f"--swap-margin({args.swap_margin}) 的单位变成分位点。", file=sys.stderr)
        else:
            print(f"⚠ --gate self-pct-buy：**只有买入闸**改用自身分位 ≤{args.buy_pct:.0%}"
                  f"（窗口 {args.quantile_window or '全历史'} 交易日）；卖出、止损、换仓仍按原始比值"
                  f"（减持线 {args.sell_line}、换仓改善 {args.swap_margin}）。"
                  f"\n  --sell-pct 本次**不生效**；--pct-stop-when-rich 仍生效但语义随之变成"
                  f"「只在 P/V ≥ {args.sell_line} 时才止损」。", file=sys.stderr)
    states = load_states(args.daily_states,
                         {c for _d, m in universe for c in m} if universe else None)
    prices = load_prices({r[0] for rows in states.values() for r in rows})
    opens = (load_opens({r[0] for rows in states.values() for r in rows})
             if args.exec_delay and args.exec_price == "open" else None)
    actions = load_actions()
    DELISTED_LAST.update(load_delisted())
    names, benchmark, risk_free = load_names(), load_benchmark(), load_risk_free()
    mkt_series = None
    if args.mkt_crash_days or args.mkt_trend_ma:
        mkt_series = load_index_series(args.mkt_index)
        if not mkt_series:
            sys.exit(f"--mkt-* 开关已开但找不到指数文件 INDEX_{args.mkt_index}.csv——拒绝静默跑成无围栏")
        print(f"  **大盘围栏**：指数 {args.mkt_index} {len(mkt_series):,} 日｜"
              + (f"速度 {args.mkt_crash_days} 日跌 ≥{args.mkt_crash_pct:.0%}（解除须站回 MA{args.mkt_release_ma}）" if args.mkt_crash_days else "")
              + ("＋" if args.mkt_crash_days and args.mkt_trend_ma else "")
              + (f"趋势 收盘<MA{args.mkt_trend_ma}" if args.mkt_trend_ma else "")
              + f"｜动作 {args.mkt_action}")
    # 均线窗口按**本次实际用到的**收集，缺哪条算哪条。此前固定 (5,10,20,60,120,240)，
    # 传入未预计算的窗口（如 `--trend-ma 10 30`）会使条件恒假、**一笔交易都不产生却不报错**
    # ——典型的静默失效（§13 第 3 条），2026-08-09 实测撞到后修正。
    windows = sorted({5, 10, 20, 60, 120, 240} | set(args.trend_ma) | set(args.hold_strong_ma)
                     | set(args.sell_trend_ma) | ({args.liquidate_ma} if args.liquidate_ma else set())
                     | {args.dev_ma, args.stop_ma} | ({args.trend_exit_ma} if args.trend_exit_ma else set()))
    ma_windows = tuple(w for w in windows if w > 0)
    if args.ma_basis == "adjusted":
        # OI-054：均线与创新低在**前复权口径**上算（折回当日口径），与实盘扫描器的前复权闸门同基；
        # 没有除权事件的股票与旧函数逐位相同。
        mas = {code: adjusted_moving_averages(series, actions.get(code, {}), ma_windows)
               for code, series in prices.items()}
        lows = {code: new_low_flags(adjusted_close_series(series, actions.get(code, {})))
                for code, series in prices.items()}
    else:
        print("⚠ --ma-basis raw：均线在不复权价上直接平均（v4.31 前旧口径，除权后均线错位），只用于复现旧读数",
              file=sys.stderr)
        mas = {code: moving_averages(series, ma_windows) for code, series in prices.items()}
        lows = {code: new_low_flags(series) for code, series in prices.items()}
    if args.exright_stop == "frozen":
        print("⚠ --exright-stop frozen：除权日不折算止损锚（v4.31 前旧口径，送转日会误触发整仓清空），只用于复现旧读数",
              file=sys.stderr)
    day_lists = {code: sorted(series) for code, series in prices.items()}
    day_pos = {code: {d: i for i, d in enumerate(ds)} for code, ds in day_lists.items()}
    corr = Correlations(daily_returns(prices, actions), args.corr_window) if args.max_corr else None
    research = None
    if args.research_gate != "off":
        ratings, downgrades, forecasts, targets = load_research(set(prices), actions=actions)
        research = ResearchGate(ratings, downgrades, forecasts, targets,
                                window=args.research_window, tol=args.research_tol,
                                missing=args.research_missing, permute=args.research_permute)
        spans = [d for series in ratings.values() for d, _ in series[:1]]
        print(f"  **研报门槛 {args.research_gate}**：有评级 {len(ratings):,} 只｜有下调记录 {len(downgrades):,} 只｜"
              f"有目标价 {len(targets):,} 只｜有预测 {len(forecasts):,} 只｜"
              f"最早评级 {min(spans) if spans else '缺'}｜"
              f"窗口 {args.research_window}d｜容忍 {args.research_tol:g}｜无覆盖={args.research_missing}")
    covered = sorted(states)
    print(f"  逐日状态 {sum(len(v) for v in states.values()):,} 行｜"
          f"{covered[0]} ~ {covered[-1]}｜行情 {len(prices)} 只｜"
          f"基准 {'沪深300 ' + str(len(benchmark)) + ' 日' if benchmark else '**缺**'}")
    if universe:
        sizes = [len(m) for _d, m in universe]
        print(f"  **时点股票库**：{len(universe)} 档｜{universe[0][0]} 起生效｜"
              f"每档 {min(sizes)}~{max(sizes)} 只｜并集 {len({c for _d, m in universe for c in m}):,} 只")
    if args.since < covered[0]:
        print(f"  ⚠ 请求起点 {args.since} 早于估值状态起点 **{covered[0]}**，"
              f"实际从后者起跑（历史带需先有逐季财务与五年年报 ROE，见工作流 §12.1）")

    tiers = load_tiers()
    strategies = ["valuation", "trend"] if args.strategy == "both" else [args.strategy]
    rows = []
    for strategy in strategies:
      for width in args.width:
        for x in args.x:
          for trend_tol in args.trend_tol:
            label = (f"{strategy}_x{x:g}_w{width:g}"
                     + (f"_tol{trend_tol:g}" if trend_tol else "")
                     + (f"_x{args.exec_delay}{args.exec_price[0]}" if args.exec_delay else "")
                     + (f"_sma{'-'.join(map(str, args.sell_trend_ma))}" if args.sell_trend_ma else "")
                     + (f"_liq{args.liquidate_ma}d{args.liquidate_days}" if args.liquidate_ma else "")
                     + ("_mos" if args.use_mos else "")
                     + (f"_tbs{args.tier_buy_scale.replace('=', '').replace(',', '_')}" if args.tier_buy_scale else "")
                     + (f"_tss{args.tier_sell_scale.replace('=', '').replace(',', '_')}" if args.tier_sell_scale else "")
                     + (f"_ma{args.stop_ma}" if args.price_stop else "")
                     + (f"_vstop{args.value_stop:g}" if args.value_stop else "")
                     + ("_stab" if args.entry_filter == "stabilized" else "")
                     + (f"_lump{args.lump_sum:g}" if args.lump_sum else "")
                     + ("_swap" if args.swap else "")
                     + ("" if args.trend_stop else "_nostop")
                     + (f"_corr{args.max_corr:g}" if args.max_corr else "")
                     + (f"_ccf-{args.corr_conflict}"
                        + (str(args.corr_strength_days) if args.corr_conflict == "swap_strength" else "")
                        if args.corr_conflict != "skip" else "")
                     + ("_tranche" if args.trend_tranche else "")
                     + ("_sf" if args.sell_full else "")
                     + (f"_stp{args.stop_tranche:g}" if args.stop_partial else "")  # `_sp` 已被 --swap-partial 占用
                     + (f"_smd{args.stop_min_days}" if args.stop_min_days else "")
                     + (f"_scd{args.stop_confirm_days}" if args.stop_confirm_days != 1 else "")
                     + (f"_sdp{args.stop_deep_pct * 100:g}" if args.stop_deep_pct else "")
                     + ("_slmin" if args.stop_line == "min_entry_current" else "")
                     + (f"_tr{args.trail_ratio:g}" if args.trail_ratio else "")
                     + (("_pl" + args.profit_lock.replace(":", "at").replace(",", "_")) if args.profit_lock else "")
                     + (f"_ag{args.addon_max_gain:g}" if args.addon_max_gain else "")
                     + (f"_gs{args.gain_sell:g}{'u' if args.gain_sell_mode == 'ungated' else ''}" if args.gain_sell else "")
                     + ("_swc" if args.swap_trigger == "cash" else "")
                     + ("_colk" if args.credit_over_limit == "keep" else "")
                     + ("_skipma60" if args.entry_below_ma60 == "skip" else "")
                     + ("_skipfill" if args.entry_below_ma60 == "skip_fill" else "")
                     + ("_stopsig" if args.stop_basis == "signal" else "")
                     + ("_rct" if args.residual_clear == "tranche" else "")
                     + ("_rawma" if args.ma_basis == "raw" else "")
                     + ("_frzstop" if args.exright_stop == "frozen" else "")
                     + (f"_ma{'-'.join(map(str,args.trend_ma))}" if args.trend_ma != [20, 60] else "")
                     + (f"_sl{args.sell_line:g}" if args.sell_line else "")
                     + (f"_bf{args.buy_floor:g}" if args.buy_floor else "")
                     + (f"_xma{args.trend_exit_ma}" if args.trend_exit_ma else "")
                     + ("_norank" if not args.rank_by_upside else "")
                     + (f"_{args.entry_mode}" if args.entry_mode != "trend" else "")
                     + (f"_dsell{args.dev_sell_min:g}" if args.dev_sell_min else "")
                     + (f"_hs{args.hold_strong}{len(args.hold_strong_ma)}" if args.hold_strong != "off" else "")
                     + (f"_{args.rank_mode[:1]}{args.quantile_window or 'all'}" if args.rank_mode != "pv" else "")
                     + ("_addma" if args.addon_trend == "ma-only" else "")
                     + ("_nvs" if args.no_value_sell else "")
                     + (f"_swk{args.swap_weak_ma}" if args.swap_require_weak else "")
                     + (f"_sop{args.swap_out_min_pv:g}" if args.swap_out_min_pv else "")
                     + (f"_q{args.quantile_window or 'all'}b{args.buy_pct:g}"
                        + (f"s{args.sell_pct:g}" if args.gate == "self-pct" else "A")
                        + ("nr" if args.pct_stop_when_rich else "")
                        if args.gate.startswith("self-pct") else "")
                     + (f"_{args.tier_mode}" if args.tier_mode != "none" else "")
                     + ("_minup" if args.min_upside else "")
                     + (f"_cap{args.position_cap:g}" if args.position_cap else "")
                     + (f"_only{args.only_tiers}" if args.only_tiers else "")
                     + ("_sp" if args.swap_partial else "")
                     + (f"_lot{args.lot_size}" if args.lot_size else "")
                     + (f"_ml{args.min_lot_cooldown}" if args.min_lot_cooldown else "")
                     + ("_lrc" if args.lot_ratio_cooldown else "")
                     + (f"_rb{args.rebuy}" if args.rebuy != "off" else "")
                     + (f"_cl{args.cluster_delta:g}u{args.cluster_min_upside:g}" if args.cluster_swap else "")
                     + (f"_rg{args.research_gate}{args.research_window}"
                        f"{'B' if args.research_missing == 'block' else ''}"
                        if args.research_gate != "off" else "")
                     + ((f"_mk{args.mkt_index}"
                         + (f"c{args.mkt_crash_days}p{args.mkt_crash_pct * 100:g}" if args.mkt_crash_days else "")
                         + (f"t{args.mkt_trend_ma}" if args.mkt_trend_ma else "")
                         + ("L" if args.mkt_action == "liquidate" else "B")
                         + ("n" if args.mkt_block_scope == "new" else "")
                         + (f"r{args.mkt_release_ma}" if args.mkt_crash_days else ""))
                        if (args.mkt_crash_days or args.mkt_trend_ma) else "")
                     + args.label_suffix)
            if research is not None:
                research.blocked.clear()
            run_stats = collections.Counter()
            ledger = [] if args.trade_log else None
            cand_handle = cand_writer = None
            if args.candidate_log:
                args.candidate_log.parent.mkdir(parents=True, exist_ok=True)
                cand_handle = args.candidate_log.open("w", newline="", encoding="utf-8")
                cand_writer = csv.writer(cand_handle)
                cand_writer.writerow(["signal_date", "exec_date", "rank", "security_code", "close",
                                      "intrinsic_value", "pv", "held", "eligible_n"])
            result = run(strategy, x / 100.0, states, prices, actions, mas,
                         args.since, args.until, args.capital, width=width, tiers=tiers,
                         credit_ratio=args.credit_ratio, credit_cap=args.credit_cap,
                         margin_rate=args.margin_rate,
                         maintenance=args.maintenance_ratio, recover_to=args.recover_ratio,
                         margin_ratchet=args.margin_ratchet,
                         use_mos=args.use_mos, price_stop=args.price_stop,
                         value_stop=args.value_stop, stop_ma=args.stop_ma,
                         trend_stop=args.trend_stop, entry_filter=args.entry_filter,
                         lump_sum=args.lump_sum / 100.0, swap=args.swap,
                         swap_margin=args.swap_margin, max_positions=args.max_positions,
                         lows=lows, day_index=(day_lists, day_pos),
                         max_corr=args.max_corr, corr=corr, corr_conflict=args.corr_conflict,
                         corr_strength_days=args.corr_strength_days, tier_mode=args.tier_mode,
                         scan_depth=args.scan_depth,
                         min_upside=(dict(zip(("L1", "L2", "L3"), args.min_upside))
                                     if args.min_upside else None),
                         position_cap=args.position_cap,
                         only_tiers={t.strip() for t in args.only_tiers.split(",") if t.strip()} or None,
                         universe=universe, trend_tranche=args.trend_tranche,
                         sell_full=args.sell_full, stop_min_days=args.stop_min_days,
                         stop_confirm_days=args.stop_confirm_days,
                         stop_deep_pct=args.stop_deep_pct, stop_line=args.stop_line,
                         entry_below_ma60=args.entry_below_ma60, exright_stop=args.exright_stop,
                         stop_basis=args.stop_basis, residual_clear=args.residual_clear,
                         stop_partial=args.stop_partial, stop_tranche=args.stop_tranche,
                         trend_ma=tuple(args.trend_ma), trend_tol=trend_tol,
                         exec_delay=args.exec_delay, exec_price=args.exec_price, opens=opens,
                         sell_trend_ma=tuple(args.sell_trend_ma),
                         liquidate_ma=args.liquidate_ma, liquidate_days=args.liquidate_days,
                         sell_line_override=args.sell_line or None,
                         trend_exit_ma=args.trend_exit_ma,
                         rank_by_upside=args.rank_by_upside, buy_floor=args.buy_floor,
                         entry_mode=args.entry_mode,
                         dev_ma=args.dev_ma, dev_buy_max=args.dev_buy_max,
                         dev_sell_min=args.dev_sell_min, hold_strong=args.hold_strong,
                         hold_strong_ma=tuple(args.hold_strong_ma), rank_mode=args.rank_mode,
                         quantile_window=args.quantile_window,
                         quantile_min_obs=args.quantile_min_obs,
                         research_gate=args.research_gate, research=research,
                         swap_bypass_corr=args.swap_bypass_corr, stats=run_stats,
                         cluster_swap=args.cluster_swap, cluster_delta=args.cluster_delta,
                         cluster_min_upside=args.cluster_min_upside / 100.0,
                         swap_partial=args.swap_partial, lot_size=args.lot_size, rebuy=args.rebuy,
                         ledger=ledger, min_lot_cooldown=args.min_lot_cooldown,
                         lot_ratio_cooldown=args.lot_ratio_cooldown,
                         quota_members=quota, quota_pct=args.quota_pct,
                         quota_swappable=args.quota_swappable,
                         gate=args.gate, buy_pct=args.buy_pct, sell_pct=args.sell_pct,
                         pct_stop_when_rich=args.pct_stop_when_rich,
                         addon_trend=args.addon_trend, no_value_sell=args.no_value_sell,
                         swap_require_weak=args.swap_require_weak,
                         swap_weak_ma=args.swap_weak_ma,
                         swap_out_min_pv=args.swap_out_min_pv,
                         mkt=mkt_series, mkt_crash_days=args.mkt_crash_days,
                         mkt_crash_pct=args.mkt_crash_pct, mkt_trend_ma=args.mkt_trend_ma,
                         mkt_action=args.mkt_action, mkt_release_ma=args.mkt_release_ma,
                         mkt_block_scope=args.mkt_block_scope, trail_ratio=args.trail_ratio,
                         profit_lock=profit_lock,
                         tier_buy_scale=parse_tier_scale(args.tier_buy_scale),
                         tier_sell_scale=parse_tier_scale(args.tier_sell_scale),
                         addon_max_gain=args.addon_max_gain, gain_sell=args.gain_sell,
                         gain_sell_mode=args.gain_sell_mode, swap_trigger=args.swap_trigger,
                         credit_over_limit=args.credit_over_limit,
                         candidate_log=cand_writer)
            if cand_handle is not None:
                cand_handle.close()
                print(f"    合格集排序记录 → {args.candidate_log}")
            if not result["equity"]:
                print(f"  {label}: 无交易日")
                continue
            # `--no-artifacts`：参数扫描只看 summary，逐笔/逐日/逐期三份写了就删。
            # 一轮 253 次运行会落 759 个文件、约 5 GB，且**目录一旦堆到几万个条目，
            # 后续每次运行的建档开销本身就会拖慢回测**（2026-08-14 实测：清空目录后同一份
            # 扫描由 ~75 分钟降到 6 分 24 秒，其中相当一部分正是目录规模造成的）。
            if args.artifacts:
                write_trades(args.out_dir / f"{label}_trades.csv", result["closed"], names)
                write_equity(args.out_dir / f"{label}_equity.csv", result["equity"])
                write_periods(args.out_dir / f"{label}_periods.csv", result["equity"])
            if ledger:
                with args.trade_log.open("w", newline="", encoding="utf-8") as handle:
                    w = csv.DictWriter(handle, fieldnames=list(ledger[0]) + ["security_name"])
                    w.writeheader()
                    for row in ledger:
                        w.writerow({**row, "security_name": names.get(row["security_code"], "")})
                print(f"    成交流水 {len(ledger):,} 笔 → {args.trade_log}")
            summary = summarize(label, result, args.capital, benchmark, risk_free)
            rows.append(summary)
            print(f"  {label}: 期末 {summary['期末资产']/1e4:,.1f} 万｜年化 {summary['年化']:.2%}"
                  f"｜最大回撤 {summary['最大回撤']:.1%}｜周期 {summary['周期数']}")
            if run_stats:
                print("    " + "｜".join(f"{k} {v:,}" for k, v in run_stats.most_common()))
            if research is not None and research.blocked:
                print("    研报门槛拦下（候选×日次）："
                      + "｜".join(f"{k} {v:,}" for k, v in research.blocked.most_common()))

    if rows:
        args.out_dir.mkdir(parents=True, exist_ok=True)   # --out-dir 指向不存在目录时此前直接崩溃
        with (args.out_dir / f"summary{args.label_suffix or ''}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        try:
            where = args.out_dir.relative_to(ROOT)
        except ValueError:
            where = args.out_dir
        print(f"\n落点 {where}/：" + ("逐周期 *_trades.csv、逐日 *_equity.csv、"
                                     "年月收益 *_periods.csv、汇总 summary.csv"
                                     if args.artifacts else
                                     "汇总 summary.csv（--no-artifacts，未落逐条产物）"))
    if not args.universe_file:
        print("\n⚠ **选样前视**：标的是今日核心池成员，池由 2026 年的分层选出。"
              "已实测其代价——2010-05~2026-08 同区间，改用逐年时点股票库后年化 "
              "**23.68% → 13.41%（−10.27pp）**（回测日志 §12.25.3）。"
              "本次未给 `--universe-file`，故本轮读数含该前视。")
    if DELISTED_LAST:
        print(f"退市处置：名册 {len(DELISTED_LAST):,} 只，过末个交易日的持仓按最后成交价整仓清出（协议 §8）；"
              "退市股三表缺失只能走权益口径、判定者后视不可消除——残余偏差见判定协议「退市股第二遍盲判」一节（OI-040 已归档）。")
    else:
        print("⚠ 退市名册缺失（data/raw/a_share_delisted_roster.csv）：退市持仓将冻结在最后成交价上，读数含幸存者偏差——见判定协议「退市股第二遍盲判」一节（OI-040 已归档）。")
    if FEES["commission"] or FEES["min_fee"] or FEES["stamp"] or FEES["stamp_mode"] == "historical":
        stamp = ("按成交日历史税率（含早年双边征收）" if FEES["stamp_mode"] == "historical"
                 else f"{FEES['stamp']*1e4:.1f}‱ 单边卖出")
        print(f"交易成本已计入：佣金 {FEES['commission']*1e4:.1f}‱（最低 {FEES['min_fee']:.0f} 元）、"
              f"过户费 {FEES['transfer']*1e4:.2f}‱ 双边、印花税 {stamp}")
    else:
        print("⚠ **不计交易成本**：对高换手（大 x）一侧更有利。加 --fee-preset user 可计入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

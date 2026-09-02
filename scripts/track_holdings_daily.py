#!/usr/bin/env python3
"""每日持仓跟踪（工作流 §11）。

取代 `scan_holdings_sell_signals.py`。该脚本自 v2.56 起只做三件事：

1. 读五列持仓清单（代码/名称/股数/成本价/**建仓日止损锚**）；
2. 取当日现价，对照核心估值合格池刷新空间；
3. 算出 `P/V`（现价 ÷ 生产带 V，`pv_ratio.trading_pv`；带缺失退回带中值），供 §9.3 的机械买卖判定消费；
4. 比对收盘价与**生效止损线 = min(锚, 当日MA60)**（§9.3.1 v4.25），命中即出
   §9.3.5 的整仓清空提示。

**v2.56 移除的是滚动均线割肉**（原持仓侧割肉条款，该编号已随 v4.07 精简退出正文；依据回测 log §12.9.38：破 MA60／破 MA120
三条口径五起点全负 −9.43 ~ −14.79pp）。随之移除的字段：`stop_loss_price`、
`stop_hit`、`day_low`、`割肉提醒`。

**v2.83 加回的 `entry_stop_price` 与它不是同一件事**（§9.3.5）：那条是**随均线
移动**的割肉线，这条是**建仓日定死、永不上移**的锚，回测里自始开启
（`trend_stop` 缺省 `True`），关掉它五起点全负、中位 −2.46pp。两者唯一的共同点
是都叫「止损」——**不得因为 v2.56 删过一个止损就把这个也删掉**。

**v4.25 的 min(锚, 当日MA60) 也不是 v2.56 那条滚动割肉的回归**：v2.56 的破线卖随均线
**双向**移动（均线上行时割肉线跟着抬高，正是全负的那只手）；v4.25 的生效线**永不高于锚**
——均线上移不抬线，只在均线跌破锚时向下豁免「大盘带着均线整体下移后冻结水位刻舟求剑」
的假跌破（依据 §12.88.2/§12.89：滚5 +0.59pp、16/23、逐年中性、回撤换手略降）。

**本脚本不产生任何买卖结论。** 卖出只有 §9.3.2 第四步四条（⓪跌破生效止损线
整仓、①较持仓均价涨幅 ≥110% 减一档（不看走势）、②出 §5 名单减一档、③换仓减一档），
由执行侧按本脚本输出的 `pv` 与 `stop_hit` 计算。

**刻意不做**的事（退役清单，现由工作流 §11.1 的边界承担）——盈亏、权重、仓位占比、单笔风险、
大趋势走坏判定、加仓资格、账户回撤与杠杆。若将来要加回来，
先改工作流 §11 再改这里（§13 第 1 条）。

`重大事项` 由大模型在逐票公告/新闻检索后判定，脚本不产出该取值。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a_share_quotes import fetch_spot_quotes
from a_share_signal_dates import evidence_iso_for_signal
from fetch_a_share_dividends import adjust_for_ex_dividend, fetch_ex_dividend_events
from screen_daily_volume_price_signals import (DEFAULT_HOLD_BANDS, DEFAULT_MODEL_BANDS, SEC93_GAIN_SELL,
                                               fetch_daily_rows, holding_trim_signal)
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log
from pv_ratio import load_model_bands, trading_pv  # noqa: E402  v4.62 OI-091

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_tracking.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"

# §9.3.1 的涨幅减持是 `较持仓均价涨幅 ≥ 110%`、不看走势；MA20 与 MA60 同经 `fetch_daily_rows` 取（前复权，§8.3），
# 命中判定用扫描器 `holding_trim_signal`（唯一实现）；执行清单由扫描器 `daily_sell_plan.csv` 给出。
# v4.62 OI-091：P/V 的净负债/企业价值来自生产带行。OI-095 起不在 import 时读带，
# 由 track() 按信号日自动推导的证据日载入；与扫描器使用同一时点。
# 测试可预置桩（非 None 即不再载入）。
MODEL_BANDS: dict[str, dict] | None = None      # 持仓侧带（v4.92 SPA：§9.3.1 换仓来源读它）
CAND_BANDS: dict[str, dict] | None = None       # 候选侧带（只用于并列显示两侧 P/V）
# §9.3.1 涨幅减持：收盘较持仓均价（`cost_basis`，按 §11.4 折算）涨幅 ≥ 110% → 减一档，不看走势；
# 资金不足时优先作换仓卖出源。
GAIN_SELL = SEC93_GAIN_SELL

FIELDNAMES = [
    "as_of",
    "security_code",
    "security_name",
    "current_shares",
    "cost_basis",
    # §9.3.5：建仓日定死的止损**锚**（成交日 MA60；v4.26 起成交日已破 MA60 的建仓直接跳过，
    # 不再产生 MA20 锚），与 `stop_hit` 一并输出；
    # v4.25 起判读用生效线 = min(锚, 当日MA60)，本列始终存锚（除权时按 §11.4 调锚）。留空 = 该票
    # 不受本条约束（存量持仓过渡口径）。**留空必须能与"跌破了"区分开**，故 `stop_hit`
    # 用三取值而不是布尔——布尔的 False 会把"没设"和"没跌破"混成同一个格子。
    "entry_stop_price",
    "stop_hit",
    "stop_line",       # 当日生效止损线 = min(锚, 当日 MA60)；锚未设或均线缺失时留空/退锚
    "close",
    "ma20",            # §8.3 前复权 MA20（展示项；涨幅减持不看走势）
    "ma60",            # §8.3 前复权 MA60：生效止损线的当日均线
    "quality_tier",
    # 参考分（工作流 §5.7）：只透传分层表经池 CSV 带过来的 quality_score，供报告显示同档内排序；
    # 不参与任何判定，也不在此重算。
    "quality_score",
    "fair_price_low",
    "fair_price_high",
    "upside",
    # §9.3 的唯一买卖判据：pv = 现价 ÷ 生产带 V（带缺失退回带中值）；两条线的取值只在 §9.3.1 定。
    # 与 upside 是同一个量的倒数关系（pv = 1/(1+upside)），但阈值定在 pv 上，故必须直接输出，
    # 不让读者每天心算倒数。
    "pv",
    "action",
    "note",
    "scanned_at_utc",
]


def to_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_pool(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["security_code"]: row for row in csv.DictReader(handle)}


def band_upside(close: float, low: float | None, high: float | None) -> str:
    """空间（区间中值/现价 − 1）。带缺失时返回空串。

    v2.11（用户指令）：第五列由「带位」改为「空间」。带位（带内X%／低于带底-X%／越带顶+X%）
    与空间是同一件事的两种写法，而空间与池阅读版同口径且可直接比较——池 MD 早在
    v1.10 就以同样理由删掉了带位列，持仓表此前一直没跟上。
    """
    if low is None or high is None or high <= 0 or close <= 0:
        return ""
    pct = round(((low + high) / 2 / close - 1) * 100)
    return "0%" if pct == 0 else f"{pct:+d}%"


def beijing_now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Shanghai"))


MA60_BASIS: dict[str, str] = {}     # 代码 → "qfq"（前复权，§8.3 口径）/ "raw"（前复权源不可用时的不复权兜底）


def fetch_raw_close(code: str, as_of: date, timeout: float) -> tuple[float | None, float | None, float | None]:
    """`as_of` 当日**不复权**收盘与当日 MA20／MA60，返回 `(收盘, MA20, MA60)`。

    取数走扫描器 `fetch_daily_rows` **同一实现**（OI-095：东财主源、腾讯备源、北交所自动改道腾讯，
    与 §9.3.1 入场闸门的 MA60 同源同基；两侧各自取数时两家前复权序列有差，同日入场闸门与
    止损生效线会不同基）。收盘：不复权序列 `as_of` 当根，当日无K线（未收盘/停牌/接口失败）为 None。
    MA60（§9.3.1 生效止损线要用的当日均线）：截至 `as_of` 的最近 60 根**前复权**收盘均值
    （§8.3 口径）——前复权序列锚在最新一根，末根即当日不复权收盘，故均值与当日价、与已按 §11.4
    折算过的锚同尺度。不足 60 根（新上市）为 None；前复权序列取不到时退回不复权均值并记
    `MA60_BASIS[code] = "raw"`（报告注明）。
    """
    as_of_text = as_of.isoformat()

    def series(fq: str) -> list[tuple[str, float]]:
        try:
            _, rows = fetch_daily_rows(code, "", as_of_text, timeout, fq=fq)
        except (OSError, ValueError, KeyError, IndexError):
            return []
        return [(str(r["date"]), float(r["close"])) for r in rows if str(r["date"]) <= as_of_text]

    def ma_of(closes: list[tuple[str, float]], window: int) -> float | None:
        return (sum(v for _d, v in closes[-window:]) / window) if len(closes) >= window else None

    raw_closes = series("")
    close = next((v for d, v in raw_closes if d == as_of_text), None)
    adj_closes = series("qfq")
    if adj_closes:
        ma20, ma60 = ma_of(adj_closes, 20), ma_of(adj_closes, 60)
        MA60_BASIS[code] = "qfq"
    elif raw_closes:
        ma20, ma60 = ma_of(raw_closes, 20), ma_of(raw_closes, 60)
        MA60_BASIS[code] = "raw"
    else:
        ma20 = ma60 = None
    return close, ma20, ma60


def resolve_prices(codes: list[str], as_of: date,
                   timeout: float) -> tuple[dict[str, float], dict[str, float], dict[str, float], str]:
    """OI-067（v4.20 修，用户裁定）：价格按 `--as-of` 取**当日不复权收盘**，不再取运行瞬间现价。

    三种情形：①盘后/补跑历史日期——日线有 `as_of` 那根K线，取真实收盘（补跑从此可信）；
    ②`as_of` 为当日且尚在盘中（北京 15:05 前）——日线未收，退实时现价并**显式标注「盘中价」**，
    用户盘后重跑同一日期即自动覆盖为收盘；③当日盘后日线仍缺（接口延迟/停牌）——现价兜底并标注。
    历史日期无K线一律「数据缺失」，**绝不拿今天的现价冒充历史收盘**（判例：2026-08-19 盘中
    补跑 08-18，汾酒显示 118.97 实为 08-19 盘中价，真实 08-18 收盘 120.52）。
    """
    bj = beijing_now()
    is_today = as_of == bj.date()
    intraday = is_today and (bj.hour, bj.minute) < (15, 5)
    out: dict[str, float] = {}
    ma20s: dict[str, float] = {}          # §9.3.1 涨幅减持的走势闸门均线
    ma60s: dict[str, float] = {}          # §9.3.1 v4.25 生效止损线的当日均线；取不到即缺席
    missing: list[str] = []
    for code in codes:
        close, ma20, ma60 = (None, None, None) if intraday else fetch_raw_close(code, as_of, timeout)
        if ma20 is not None:
            ma20s[code] = ma20
        if ma60 is not None:
            ma60s[code] = ma60
        if close is not None:
            out[code] = close
        else:
            missing.append(code)
    label = "收盘"
    if missing and is_today:
        spots = fetch_spot_quotes([(c, "") for c in missing], timeout=timeout)
        for c in missing:
            price = to_float((spots.get(c) or {}).get("price"))
            if price is not None:
                out[c] = price
        label = "盘中价（北京 15:05 前运行，盘后重跑即覆盖为收盘）" if intraday else "现价兜底（当日K线未入库）"
    elif missing:
        label = "收盘（历史日期，无K线的按数据缺失处理）"
    return out, ma20s, ma60s, label


def track(holdings_file: Path, pool_file: Path, as_of: date, symbols: str, timeout: float) -> list[dict[str, object]]:
    global MODEL_BANDS, CAND_BANDS
    if MODEL_BANDS is None:
        evidence = evidence_iso_for_signal(as_of)
        CAND_BANDS = load_model_bands(DEFAULT_MODEL_BANDS, as_of=evidence)
        if DEFAULT_HOLD_BANDS.exists():
            MODEL_BANDS = load_model_bands(DEFAULT_HOLD_BANDS, as_of=evidence)
        else:
            MODEL_BANDS = CAND_BANDS
            print(f"  ⚠ **持仓侧带文件不存在（{DEFAULT_HOLD_BANDS}）**：P/V 退回候选侧带；重建见 §6.7 第 4 步")
    with holdings_file.open(newline="", encoding="utf-8") as handle:
        holdings = list(csv.DictReader(handle))
    wanted = {s.strip().zfill(6) for s in symbols.split(",") if s.strip()}
    if wanted:
        holdings = [h for h in holdings if h["security_code"].zfill(6) in wanted]

    pool = load_pool(pool_file)
    prices, ma20s, ma60s, price_label = resolve_prices([h["security_code"].zfill(6) for h in holdings], as_of, timeout)
    if price_label != "收盘":
        print(f"  ⚠ 价格口径：{price_label}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: list[dict[str, object]] = []
    for h in holdings:
        code = h["security_code"].zfill(6)
        close = prices.get(code)
        pool_row = pool.get(code)
        low = to_float(pool_row.get("fair_price_low")) if pool_row else None
        high = to_float(pool_row.get("fair_price_high")) if pool_row else None

        upside = band_upside(close, low, high) if close is not None else ""

        # §9.3 唯一判据（v2.56）：V 取带中值；带缺失则 pv 留空，该票当日不进任何机械判定。
        # v4.62（OI-091）：有生产带行时按 `pv_ratio.trading_pv`（ROIC 路径为 (现价+净负债)÷EV），否则退回 现价÷中值。
        pv = None
        cand_pv = None
        if close is not None and low is not None and high is not None:
            mid = (low + high) / 2
            band_row = MODEL_BANDS.get(str(code).zfill(6)) if MODEL_BANDS else None
            if band_row is not None:
                pv = trading_pv(close, band_row)
            cand_row = CAND_BANDS.get(str(code).zfill(6)) if CAND_BANDS else None
            if cand_row is not None:
                cand_pv = trading_pv(close, cand_row)
            if pv is None and mid > 0:
                pv = close / mid

        notes: list[str] = []
        if pv is not None and cand_pv is not None and abs(pv - cand_pv) > 5e-5:
            notes.append(f"持仓侧 `P/V` {pv:.2f}（候选侧 {cand_pv:.2f}；换仓来源按持仓侧判）")
        if close is None:
            notes.append("**未取到当日行情**（停牌或接口失败）：`P/V` 未算出，该票当日不进 §9.3 判定")
        if pool_row is None:
            notes.append("不在核心估值合格池内，无带——按 §9.3.2 第四步逐日清仓")
        elif low is None or high is None:
            notes.append("池内无合理价区间（无法估值）：无 `P/V`，当日不进机械判定")
        # §9.3.1 涨幅减持行：唯一判定在扫描器 `holding_trim_signal`（只看涨幅，不看走势）。
        # 无带／无 P/V 的票照判（只要有收盘价与成本）。
        cost = to_float(h.get("cost_basis"))
        ma20 = ma20s.get(code)
        trim_rule, trim_why = holding_trim_signal(close, ma20, cost)
        gain = (close / cost - 1.0) if (close is not None and cost is not None and cost > 0) else None
        if trim_rule == "涨幅减持":
            notes.append(f"**涨幅减持一档**：较持仓均价 {cost:g} 涨幅 {gain:.0%} ≥ {GAIN_SELL:.0%}（不看走势）"
                         f"（§9.3.1 涨幅行）；资金不足时优先作换仓卖出源（涨幅最大者先）")
        elif trim_why:
            notes.append(trim_why)
        if close is not None and (cost is None or cost <= 0):
            # §13 第 3 条：判据缺失必须显式落字，不能静默等同「未触发」。
            notes.append("**持仓均价未填**（`cost_basis` 空）：§9.3.1 涨幅减持行无法判定，请按 §11.2 补填（买入加权、除权按 §11.4 折算）")

        # §9.3.5 建仓日止损。**先判无行情**：没有收盘价就既不能说跌破、也不能
        # 说没跌破，落 `无行情` 而不是默认放行——与 `action` 的 `数据缺失` 同一条理由。
        #
        # v4.25（§9.3.1）：`entry_stop_price` 是**锚**，生效止损线 = min(锚, 当日 MA60)
        # ——均线下移时生效线跟随下移、上移不抬。v4.26 起成交日已破 MA60 的建仓直接跳过、
        # 新锚恒为 MA60；仅 v4.26 前的存量持仓可能残留 MA20 锚（本工具按 MA60 取当日线，
        # 对其偏保守、提示可能偏早，如有按同周期人工复核）。当日均线不可得
        # （盘中价/新上市不足 60 根）时退回按锚判读并注明。
        entry_stop = to_float(h.get("entry_stop_price"))
        ma60 = ma60s.get(code)
        stop_line = None
        if entry_stop is None:
            stop_hit = "未设"
        elif close is None:
            stop_hit = "无行情"
        else:
            stop_line = min(entry_stop, ma60) if ma60 is not None else entry_stop
            if close < stop_line:
                stop_hit = "**已跌破**"
                ma_tag = "当日MA60" if MA60_BASIS.get(code) != "raw" else "当日MA60(不复权兜底，前复权源不可用)"
                detail = (f"= min(锚 {entry_stop:g}, {ma_tag} {ma60:g})" if ma60 is not None
                          else f"= 锚 {entry_stop:g}（当日均线不可得，按锚判读）")
                notes.append(
                    f"**收盘 {close:g} < 生效止损线 {stop_line:g}**（{detail}）："
                    f"按 §9.3.1 止损行次日尾盘以现价对当日生效线（min(锚, 当日MA60)）复核，"
                    f"仍跌破即**当日整仓清空**，先于涨幅减持与换仓执行"
                )
            else:
                stop_hit = "否"
                if ma60 is not None and close < entry_stop:
                    # 正是 v4.25 min 口径豁免的情形——旧冻结口径会在这里整仓清空，写明防误读
                    ma_tag = "当日MA60" if MA60_BASIS.get(code) != "raw" else "当日MA60(不复权兜底)"
                    notes.append(f"收盘 {close:g} 低于锚 {entry_stop:g} 但不低于{ma_tag} "
                                 f"{ma60:g}：按 §9.3.1 min 口径不触发止损")

        # §11.3 三取值（v2.56 删去 `割肉提醒`）。无行情时必须落 `数据缺失` 而非 `持有`：
        # `持有` 是唯一读起来像「已检查、没事」的取值，而没有现价恰恰意味着 `P/V` 没算过。
        # 一只涨幅已达标、本该减持的停牌股若显示为持有，就在卖出规则上
        # 制造了静默失效——这正是 §13 第 3 条要拦的形态。
        action = "数据缺失" if close is None else "持有"

        rows.append(
            {
                "as_of": as_of.isoformat(),
                "security_code": code,
                "security_name": h.get("security_name", ""),
                "current_shares": h.get("current_shares", ""),
                "cost_basis": h.get("cost_basis", ""),
                "entry_stop_price": "" if entry_stop is None else f"{entry_stop:g}",
                "stop_hit": stop_hit,
                "stop_line": "" if stop_line is None else f"{stop_line:.4g}",
                "close": "" if close is None else f"{close:g}",
                "ma20": "" if ma20 is None else f"{ma20:.4f}",
                "ma60": "" if ma60 is None else f"{ma60:.4f}",
                "quality_tier": (pool_row or {}).get("quality_tier", ""),
                "quality_score": (pool_row or {}).get("quality_score", ""),
                "fair_price_low": "" if low is None else f"{low:g}",
                "fair_price_high": "" if high is None else f"{high:g}",
                "upside": upside,
                "pv": "" if pv is None else f"{pv:.2f}",
                "action": action,
                "note": "；".join(notes),
                "scanned_at_utc": now,
            }
        )
    return rows


def log_decisions(
    log_file: Path,
    rows: list[dict[str, object]],
    as_of: date,
    holdings_file: Path,
    output_csv: Path,
    pool_file: Path = DEFAULT_VALUATION_POOL,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = [
        {
            "logged_at_utc": now,
            "workflow_stage": "holdings_tracking",
            "run_id": f"holdings_tracking_{as_of.isoformat()}",
            "as_of": as_of.isoformat(),
            "security_code": row["security_code"],
            "security_name": row["security_name"],
            "decision_type": "daily_holdings_tracking",
            "decision_result": row["action"],
            "summary_reason": (
                f"现价 {row['close'] or 'NA'}｜{row['quality_tier'] or 'NA'}"
                f"｜带 {row['fair_price_low'] or 'NA'}-{row['fair_price_high'] or 'NA'}｜空间 {row['upside'] or 'NA'}"
                f"｜P/V {row['pv'] or 'NA'}"
                + (f"｜{row['note']}" if row["note"] else "")
            ),
            # 溯源写实际用到的池文件；旧版硬写 DEFAULT_VALUATION_POOL，`--valuation-pool`
            # 指向别处时日志会记下一个本次没读过的路径。
            "input_files": f"{holdings_file}; {pool_file}",
            "source_urls": "",
            "output_file": str(output_csv),
            "operator_or_script": "track_holdings_daily.py",
            "workflow_version": WORKFLOW_VERSION,
            "decision_id": f"holdings_tracking:{as_of.isoformat()}:{row['security_code']}:01",
            "supersedes_decision_id": "",
        }
        for row in rows
    ]
    append_decision_log(log_file, records)


def report_ex_dividend(rows: list[dict[str, object]], as_of: date, timeout: float) -> None:
    """§11.4 除权除息检出（结 OI-030）：**每日固定输出一行**，无事也要说「无」。

    固定输出而非只在命中时打印，是本条的要点：不出声时，「今天查过了、没有」与「今天忘了查」
    在报告上长得一模一样——而 OI-030 登记的正是后者（规则预见了失效形态，却没有人负责触发它）。

    只提示、不写回：调整由 `apply_holdings_corporate_action.py` 执行并登记台账
    `holdings_corporate_actions_applied.csv`；本检出按台账区分「已处理／未处理」，并对近 30 日事件库有除权而无登记的
    持仓提示疑似漏调。**v2.56 后本检出的要害变了**——
    割肉价已退役，漏调影响的是 `P/V`（分子跳、分母不跳），会凭空造出一个买入信号；
    10 送 10 直接让 `P/V` 腰斩。危害由「多喊一次」升级为「多买一笔」。
    建议值一律标为**须人工核对**——差异化分派（判例即九号公司 2026-08-07）的价格口径与
    公告的每股派息不等，机械换算会算错。
    """
    codes = {str(row["security_code"]) for row in rows}
    from apply_holdings_corporate_action import DEFAULT_LEDGER, ledger_index, load_ledger
    applied = ledger_index(load_ledger(DEFAULT_LEDGER))
    try:
        events = fetch_ex_dividend_events(as_of.isoformat(), timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  **当日持仓除权除息：查询失败**（{type(exc).__name__}）——须人工核对，不得当作「无」")
        return

    hits = {code: event for code, event in events.items() if code in codes}
    # 配股（§11.4）：东财按日接口不含配股，读事件库（新浪配股表，`fetch_ohlcv_history.py --actions-only` 刷新）当日配股行
    actions_csv = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
    if actions_csv.exists():
        with actions_csv.open(newline="", encoding="utf-8-sig") as fh:
            for a in csv.DictReader(fh):
                code = str(a.get("security_code") or "").zfill(6)
                if code not in codes or (a.get("ex_dividend_date") or "")[:10] != as_of.isoformat():
                    continue
                rr, rp = to_float(a.get("rights_ratio")) or 0.0, to_float(a.get("rights_price")) or 0.0
                if rr <= 0:
                    continue
                ev = hits.setdefault(code, {"name": a.get("security_name", ""), "plan": "", "cash_per_share": 0.0,
                                            "share_ratio": 0.0, "progress": ""})
                ev["rights_ratio"], ev["rights_price"] = rr, rp
                ev["plan"] = (str(ev.get("plan") or "") + " " + str(a.get("plan") or "")).strip()
    # 疑似漏调：事件库里近 30 日有除权而台账无登记的持仓（事件库随 §6.7 第 1 步刷新，只覆盖库内代码）
    if actions_csv.exists():
        from datetime import timedelta
        lo = (as_of - timedelta(days=30)).isoformat()
        missed = []
        with actions_csv.open(newline="", encoding="utf-8-sig") as fh:
            for a in csv.DictReader(fh):
                code = str(a.get("security_code") or "").zfill(6)
                ex = (a.get("ex_dividend_date") or "")[:10]
                if code in codes and lo <= ex < as_of.isoformat() and (code, ex) not in applied:
                    missed.append(f"{a.get('security_name') or code}（{code}）{ex} {a.get('plan', '')}")
        if missed:
            print(f"  ⚠ **疑似漏调 {len(missed)} 项**（近 30 日事件库有除权、台账无登记）：{'；'.join(missed)}"
                  f"——若已手工调过，补跑 apply_holdings_corporate_action.py 登记（--dry-run 看数）；未调过则立即执行")
    if not hits:
        print(f"  当日持仓除权除息：无（全市场 {len(events)} 家除权，均不在持仓内；事件库当日无持仓配股）")
        return

    print(f"  **当日持仓除权除息 {len(hits)} 只**（§11.4：须在当日跟踪前调整**估值带**与 `cost_basis`）：")
    by_code = {str(row["security_code"]): row for row in rows}
    for code, event in hits.items():
        row = by_code[code]
        cash, ratio = float(event["cash_per_share"]), float(event["share_ratio"])  # type: ignore[arg-type]
        rr, rp = float(event.get("rights_ratio") or 0.0), float(event.get("rights_price") or 0.0)  # type: ignore[arg-type]
        done = (code, as_of.isoformat()) in applied
        print(f"    - {row['security_name']}（{code}）{event['plan']}"
              + ("｜**已处理**（台账已登记，持仓表为除权后口径，勿再调）" if done else "｜**未处理**"))
        if done:
            continue
        # `entry_stop_price` 与前三项一起调（§11.4）。**漏调它的后果比漏调带更立即**：
        # 送转后价格按因子下跳而止损价不动，次日必然「跌破」，直接触发一次错误的整仓清仓。
        for label, field in (("成本价", "cost_basis"), ("带下沿", "fair_price_low"),
                             ("带上沿", "fair_price_high"), ("**建仓日止损价**", "entry_stop_price")):
            value = to_float(row.get(field))
            if value is None:
                print(f"        {label}：未设定，无需调整")
                continue
            print(f"        {label} {value:g} → **建议 {adjust_for_ex_dividend(value, cash, ratio, rr, rp):.2f}**"
                  f"（(原价 − {cash:g}" + (f" + {rr:g}×{rp:g}" if rr else "") + f") ÷ (1 + {ratio + rr:g})）")
        if ratio:
            print(f"        送转比例 {ratio:g}/股：`current_shares` 同须按 §11.4 调整")
        if rr:
            print(f"        配股 {rr:g}/股 @ {rp:g}：认购后 `current_shares` × (1 + {rr:g})、认购款 = 股数 × {rr:g} × {rp:g}；"
                  f"不认购则股数不变、价格口径量仍按上式折算")
        print("        注：`entry_stop_price` 的调整**须持久化**——它是历史时点价格，"
              "没有任何重建会重新算它（带的除权归一化由建带链机械维护，见 §11.4）")
        print(f"        → 执行：python3 scripts/apply_holdings_corporate_action.py --as-of {as_of.isoformat()} --code {code}"
              "（写回持仓表并登记台账；同一事件二次执行会被拒绝）。差异化分派的价格口径与公告每股派息不等"
              "（判例：九号公司 2026-08-07 公告 10派12.3852，价格口径每份 1.22）时显式给 --cash/--ratio")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日持仓跟踪（工作流 §11）")
    parser.add_argument("--as-of", required=True, help="交易日 YYYY-MM-DD")
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    parser.add_argument("--valuation-pool", type=Path, default=DEFAULT_VALUATION_POOL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="可选：逗号分隔的代码过滤")
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    rows = track(args.holdings, args.valuation_pool, as_of, args.symbols, args.timeout)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    log_decisions(args.log_file, rows, as_of, args.holdings, args.output_csv, args.valuation_pool)

    gain_trim = []
    for r in rows:
        c, k = to_float(r.get("close")), to_float(r.get("cost_basis"))
        rule, _why = holding_trim_signal(c, to_float(r.get("ma20")), k)
        if rule == "涨幅减持":
            gain_trim.append((c / k - 1.0, r))
    gain_trim.sort(key=lambda t: -t[0])
    no_pv = [r for r in rows if not str(r["pv"]).strip()]
    no_band = [r for r in rows if not r["fair_price_low"]]
    print(f"tracked {len(rows)} holdings as of {as_of}")
    # §11.4 检出排在 P/V 结论之前打印：除权未调时，下面那行 P/V 就是错的（§9.1 第四步）。
    report_ex_dividend(rows, as_of, args.timeout)
    # §9.3.5 排在 P/V 之前：止损是第 ⓪ 条路径，命中即整仓，不再走涨幅减持与换仓。
    # **无事也打印**，且必须把「未设」单列——一行「跌破：无」在 25 只全部未设时是恒真的，
    # 与恒亮的告警同型（§13 第 3 条）。
    stopped = [r for r in rows if r["stop_hit"] == "**已跌破**"]
    unset = [r for r in rows if r["stop_hit"] == "未设"]
    blind = [r for r in rows if r["stop_hit"] == "无行情"]
    if stopped:
        names = "、".join(f"{r['security_name']}(收 {r['close']}，锚 {r['entry_stop_price']}，生效线见 note)"
                          for r in stopped)
        print(f"  **跌破生效止损线 {len(stopped)} 只**：{names}——按 §9.3.5 次日尾盘**整仓清空**，先于涨幅减持与换仓")
    else:
        print(f"  跌破生效止损线（min(锚, 当日MA60)，§9.3.1 v4.25）：无"
              f"（已设锚 {len(rows) - len(unset)}/{len(rows)} 只"
              + (f"，其中 {len(blind)} 只当日无行情无法比对" if blind else "") + "）")
    if unset:
        print(f"  未设止损锚 {len(unset)} 只：{'、'.join(str(r['security_name']) for r in unset)}"
              f"——§9.3.5 对其不生效，须待清空后重新建仓时按新规则设定")
    no_cost = [r for r in rows if not (to_float(r.get("cost_basis")) or 0) > 0]
    if no_cost:
        print(f"  **持仓均价未填 {len(no_cost)} 只**：{'、'.join(str(r['security_name']) for r in no_cost)}——§9.3.1 涨幅减持行对其无法判定，请补 `cost_basis`（§11.2）")
    if gain_trim:
        names = "、".join(f"{r['security_name']}(+{g:.0%}，收 {r['close']})" for g, r in gain_trim)
        print(f"  **涨幅减持一档（涨幅 ≥ {GAIN_SELL:.0%}，不看走势）共 {len(gain_trim)} 只**：{names}——"
              f"资金不足时按此顺序优先作换仓卖出源；股数见 `daily_sell_plan.csv`")
    else:
        print(f"  涨幅减持（涨幅 ≥ {GAIN_SELL:.0%}，不看走势）：无")
    if no_pv:
        print(f"  **P/V 未算出 {len(no_pv)} 只**：{'、'.join(str(r['security_name']) for r in no_pv)}（无行情或无带，当日不进 §9.3 判定）")
    if no_band:
        print(f"  无带（出池或无法估值）{len(no_band)} 只：{'、'.join(str(r['security_name']) for r in no_band)}")
    # 落地校验：新增列必须核对非空行数——「整列为空而无人察觉」是本仓库复发过四次的静默失效签名（§13 第 3 条）。
    scored = [r for r in rows if str(r["quality_score"]).strip()]
    print(f"  参考分（工作流 §5.7）非空 {len(scored)}/{len(rows)} 行")
    if rows and not scored:
        print("  **告警：quality_score 整列为空** —— 池 CSV 未透传参考分，报告不得手填，先修脚本/池物化")


if __name__ == "__main__":
    main()

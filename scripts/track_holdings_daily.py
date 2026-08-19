#!/usr/bin/env python3
"""每日持仓跟踪（工作流 §11）。

取代 `scan_holdings_sell_signals.py`。该脚本自 v2.56 起只做三件事：

1. 读五列持仓清单（代码/名称/股数/成本价/**建仓日止损锚**）；
2. 取当日现价，对照核心估值合格池刷新现档（§6.2）与空间；
3. 算出 `P/V`（现价 ÷ 合理价区间中值），供 §9.3 的机械买卖判定消费；
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
整仓、①`P/V` 越过 §9.3.1 减持线且破 MA20 减一档、②出 §5 名单减一档、③换仓减一档），
由执行侧按本脚本输出的 `pv` 与 `stop_hit` 计算。

**刻意不做**的事（退役清单，现由工作流 §11.1 的边界承担）——盈亏、权重、仓位占比、单笔风险、
大趋势走坏判定、估值卖出减仓梯、加仓资格、账户回撤与杠杆。若将来要加回来，
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
from fetch_a_share_dividends import adjust_for_ex_dividend, fetch_ex_dividend_events
from screen_daily_volume_price_signals import SEC93_SELL_LINE, get_json, infer_secid
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_tracking.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"

# **减持线的唯一落点在 §9.3.1**；此处直接引用扫描器常量、不再抄数——v2.98 抄下的 2.50 在
# v4.04 参数表改 2.5548 时没跟上（本文件漂移到 2026-08-19 才被发现，v4.20 修）。
# 注意：§9.3.1 的减持是 `P/V ≥ 线 **且收盘 < MA20**`，本脚本不算均线，只报前半个条件。
SELL_LINE = SEC93_SELL_LINE

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
    "close",
    "quality_tier",
    # 参考分（工作流 §5.7）：只透传分层表经池 CSV 带过来的 quality_score，供报告显示同档内排序；
    # 不参与任何判定，也不在此重算。
    "quality_score",
    "effective_valuation_tier",
    "fair_price_low",
    "fair_price_high",
    "upside",
    # §9.3 的唯一买卖判据（v2.56）：pv = 现价 ÷ 合理价区间中值；两条线的取值只在 §9.3.1 定。
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


def effective_tier(close: float, low: float | None, high: float | None) -> tuple[str, str]:
    """§6.2 价格自动定档 + 空间（区间中值/现价 − 1）。带缺失时返回空档与空空间。

    v2.11（用户指令）：第五列由「带位」改为「空间」。带位（带内X%／低于带底-X%／越带顶+X%）
    与空间是同一件事的两种写法，而空间与池阅读版、§9.6 名单同口径且可直接比较——池 MD 早在
    v1.10 就以同样理由删掉了带位列，持仓表此前一直没跟上。
    """
    if low is None or high is None or high <= 0 or close <= 0:
        return "", ""
    pct = round(((low + high) / 2 / close - 1) * 100)
    upside = "0%" if pct == 0 else f"{pct:+d}%"
    if close > 1.2 * high:
        return "高估", upside
    if close > high:
        return "较高估", upside
    if close >= low:
        return "中性", upside
    return ("低估" if (low + high) / 2 / close - 1 >= 0.40 else "较低估"), upside


def beijing_now() -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def fetch_raw_close(code: str, as_of: date, timeout: float) -> tuple[float | None, float | None]:
    """`as_of` 当日**不复权**收盘与当日 MA60，返回 `(收盘, MA60)`。

    收盘：当日无K线（未收盘/停牌/接口失败）为 None。MA60（§9.3.1 v4.25 生效止损线
    要用的当日均线）：截至 `as_of` 的最近 60 根不复权收盘均值，不足 60 根（新上市）为 None
    ——与锚同为不复权口径，除权日的跳变两侧同源。
    主源腾讯 newfqkline 的 `day`（不复权）数组——东财 kline 端点对本机批量访问会整段断连
    （2026-08-19 实测连扫描器同参查询也 RemoteDisconnected），故顺序与扫描器相反：腾讯为主。
    """
    import urllib.parse
    from datetime import timedelta
    from a_share_quotes import quote_symbol
    symbol = quote_symbol(code, "")
    # 60 个交易日 ≈ 90 个自然日，节假日富余取 130 天窗口
    start = (as_of - timedelta(days=130)).isoformat()

    def digest(rows: list[list[str]]) -> tuple[float | None, float | None]:
        closes = [(str(p[0]), float(p[2])) for p in rows if str(p[0]) <= as_of.isoformat()]
        close = next((v for d, v in closes if d == as_of.isoformat()), None)
        ma60 = (sum(v for _d, v in closes[-60:]) / 60) if len(closes) >= 60 else None
        return close, ma60

    url = (f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
           f"?param={symbol},day,{start},{as_of.isoformat()},90,")
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": "https://gu.qq.com/"})
        import json as _json
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = _json.loads(resp.read().decode("utf-8", "ignore"))
        day_rows = ((payload.get("data") or {}).get(symbol) or {}).get("day") or []
        if day_rows:
            close, ma60 = digest(day_rows)
            if close is not None:
                return close, ma60
    except OSError:
        pass
    # 备源：东财不复权日线
    query = urllib.parse.urlencode({
        "secid": infer_secid(code, ""),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "0",
        "beg": start.replace("-", ""),
        "end": as_of.isoformat().replace("-", ""), "lmt": "90",
    })
    try:
        payload = get_json(f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{query}", timeout)
    except OSError:
        return None, None
    rows = [line.split(",") for line in (payload.get("data") or {}).get("klines") or []]
    return digest(rows) if rows else (None, None)


def resolve_prices(codes: list[str], as_of: date,
                   timeout: float) -> tuple[dict[str, float], dict[str, float], str]:
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
    ma60s: dict[str, float] = {}          # §9.3.1 v4.25 生效止损线的当日均线；取不到即缺席
    missing: list[str] = []
    for code in codes:
        close, ma60 = (None, None) if intraday else fetch_raw_close(code, as_of, timeout)
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
    return out, ma60s, label


def track(holdings_file: Path, pool_file: Path, as_of: date, symbols: str, timeout: float) -> list[dict[str, object]]:
    with holdings_file.open(newline="", encoding="utf-8") as handle:
        holdings = list(csv.DictReader(handle))
    wanted = {s.strip().zfill(6) for s in symbols.split(",") if s.strip()}
    if wanted:
        holdings = [h for h in holdings if h["security_code"].zfill(6) in wanted]

    pool = load_pool(pool_file)
    prices, ma60s, price_label = resolve_prices([h["security_code"].zfill(6) for h in holdings], as_of, timeout)
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

        tier, upside = ("", "")
        if close is not None:
            tier, upside = effective_tier(close, low, high)

        # §9.3 唯一判据（v2.56）：V 取带中值；带缺失则 pv 留空，该票当日不进任何机械判定。
        pv = None
        if close is not None and low is not None and high is not None:
            mid = (low + high) / 2
            if mid > 0:
                pv = close / mid

        notes: list[str] = []
        if close is None:
            notes.append("**未取到当日行情**（停牌或接口失败）：`P/V` 未算出，该票当日不进 §9.3 判定")
        if pool_row is None:
            notes.append("不在核心估值合格池内，无带——按 §9.3.2 第四步逐日清仓")
        elif low is None or high is None:
            notes.append("池内无合理价区间（无法估值）：无 `P/V`，当日不进机械判定")
        elif pv is not None and pv >= SELL_LINE:
            notes.append(f"**`P/V` {pv:.2f} ≥ {SELL_LINE:.4f}**：减持另须 `收盘 < MA20`"
                         f"（§9.3.1 完整条件，均线见扫描器输出），两者同时成立才减一档")

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
        if entry_stop is None:
            stop_hit = "未设"
        elif close is None:
            stop_hit = "无行情"
        else:
            stop_line = min(entry_stop, ma60) if ma60 is not None else entry_stop
            if close < stop_line:
                stop_hit = "**已跌破**"
                detail = (f"= min(锚 {entry_stop:g}, 当日MA60 {ma60:g})" if ma60 is not None
                          else f"= 锚 {entry_stop:g}（当日均线不可得，按锚判读）")
                notes.append(
                    f"**收盘 {close:g} < 生效止损线 {stop_line:g}**（{detail}）："
                    f"按 §9.3.5 次日尾盘**整仓清空**，先于 `P/V` 减持与换仓执行"
                )
            else:
                stop_hit = "否"
                if ma60 is not None and close < entry_stop:
                    # 正是 v4.25 min 口径豁免的情形——旧冻结口径会在这里整仓清空，写明防误读
                    notes.append(f"收盘 {close:g} 低于锚 {entry_stop:g} 但不低于当日MA60 "
                                 f"{ma60:g}：按 §9.3.1 min 口径不触发止损")

        # §11.3 三取值（v2.56 删去 `割肉提醒`）。无行情时必须落 `数据缺失` 而非 `持有`：
        # `持有` 是唯一读起来像「已检查、没事」的取值，而没有现价恰恰意味着 `P/V` 没算过。
        # 一只 P/V 已越过减持线、本该减持的停牌股若显示为持有，就在唯一的卖出规则上
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
                "close": "" if close is None else f"{close:g}",
                "quality_tier": (pool_row or {}).get("quality_tier", ""),
                "quality_score": (pool_row or {}).get("quality_score", ""),
                "effective_valuation_tier": tier,
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
                f"现价 {row['close'] or 'NA'}｜{row['quality_tier'] or 'NA'}×{row['effective_valuation_tier'] or 'NA'}"
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

    只提示、不写回：§11.4 明文「调整由维护者完成」。**v2.56 后本检出的要害变了**——
    割肉价已退役，漏调影响的是 `P/V`（分子跳、分母不跳），会凭空造出一个买入信号；
    10 送 10 直接让 `P/V` 腰斩。危害由「多喊一次」升级为「多买一笔」。
    建议值一律标为**须人工核对**——差异化分派（判例即九号公司 2026-08-07）的价格口径与
    公告的每股派息不等，机械换算会算错。
    """
    codes = {str(row["security_code"]) for row in rows}
    try:
        events = fetch_ex_dividend_events(as_of.isoformat(), timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  **当日持仓除权除息：查询失败**（{type(exc).__name__}）——须人工核对，不得当作「无」")
        return

    hits = {code: event for code, event in events.items() if code in codes}
    if not hits:
        print(f"  当日持仓除权除息：无（全市场 {len(events)} 家除权，均不在持仓内）")
        return

    print(f"  **当日持仓除权除息 {len(hits)} 只**（§11.4：须在当日跟踪前调整**估值带**与 `cost_basis`）：")
    by_code = {str(row["security_code"]): row for row in rows}
    for code, event in hits.items():
        row = by_code[code]
        cash, ratio = float(event["cash_per_share"]), float(event["share_ratio"])  # type: ignore[arg-type]
        print(f"    - {row['security_name']}（{code}）{event['plan']}")
        # `entry_stop_price` 与前三项一起调（§11.3）。**漏调它的后果比漏调带更立即**：
        # 送转后价格按因子下跳而止损价不动，次日必然「跌破」，直接触发一次错误的整仓清仓。
        for label, field in (("成本价", "cost_basis"), ("带下沿", "fair_price_low"),
                             ("带上沿", "fair_price_high"), ("**建仓日止损价**", "entry_stop_price")):
            value = to_float(row.get(field))
            if value is None:
                print(f"        {label}：未设定，无需调整")
                continue
            print(f"        {label} {value:g} → **建议 {adjust_for_ex_dividend(value, cash, ratio):.2f}**"
                  f"（(原价 − {cash:g}) ÷ (1 + {ratio:g})）")
        if ratio:
            print(f"        送转比例 {ratio:g}/股：`current_shares` 同须按 §11.4 调整")
        print("        注：`entry_stop_price` 的调整**须持久化**——它是历史时点价格，"
              "没有任何重建会重新算它（带的 `−D` 则到下次基本面重建即抹掉，见 §11.3）")
        print("        ⚠ 建议值须人工核对后写回，两条都要核："
              "①**本检出不知道你调过没有**——清单里没有记录调整状态的字段，若本日已按 §11.4 调过，"
              "忽略本行，再调一次就是重复除权；"
              "②差异化分派的价格口径与公告每股派息不等（判例：九号公司 2026-08-07 公告 10派12.3852，"
              "价格口径每份 1.22）")


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

    trim = [r for r in rows if r["pv"] and float(r["pv"]) >= SELL_LINE]
    no_pv = [r for r in rows if not str(r["pv"]).strip()]
    no_band = [r for r in rows if not r["fair_price_low"]]
    print(f"tracked {len(rows)} holdings as of {as_of}")
    # §11.4 检出排在 P/V 结论之前打印：除权未调时，下面那行 P/V 就是错的（§9.1 第四步）。
    report_ex_dividend(rows, as_of, args.timeout)
    # §9.3.5 排在 P/V 之前：止损是第 ⓪ 条路径，命中即整仓，不再走减持与换仓。
    # **无事也打印**，且必须把「未设」单列——一行「跌破：无」在 25 只全部未设时是恒真的，
    # 与恒亮的告警同型（§13 第 3 条）。
    stopped = [r for r in rows if r["stop_hit"] == "**已跌破**"]
    unset = [r for r in rows if r["stop_hit"] == "未设"]
    blind = [r for r in rows if r["stop_hit"] == "无行情"]
    if stopped:
        names = "、".join(f"{r['security_name']}(收 {r['close']}，锚 {r['entry_stop_price']}，生效线见 note)"
                          for r in stopped)
        print(f"  **跌破生效止损线 {len(stopped)} 只**：{names}——按 §9.3.5 次日尾盘**整仓清空**，先于减持与换仓")
    else:
        print(f"  跌破生效止损线（min(锚, 当日MA60)，§9.3.1 v4.25）：无"
              f"（已设锚 {len(rows) - len(unset)}/{len(rows)} 只"
              + (f"，其中 {len(blind)} 只当日无行情无法比对" if blind else "") + "）")
    if unset:
        print(f"  未设止损锚 {len(unset)} 只：{'、'.join(str(r['security_name']) for r in unset)}"
              f"——§9.3.5 对其不生效，须待清空后重新建仓时按新规则设定")
    if trim:
        names = "、".join(f"{r['security_name']}({r['pv']})" for r in trim)
        print(f"  **P/V ≥ {SELL_LINE:.4f} 共 {len(trim)} 只**：{names}——另须 `收盘 < MA20`（§9.3.1）才减一档")
    else:
        print(f"  P/V ≥ {SELL_LINE:.4f}：无")
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

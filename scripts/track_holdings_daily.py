#!/usr/bin/env python3
"""每日持仓跟踪（工作流 §11）。

取代 `scan_holdings_sell_signals.py`。该脚本自 v2.56 起只做三件事：

1. 读五列持仓清单（代码/名称/股数/成本价/**建仓日止损价**）；
2. 取当日现价，对照核心估值合格池刷新现档（§6.2）与空间；
3. 算出 `P/V`（现价 ÷ 合理价区间中值），供 §9.3 的机械买卖判定消费；
4. 比对收盘价与 `entry_stop_price`，命中即出 §9.3.5 的整仓清空提示。

**v2.56 移除的是滚动均线割肉**（原持仓侧割肉条款，该编号已随 v4.07 精简退出正文；依据回测 log §12.9.38：破 MA60／破 MA120
三条口径五起点全负 −9.43 ~ −14.79pp）。随之移除的字段：`stop_loss_price`、
`stop_hit`、`day_low`、`割肉提醒`。

**v2.83 加回的 `entry_stop_price` 与它不是同一件事**（§9.3.5）：那条是**随均线
移动**的割肉线，这条是**建仓日定死、永不上移**的固定价，回测里自始开启
（`trend_stop` 缺省 `True`），关掉它五起点全负、中位 −2.46pp。两者唯一的共同点
是都叫「止损」——**不得因为 v2.56 删过一个止损就把这个也删掉**。

**本脚本不产生任何买卖结论。** 卖出只有 §9.3.2 第四步四条（⓪跌破建仓日止损
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
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_tracking.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"

# **减持线的唯一落点在 §9.3.1，这里只放一份副本**（v2.98 由 1.10 改为 2.50，用户 2026-08-14 指令）。
# 此前本文件把 1.10 硬编码在五处，v2.89 改参数表时一处都没跟上——正是 v2.97 清掉的那类
# 「同一个量抄在多处后各自漂移」。改这里之前先改 §9.3.1。
SELL_LINE = 2.50

FIELDNAMES = [
    "as_of",
    "security_code",
    "security_name",
    "current_shares",
    "cost_basis",
    # §9.3.5（v2.83）：建仓日 MA20 定死的止损价，与 `stop_hit` 一并输出。留空 = 该票
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


def track(holdings_file: Path, pool_file: Path, as_of: date, symbols: str, timeout: float) -> list[dict[str, object]]:
    with holdings_file.open(newline="", encoding="utf-8") as handle:
        holdings = list(csv.DictReader(handle))
    wanted = {s.strip().zfill(6) for s in symbols.split(",") if s.strip()}
    if wanted:
        holdings = [h for h in holdings if h["security_code"].zfill(6) in wanted]

    pool = load_pool(pool_file)
    quotes = fetch_spot_quotes([(h["security_code"], "") for h in holdings], timeout=timeout)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows: list[dict[str, object]] = []
    for h in holdings:
        code = h["security_code"].zfill(6)
        quote = quotes.get(code) or {}
        close = to_float(quote.get("price"))
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
            notes.append(f"**`P/V` {pv:.2f} ≥ {SELL_LINE:.2f}**：按 §9.3.2 第四步每日减持一档")

        # §9.3.5 建仓日止损（v2.83）。**先判无行情**：没有收盘价就既不能说跌破、也不能
        # 说没跌破，落 `无行情` 而不是默认放行——与 `action` 的 `数据缺失` 同一条理由。
        entry_stop = to_float(h.get("entry_stop_price"))
        if entry_stop is None:
            stop_hit = "未设"
        elif close is None:
            stop_hit = "无行情"
        elif close < entry_stop:
            stop_hit = "**已跌破**"
            notes.append(
                f"**收盘 {close:g} < 建仓日止损价 {entry_stop:g}**："
                f"按 §9.3.5 次日尾盘**整仓清空**，先于 `P/V` 减持与换仓执行"
            )
        else:
            stop_hit = "否"

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
        names = "、".join(f"{r['security_name']}(收 {r['close']} < 止损 {r['entry_stop_price']})" for r in stopped)
        print(f"  **跌破建仓日止损 {len(stopped)} 只**：{names}——按 §9.3.5 次日尾盘**整仓清空**，先于减持与换仓")
    else:
        print(f"  跌破建仓日止损：无（已设止损价 {len(rows) - len(unset)}/{len(rows)} 只"
              + (f"，其中 {len(blind)} 只当日无行情无法比对" if blind else "") + "）")
    if unset:
        print(f"  未设建仓日止损 {len(unset)} 只：{'、'.join(str(r['security_name']) for r in unset)}"
              f"——§9.3.5 对其不生效，须待清空后重新建仓时按新规则设定")
    if trim:
        names = "、".join(f"{r['security_name']}({r['pv']})" for r in trim)
        print(f"  **P/V ≥ {SELL_LINE:.2f} 共 {len(trim)} 只**：{names}——按 §9.3.2 第四步每日减持一档")
    else:
        print(f"  P/V ≥ {SELL_LINE:.2f}：无")
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

#!/usr/bin/env python3
"""Batch spot quotes for non-A-share lines (HK / US / KR) from Tencent (qt.gtimg.cn).

Serves the 海外关注清单 appendix of the pool MD (§6.8). Same provider as
`a_share_quotes.py` on purpose — one quote source, one failure mode — but the
payload layout differs per market, so the field indices live here.

Symbol form: ``hk00700`` / ``usAAPL`` / ``kr005930``. US tickers must carry no
exchange suffix (``usAAPL.OQ`` returns ``pv_none_match``).

Field indices, validated 2026-07-29 against 00700/09618/03690/06862 (HK),
AAPL/NVDA/MU (US) and 005930/000660 (KR):

| 市场 | 现价 | 行情时间 | PE-TTM | PB | 总市值(亿) | 币种 |
| HK   | 3    | 30       | 39     | 58 | 45         | 75   |
| US   | 3    | 30       | 39     | —  | 45         | 35   |
| KR   | 3    | 30       | —      | —  | 45         | —    |

US payloads carry no PB (index 43 is 振幅, not 市净率) and KR payloads carry
neither PE nor PB; callers fall back to the review-time values stored in the
valuation table (same degradation rule as a suspended A-share line).
"""

from __future__ import annotations

import urllib.request

TENCENT_QUOTE = "https://qt.gtimg.cn/q="
CHUNK_SIZE = 40
CURRENCY_BY_MARKET = {"HK": "HKD", "US": "USD", "KR": "KRW"}
# 每市场：(PE-TTM 下标, PB 下标, 币种下标)；None = 该市场不提供，调用方沿用估值时点值。
FIELD_LAYOUT = {
    "HK": (39, 58, 75),
    "US": (39, None, 35),
    "KR": (None, None, None),
}


def quote_symbol(market: str, code: str) -> str:
    market = (market or "").upper()
    if market == "HK":
        return "hk" + str(code).zfill(5)
    if market == "US":
        return "us" + str(code).upper()
    if market == "KR":
        return "kr" + str(code).zfill(6)
    raise ValueError(f"unsupported overseas market: {market}")


def _to_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _market_of(symbol: str) -> str:
    for prefix, market in (("hk", "HK"), ("us", "US"), ("kr", "KR")):
        if symbol.startswith(prefix):
            return market
    return ""


def fetch_overseas_quotes(
    items: list[tuple[str, str]], timeout: float = 8.0
) -> dict[str, dict[str, float | str | None]]:
    """items: (market, code) 列表 → {"HK:00700": {price, quote_time, pe_ttm, pb, market_cap_yi, currency}}。

    请求失败的分片和停牌/无报价(价格为0)的标的不出现在结果里；调用方按“缺失即沿用旧值”降级。
    """
    pairs: list[tuple[str, str]] = []
    for market, code in items:
        market = (market or "").upper()
        if market in CURRENCY_BY_MARKET:
            pairs.append((market, str(code)))
    quotes: dict[str, dict[str, float | str | None]] = {}
    for start in range(0, len(pairs), CHUNK_SIZE):
        chunk = pairs[start : start + CHUNK_SIZE]
        url = TENCENT_QUOTE + ",".join(quote_symbol(market, code) for market, code in chunk)
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("gbk", "ignore")
        except OSError:
            continue
        for line in text.split(";"):
            line = line.strip()
            if "=" not in line or '"' not in line:
                continue
            symbol = line.split("=", 1)[0].strip().removeprefix("v_")
            market = _market_of(symbol)
            if not market:
                continue
            fields = line.split('"')[1].split("~")
            if len(fields) < 46:
                continue
            price = _to_float(fields[3])
            if not price:
                continue
            pe_index, pb_index, currency_index = FIELD_LAYOUT[market]

            def field(index: int | None) -> str:
                return fields[index] if index is not None and index < len(fields) else ""

            quotes[f"{market}:{symbol[2:]}"] = {
                "price": price,
                "quote_time": fields[30],
                "pe_ttm": _to_float(field(pe_index)),
                "pb": _to_float(field(pb_index)),
                "market_cap_yi": _to_float(fields[45]),
                "currency": field(currency_index).strip() or CURRENCY_BY_MARKET[market],
            }
    return quotes

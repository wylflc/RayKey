#!/usr/bin/env python3
"""Batch A-share spot quotes from Tencent (qt.gtimg.cn).

Serves the pool MD daily price refresh (§6.7) and any script needing latest
price / PE-TTM / PB / total market cap. Tencent only, on purpose: the field
layout is stable and the same provider already backs the kline fallback in
screen/sell scans; Eastmoney's batch quote endpoint (ulist.np) returned 502
when evaluated on 2026-07-17.

Field indices in the "~"-separated payload (validated against 600900 on
2026-07-17): 3=最新价, 30=行情时间YYYYMMDDHHMMSS, 39=PE-TTM, 45=总市值(亿),
46=PB. Suspended stocks report price 0/blank and are omitted from the result.
"""

from __future__ import annotations

import urllib.request

TENCENT_QUOTE = "https://qt.gtimg.cn/q="
CHUNK_SIZE = 60


def quote_symbol(code: str, exchange: str = "") -> str:
    code = str(code).zfill(6)
    exchange = (exchange or "").upper()
    if exchange == "SSE" or code.startswith(("60", "68", "69")):
        return "sh" + code
    if exchange == "BSE" or code.startswith(("43", "83", "87", "88", "92")):
        return "bj" + code
    return "sz" + code


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_spot_quotes(
    items: list[tuple[str, str]], timeout: float = 8.0
) -> dict[str, dict[str, float | str | None]]:
    """items: (code, exchange) 列表 → {6位代码: {price, quote_time, pe_ttm, pb, market_cap_yi}}。

    请求失败的分片和停牌(价格为0)的代码不出现在结果里；调用方按"缺失即沿用旧值"降级。
    """
    pairs = [(str(code).zfill(6), exchange or "") for code, exchange in items]
    quotes: dict[str, dict[str, float | str | None]] = {}
    for start in range(0, len(pairs), CHUNK_SIZE):
        chunk = pairs[start : start + CHUNK_SIZE]
        url = TENCENT_QUOTE + ",".join(quote_symbol(code, exchange) for code, exchange in chunk)
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
            fields = line.split('"')[1].split("~")
            if len(fields) < 47:
                continue
            price = _to_float(fields[3])
            if not price:
                continue
            quotes[symbol[-6:]] = {
                "price": price,
                "quote_time": fields[30],
                "pe_ttm": _to_float(fields[39]),
                "market_cap_yi": _to_float(fields[45]),
                "pb": _to_float(fields[46]),
            }
    return quotes

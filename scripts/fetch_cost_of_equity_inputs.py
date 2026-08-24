#!/usr/bin/env python3
"""股权资本成本的两个输入：无风险利率 R_f 与股权风险溢价 ERP（§6.7）。

为什么需要它
------------
A 股生产 r 统一 10%（§6.5.1）；本序列服务①银行/保险股利折现的十年国债 rf（`rebuild_bank_bands.py`／扫描器缺省）、②海外 §6.8 的 r = 美债 10Y + β·ERP、③研究开关 `--r-mode market`——后者要求**逐期取当时的**
R_f 与 ERP——用 2026 年的利率回测 2017 年属 §12.4 前视。此前本仓库只有**一个**手抄的观测
点（2026-08-07），`--r-mode market` 因此跑历史带时 399/399 全部拒绝。本脚本补上历史序列。

两个来源，都免密钥
------------------
* **R_f：中国 10 年期国债收益率**。东财 `RPTA_WEB_TREASURYYIELD`，与本仓库其它取数同host、
  同免 token 端点（`datacenter-web.eastmoney.com/api/data/v1/get`）。
* **ERP：Damodaran 国家风险溢价表** `pages.stern.nyu.edu/.../ctryprem.xlsx`。xlsx 本质是
  zip 包 XML，故用标准库 `zipfile + ElementTree` 解析，**不引入 openpyxl/pandas 依赖**。

列名靠**恒等式自证**，不靠猜
----------------------------
东财该表列名是 `EMM00166466` 这类不可读代码。本脚本不硬编码「第 3 列就是 10Y」，而是用表
内自带的利差列做校验：`10Y − 2Y` 必须等于利差列，中美两组都对上才接受（实测两组都精确
相等）。Damodaran 表同理：评级口径与 CDS 口径各自的「总 ERP − 国家溢价」必须都等于同一个
成熟市场 ERP（实测都等于 4.23%）。**任一恒等式不成立即报错退出，不写文件。**

一个必须写明的欠缺：ERP 是常数，不随时间变
------------------------------------------
Damodaran 的**逐月**隐含 ERP 文件 `ERPbymonth.xlsx` 实测**只到 2022-07-31**，距今四年；
且它是**美国/成熟市场**口径，与中国国家溢价拼接会在接缝处产生跳变。两害相权，本脚本取
**当前 ERP 常数 + 逐期变动的 R_f**，并把这个选择连同它的偏误方向写进输出文件：

    ERP 取常数 ⇒ **危机期（2015 股灾、2018）真实 ERP 会飙升，本口径低估当时的 r，
    从而高估当时的内在价值。** 读那几年的带时须知道这一条。

R_f 的时间变动本身是主要驱动：实测中国 10Y 由 2011 年的约 4% 降到 2026 年的 1.71%，
逾 200bp，方向与幅度都远大于 ERP 的常见波动。

用法::

    python3 scripts/fetch_cost_of_equity_inputs.py
    python3 scripts/fetch_cost_of_equity_inputs.py --since 2008-01-01 --frequency monthly
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/reference/cost_of_equity_inputs.csv"

YIELD_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
YIELD_REPORT = "RPTA_WEB_TREASURYYIELD"
CTRYPREM_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx"
ERP_MONTHLY_URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

# 东财该表的不可读列名。**不假定其含义**——下面用利差恒等式验证后才采用。
CN_2Y, CN_5Y, CN_10Y, CN_30Y, CN_SPREAD = ("EMM00588704", "EMM00166462",
                                           "EMM00166466", "EMM00166469", "EMM01276014")
US_2Y, US_10Y, US_SPREAD = "EMG00001306", "EMG00001310", "EMG01339436"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class SourceError(RuntimeError):
    """来源不可用或**自证恒等式不成立**时抛出——宁可不写文件，也不写一份没验过的。"""


# ------------------------------------------------------------------ xlsx（标准库）
def read_xlsx(payload: bytes, sheet_name: str) -> list[dict[str, str]]:
    """把 xlsx 的某个工作表读成 [{列字母: 值}]。xlsx = zip 包 XML，故无需第三方库。"""
    archive = zipfile.ZipFile(io.BytesIO(payload))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    paths = {s.get("name"): "xl/" + rels[s.get(RS + "id")].lstrip("/")
             for s in workbook.iter(NS + "sheet")}
    if sheet_name not in paths:
        raise SourceError(f"工作表 {sheet_name!r} 不存在，实有：{sorted(paths)}")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        table = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(NS + "t")) for si in table.iter(NS + "si")]
    rows = []
    for row in ET.fromstring(archive.read(paths[sheet_name])).iter(NS + "row"):
        cells = {}
        for cell in row.iter(NS + "c"):
            value = cell.find(NS + "v")
            if value is None:
                continue
            cells[re.sub(r"\d", "", cell.get("r"))] = (
                shared[int(value.text)] if cell.get("t") == "s" else value.text)
        if cells:
            rows.append(cells)
    return rows


def fetch(url: str, timeout: float) -> bytes:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"{url} 取数失败（{type(exc).__name__}）") from exc


# ------------------------------------------------------------------ R_f
def fetch_treasury_yields(timeout: float, pause: float) -> list[tuple[str, float]]:
    """(日期, 中国 10Y 收益率小数) 升序。列名由利差恒等式自证。"""
    import time
    rows: dict[str, float] = {}
    verified = False
    page, pages = 1, None
    while True:
        url = (f"{YIELD_API}?reportName={YIELD_REPORT}&columns=ALL&pageSize=500"
               f"&pageNumber={page}&sortColumns=SOLAR_DATE&sortTypes=-1")
        payload = json.loads(fetch(url, timeout).decode("utf-8", "replace"))
        result = payload.get("result") or {}
        pages = pages if pages is not None else result.get("pages")
        data = result.get("data") or []
        if not data:
            break
        for item in data:
            cn10 = item.get(CN_10Y)
            if cn10 is None:
                continue
            rows[item["SOLAR_DATE"][:10]] = cn10 / 100.0
            if not verified:
                verified = _verify_columns(item)
        if pages and page >= int(pages):
            break
        page += 1
        time.sleep(pause)
    if not verified:
        raise SourceError("利差恒等式一次都没验成——**不接受这份数据**，列名含义未证实")
    return sorted(rows.items())


def _verify_columns(item: dict) -> bool:
    """`10Y − 2Y == 利差列`，中美两组都要成立。这是列名含义的**证据**，不是假设。"""
    checks = ((item.get(CN_10Y), item.get(CN_2Y), item.get(CN_SPREAD)),
              (item.get(US_10Y), item.get(US_2Y), item.get(US_SPREAD)))
    for long, short, spread in checks:
        if None in (long, short, spread) or abs(long - short - spread) > 1e-6:
            return False
    return True


def month_end_samples(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """每月最后一个有观测的交易日。ERP 本身只有月度精度，R_f 取月末即可，且比单日更稳。"""
    latest: dict[str, tuple[str, float]] = {}
    for day, value in series:
        latest[day[:7]] = (day, value)
    return sorted(latest.values())


# ------------------------------------------------------------------ ERP
def fetch_china_erp(timeout: float) -> tuple[float, float, float]:
    """(中国总 ERP, 中国国家风险溢价, 成熟市场 ERP)，均为小数。用两套口径互证。"""
    rows = read_xlsx(fetch(CTRYPREM_URL, timeout), "ERPs by country")
    china = next((r for r in rows if str(r.get("A", "")).strip() == "China"), None)
    if china is None:
        raise SourceError("Damodaran 国家表里找不到 China 行")
    try:
        erp_rating, crp_rating = float(china["E"]), float(china["F"])
        erp_cds, crp_cds = float(china["H"]), float(china["I"])
    except (KeyError, ValueError) as exc:
        raise SourceError(f"China 行列位与预期不符：{china}") from exc
    # 自证：评级口径与 CDS 口径各自的「总 ERP − 国家溢价」必须是同一个成熟市场 ERP
    mature_rating, mature_cds = erp_rating - crp_rating, erp_cds - crp_cds
    if abs(mature_rating - mature_cds) > 5e-4:
        raise SourceError(f"成熟市场 ERP 两口径不一致（{mature_rating:.4%} vs {mature_cds:.4%}）"
                          f"——列位可能已变，**不接受**")
    return erp_rating, crp_rating, mature_rating


def monthly_erp_coverage(timeout: float) -> str | None:
    """Damodaran 逐月隐含 ERP 的覆盖终点——用来把「为什么 ERP 只能取常数」讲成可核对的事实。"""
    try:
        rows = read_xlsx(fetch(ERP_MONTHLY_URL, timeout), "Historical ERP")
    except SourceError:
        return None
    serials = [float(r["A"]) for r in rows if r.get("A", "").replace(".", "").isdigit()]
    if not serials:
        return None
    return (date(1899, 12, 30).toordinal() + int(max(serials))) and \
        date.fromordinal(date(1899, 12, 30).toordinal() + int(max(serials))).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="取 R_f 与 ERP 历史序列（§6.7）")
    parser.add_argument("--since", default="2010-01-01", help="起始日期，缺省 2010-01-01")
    parser.add_argument("--frequency", choices=("monthly", "daily"), default="monthly")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--pause", type=float, default=0.2)
    args = parser.parse_args()

    try:
        print("① 取中国 10 年期国债收益率（东财 RPTA_WEB_TREASURYYIELD，免 token）…")
        series = [x for x in fetch_treasury_yields(args.timeout, args.pause) if x[0] >= args.since]
        print(f"   ✅ 利差恒等式已验（10Y−2Y 中美两组均相等）｜{len(series):,} 个交易日"
              f"｜{series[0][0]} ~ {series[-1][0]}")
        print("② 取 Damodaran 国家风险溢价（标准库解 xlsx，无新依赖）…")
        erp, crp, mature = fetch_china_erp(args.timeout)
        print(f"   ✅ 成熟市场 ERP 两口径互证一致 = {mature:.2%}"
              f"｜中国国家风险溢价 {crp:.2%}｜**中国总 ERP {erp:.2%}**")
        coverage = monthly_erp_coverage(args.timeout)
    except SourceError as exc:
        print(f"**失败：{exc}**\n未写任何文件（宁可没有，也不要一份没验过的）")
        return 1

    samples = month_end_samples(series) if args.frequency == "monthly" else series
    stamp = datetime.now(timezone.utc).date().isoformat()
    note = (f"R_f=中国10Y国债(东财,利差恒等式已验)；ERP=Damodaran中国总ERP，"
            f"**取常数不随时间变**"
            + (f"（其逐月隐含ERP文件只到 {coverage}，且为美国口径，拼接会有接缝）" if coverage else "")
            + "；偏误方向：危机期真实ERP飙升，本口径低估当时r、高估当时内在价值")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["observed_on", "risk_free_rate", "equity_risk_premium", "source", "note"])
        for day, rf in samples:
            writer.writerow([day, f"{rf:.6f}", f"{erp:.6f}",
                             f"eastmoney {YIELD_REPORT} + damodaran ctryprem.xlsx (fetched {stamp})",
                             note])
    print(f"\n已写入 {args.out.relative_to(ROOT)}：{len(samples):,} 行"
          f"（{samples[0][0]} ~ {samples[-1][0]}，{args.frequency}）")

    lo, hi = min(x[1] for x in samples), max(x[1] for x in samples)
    print(f"R_f 区间 {lo:.2%} ~ {hi:.2%}｜期末 {samples[-1][1]:.2%}"
          f"  → β=1 时 r 由 {hi + erp:.2%} 降到 {samples[-1][1] + erp:.2%}")
    print(f"⚠ **ERP 为常数** {erp:.2%}：r 的全部时间变动都来自 R_f。"
          f"危机期（2015 股灾、2018）真实 ERP 会飙升，本口径低估当时 r、高估当时内在价值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

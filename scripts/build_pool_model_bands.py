#!/usr/bin/env python3
"""生成 §6.7 链条的池模型带文件（v4.00：ROIC 口径），供 apply→校验→池物化与日线扫描消费。

职责（§6.5.2.3 的落点）：
1. 从 `roic_bands.csv`（§6.7 第 2 步产物）取**池内每只**的最新 `ok` 带
   （排序键 `(available_at, report_date)`，与 `apply_model_bands_to_dossiers.py` 同规）；
2. **银行行的 V 改写为股利折现值**——取自采纳逐日状态最后一行的 `intrinsic_value`
   （§6.7 第 3 步已把 divspread 烙进去，且已按送转折算到现价基准；银行近年无送转，
   与 apply 的报告期基准假设不冲突）；
3. 写 `a_share_pool_model_bands_adopted.csv`。**列 = roic_bands 的原列**（含 `roic_path`／
   `nopat_ps`／`wacc` 等），下游按列名取用，多列无害。

用法：
    python3 scripts/build_pool_model_bands.py            # 缺省路径
    python3 scripts/build_pool_model_bands.py --as-of 2026-08-16
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
BANDS = ROOT / "data/processed/roic_bands.csv"
STATES = ROOT / "data/processed/a_share_daily_states_adopted.csv"
OUT = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"


from divspread_names import is_divspread_financial   # v4.56：银行＋保险同一判定（OI-085）


def is_bank(name: str, code: str = "") -> bool:
    # 「银」单字会把兴业银锡(000426)这类矿业股误判成银行（2026-08-16 踩中）；判定统一在 divspread_names。
    return is_divspread_financial(code, name)


def main() -> int:
    ap = argparse.ArgumentParser(description="池模型带文件（ROIC 口径 + 银行股利折现）")
    ap.add_argument("--as-of", default="9999-12-31", help="只取 available_at ≤ 此日的带")
    ap.add_argument("--pool", type=Path, default=POOL)
    ap.add_argument("--bands", type=Path, default=BANDS)
    ap.add_argument("--states", type=Path, default=STATES)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()

    with a.pool.open(encoding="utf-8-sig") as fh:
        pool = {r["security_code"].zfill(6): r.get("security_name", "")
                for r in csv.DictReader(fh) if r.get("security_code")}
    # 成员 = 池（v4.54，OI-083 用户指令）：分层表 worth_attention 的 L1-L3 ∪ 池 CSV。
    # 此前并入逐票档案是为了给池外观察行档案供带（apply 只读本文件），代价是 L4/boundary 点名
    # 档案的带也进了生产带文件，与 §6.1「只落档案、不落生产带文件」不符；现由
    # `apply_model_bands_to_dossiers.py` 对池外档案直接读 roic_bands.csv，本文件只写池成员。
    tiers = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
    if tiers.exists():
        with tiers.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                c = (r.get("security_code") or "").zfill(6)
                if (c and c != "000000" and c not in pool
                        and (r.get("attention_class") or "worth_attention") == "worth_attention"
                        and (r.get("quality_tier") or "") in ("L1", "L2", "L3")):
                    pool[c] = r.get("security_name", "")
    print(f"成员 {len(pool)} 只 ← 池（分层表 L1-L3 ∪ 池 CSV；池外档案不进生产带文件）")

    best: dict[str, dict] = {}
    evaluated: dict[str, str] = {}
    fields: list[str] = []
    with a.bands.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        for row in reader:
            code = row["security_code"].zfill(6)
            avail = row.get("available_at") or ""
            if code not in pool or not avail or avail > a.as_of:
                continue
            # 模型最近评估过的报告期可得日（含护栏拒绝行）：§7.3 估值复核日读它，
            # 采纳带停在更早 ok 行时不再把已评估的新报告期重复入队。
            if avail > evaluated.get(code, ""):
                evaluated[code] = avail
            if row.get("status") != "ok":
                continue
            key = (avail, row.get("report_date") or "")
            if code not in best or key > (best[code].get("available_at", ""),
                                          best[code].get("report_date", "")):
                best[code] = row

    # 银行：V 换成采纳逐日状态最后一行的股利折现值
    bank_codes = {c for c, n in pool.items() if is_bank(n, c)}
    bank_last: dict[str, dict] = {}
    with a.states.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            c = row["security_code"].zfill(6)
            if c in bank_codes:
                prev = bank_last.get(c)
                if prev is None or row["date"] > prev["date"]:
                    bank_last[c] = row
    replaced = 0
    for c, row in best.items():
        if c in bank_codes and c in bank_last:
            v = float(bank_last[c]["intrinsic_value"])
            row["intrinsic_value"] = f"{v:.4f}"
            row["band_low"], row["band_high"] = f"{v * 0.90:.4f}", f"{v * 1.10:.4f}"
            row["roic_path"] = "bank_divspread"
            replaced += 1

    if "model_evaluated_at" not in fields:
        fields.append("model_evaluated_at")
    for c, row in best.items():
        row["model_evaluated_at"] = max(evaluated.get(c, ""), row.get("available_at") or "")

    missing = sorted(set(pool) - set(best))
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, restval="")
        w.writeheader()
        for c in sorted(best):
            w.writerow(best[c])
    print(f"带 {len(best)}/{len(pool)} 只（银行改写 {replaced}）→ {a.out.name}")
    if missing:
        # 无 ok 带 = 模型判不可估或数据不全 → 走 §6.5.2.4 手工带，不静默
        names = "、".join(pool[c] for c in missing)
        print(f"⚠ 无模型带 {len(missing)} 只（走 §6.5.2.4 手工带或建档队列）：{names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

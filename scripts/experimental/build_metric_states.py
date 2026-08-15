"""把逐日状态里的 `valuation_ratio` 换成另一个**估值指标**，产出可直接喂给回测的同形文件。

用途是用户 2026-08-15 提出的重构：**每只股票只跟自己比**——先给每只股票一条自己的估值指标
时间序列，回测再把它转成「相对该股自身历史的分位」当买卖闸门（`--gate self-pct`）。
本脚本只负责**指标**这一层，分位在回测里逐日算（那样窗口长度可扫、且严格无前视）。

四个指标
--------
``pv``     现有 DCF 口径 `P/V`，直接透传（不必跑本脚本，原文件即是）。
``pb``     `收盘 ÷ 每股净资产`。分母最平滑，周期股盈利崩塌时不会假装变贵。
``pe``     `收盘 ÷ 每股 TTM 盈利`。用户点名的最简口径。**亏损期整行丢弃**——
           负 PE 无法排序，留着会把「亏到没法估值」读成「便宜到极点」。
           这等于给该股当日**不可买**，是本指标自带的样本损失，读数时须记住。
``pbroe``  `收盘 ÷ (每股净资产 × roe0)`，即 **PB ÷ 正常化 ROE**，也就是
           「在**正常化盈利**上的 PE」。它同时避开 `pe` 的周期陷阱（分母不用当期盈利）
           与 `pb` 的盲点（盈利能力永久下台阶时分母会跟着降），是四个里唯一
           把「便宜」和「赚钱能力」绑在一起的。

送转折算
--------
逐日文件的 `intrinsic_value` 是**已按 `split_factor` 折算过**的口径（每股价值 ÷ split_factor），
故每股基本面一律照做：`分母 = 基本面 ÷ split_factor`。已用 IV 逐位比对验证过这条约定
——按采用口径重建的带（`--roe-source onesided_max --roe-lift 2.0 --uniform-tier L2`）
与在跑的逐日状态 802,574 行中 693,673 行 IV 完全相同，其余 108,901 行恰是 41 只银行
（银行行被 `rebuild_bank_bands.py` 的股利折现覆盖过，`bps`/`eps_ttm` 不受影响）。

用法
----
    python3 scripts/experimental/build_metric_states.py \
        --metric pb --bands <采用口径重建的带.csv> --out data/processed/metric_states/pb.csv

`--bands` **必须与在跑的逐日状态同源**。带文件在 `.gitignore` 内，按 §9.7.1.2 重建：
    python3 scripts/build_historical_valuation_bands.py --codes-file <逐日里的全部代码> \
        --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
        --out-bands <带> --out-daily <弃用>
"""
import argparse
import csv
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAILY = ROOT / "data/processed/a_share_daily_states_adopted.csv"

# 每个指标的分母：拿一行带（已转 float 的 dict）算出**每股**基本面，取不到或非正数返回 None。
# 非正数一律返回 None 而不是留着——负净资产/负盈利做出来的比值不可排序（见文件头）。
DENOM = {
    "pb": lambda b: b.get("bps"),
    "pe": lambda b: b.get("eps_ttm"),
    "pbroe": lambda b: (b["bps"] * b["roe0"]
                        if b.get("bps") and b.get("roe0") else None),
}


def _f(text):
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metric", choices=sorted(DENOM), required=True)
    ap.add_argument("--bands", type=Path, required=True, help="与在跑逐日状态同源的带")
    ap.add_argument("--daily", type=Path, default=DAILY)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    # 带按 (代码, 报告期, 可得日) 索引——**必须带上可得日**，否则同一报告期的重述会串行
    # （实测 002415 的 2022-12-31 有多条，只按报告期取会拿错一条）。
    fund: dict[tuple[str, str, str], float] = {}
    with a.bands.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("status") != "ok":
                continue
            row = {k: _f(r.get(k)) for k in ("bps", "eps_ttm", "roe0")}
            d = DENOM[a.metric](row)
            if d is not None and d > 0:
                fund[(r["security_code"].zfill(6), r["report_date"], r["available_at"])] = d

    a.out.parent.mkdir(parents=True, exist_ok=True)
    kept = collections.Counter()
    with a.daily.open(newline="", encoding="utf-8") as src, \
            a.out.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for r in reader:
            kept["逐日总行"] += 1
            key = (r["security_code"], r["band_report_date"], r["band_available_at"])
            base = fund.get(key)
            sf = _f(r["split_factor"]) or 1.0
            close = _f(r["close"])
            if base is None:
                kept["分母缺失或非正·丢弃"] += 1
                continue
            if not close or close <= 0:
                kept["无收盘·丢弃"] += 1
                continue
            per_share = base / sf              # 与 IV 同一送转约定
            r["intrinsic_value"] = f"{per_share:.6f}"
            r["band_low"] = r["band_high"] = f"{per_share:.6f}"
            r["valuation_ratio"] = f"{close / per_share:.6f}"
            r["upside_to_low"] = r["valuation_label"] = ""
            writer.writerow(r)
            kept["写出"] += 1

    codes = set()
    with a.out.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            codes.add(r["security_code"])
    print(f"指标 {a.metric}｜" + "｜".join(f"{k} {v:,}" for k, v in kept.items())
          + f"｜覆盖 {len(codes)} 只 → {a.out}")


if __name__ == "__main__":
    main()

"""把「成长档」内的逐日估值行换成另一套模型的产出，**档外的行逐位不动**。

这是 §12.38 分档估值的执行件：资源股/周期股/银行的 `P/V` 完全保留现状（它们原有的合格日
与换仓排序位置一个不变），只在成长档内替换成长股那一侧的估值。

三种成长口径（对应用户 2026-08-13 给的三条思路）：
  --from <逐日文件>   直接取另一套建带产出（如 `--n1 5`、`--roe-source onesided_max`）
  --scale K          把成长档内的内在价值乘 K（K=2 即「估值带除以 2」，P/V 减半）
两者可叠加：先取 `--from`，再乘 `--scale`。

`valuation_ratio`、`band_low/high`、`upside_to_low` 一并按新内在价值重算，
与 `rebuild_bank_bands.py` 的写法保持一致。

用法：
    python3 splice_growth_bands.py --base <基准逐日> --seg <成长档CSV> --out <输出> \
        [--from <替换源逐日>] [--scale 2.0]
"""
import csv, argparse, collections, bisect


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def load_seg(p):
    seg = collections.defaultdict(list)
    for r in csv.DictReader(open(p, encoding="utf-8")):
        seg[r["security_code"]].append((r["effective_from"], r["effective_to"] or "2099-12-31"))
    for c in seg:
        seg[c].sort()
    return seg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--seg", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="src")
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()

    seg = load_seg(a.seg)
    src = {}
    if a.src:
        for r in csv.DictReader(open(a.src, encoding="utf-8")):
            v = num(r.get("intrinsic_value"))
            if v and v > 0:
                src[(r["security_code"], r["date"])] = v

    in_seg = lambda c, d: any(lo <= d < hi for lo, hi in seg.get(c, ()))
    n_rep = n_keep = n_miss = 0
    with open(a.base, encoding="utf-8") as fi, open(a.out, "w", encoding="utf-8", newline="") as fo:
        rd = csv.DictReader(fi)
        w = csv.DictWriter(fo, fieldnames=rd.fieldnames)
        w.writeheader()
        for r in rd:
            c, d = r["security_code"], r["date"]
            if not in_seg(c, d):
                w.writerow(r); n_keep += 1; continue
            px = num(r.get("close"))
            v = src.get((c, d)) if a.src else num(r.get("intrinsic_value"))
            if v is None and a.src:
                # 替换源缺该行（护栏拒绝等）：**保留基准行，不静默丢弃**
                w.writerow(r); n_miss += 1; continue
            if v is None or v <= 0 or not px or px <= 0:
                w.writerow(r); n_miss += 1; continue
            v *= a.scale
            r["intrinsic_value"] = f"{v:.4f}"
            r["band_low"] = f"{v*0.9:.4f}"
            r["band_high"] = f"{v*1.1:.4f}"
            r["valuation_ratio"] = f"{px/v:.4f}"
            r["upside_to_low"] = f"{v*0.9/px-1:.4f}"
            w.writerow(r); n_rep += 1
    print(f"成长档内替换 {n_rep:,} 行｜档内但替换源缺失而保留 {n_miss:,} 行｜档外原样 {n_keep:,} 行 → {a.out}")


if __name__ == "__main__":
    main()

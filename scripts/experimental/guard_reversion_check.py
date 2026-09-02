#!/usr/bin/env python3
"""周期守卫的机制层核对（OI-135 C6 的系统化形态）：峰／谷守卫触发的年份，其后三年利润率是否真的回到中位？

守卫的前提是**均值回归**——`当期比率 / 十年中位` 越过 K±ramp 时把锚拉向窗口中位。
本脚本不看回测收益，只问：被守卫触发的 (公司, 年份) 里，有多大比例在三年内真的回到了非触发区？
  谷侧：触发年 ROE 低到十年中位 / 1.3 以下 → 其后三年 ROE 最高值是否 ≥ 十年中位 / 1.3（脱离谷区）／ ≥ 中位（完全回归）
  峰侧：触发年 ROE 高到十年中位 × 1.3 以上 → 其后三年 ROE 最低值是否 ≤ 十年中位 × 1.3（脱离峰区）／ ≤ 中位（完全回归）
比率用带文件年报行的 `roe_ttm`（母公司净利 / 权益）作 NOPAT/E_op 的代理，十年中位含当年（与建带同窗）。
只用年报行；季报行的触发只计数。

用法：
  guard_reversion_check.py [--bands data/processed/roic_bands.csv]
                           [--universe data/processed/pit_attention/panel_moat_bank_v6b.csv]
                           [--codes 600066,002128,...]   # 逐票列出触发年份与结局
                           [--horizon 3]                 # 其后几年内算「脱离」
另按建带自身的周期判定拆分（带文件 `roe_window` = 9 即 ROE 序列被判周期态：单调度 < 0.35 且振幅 > 中位一半）。
"""
import argparse
import collections
import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K, RAMP = 1.6, 0.3
EDGE = K - RAMP          # 1.3：坡道起点，越过即开始触发


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load(bands: Path):
    annual = collections.defaultdict(dict)      # code -> {year: roe}
    names, trig = {}, []                         # trig: (code, year, side, weight, cyclical)
    q_trig = collections.Counter()
    with bands.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code, rd = r["security_code"], r["report_date"]
            names[code] = r["security_name"]
            pw, tw = fnum(r.get("peak_weight")) or 0.0, fnum(r.get("trough_weight")) or 0.0
            if rd.endswith("-12-31"):
                roe = fnum(r.get("roe_ttm"))
                if roe is not None:
                    annual[code][int(rd[:4])] = roe
                cyc = (r.get("roe_window") or "") == "9"
                if tw > 0:
                    trig.append((code, int(rd[:4]), "trough", tw, cyc))
                if pw > 0:
                    trig.append((code, int(rd[:4]), "peak", pw, cyc))
            else:
                if tw > 0:
                    q_trig["trough"] += 1
                if pw > 0:
                    q_trig["peak"] += 1
    return annual, names, trig, q_trig


def judge(series: dict, year: int, side: str, horizon: int = 3):
    """返回 (十年中位, 当年, 前三年极值, 脱离触发区?, 完全回归?) 或 None（数据不足／未到期）。"""
    win = [series[y] for y in range(year - 9, year + 1) if y in series]
    if len(win) < 4 or year not in series:
        return None
    med = statistics.median(win)
    fwd = [series[y] for y in range(year + 1, year + 1 + horizon) if y in series]
    if len(fwd) < horizon:
        return None
    cur = series[year]
    if side == "trough":
        ext = max(fwd)
        return med, cur, ext, ext >= med / EDGE, ext >= med
    ext = min(fwd)
    return med, cur, ext, ext <= med * EDGE, ext <= med


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bands", type=Path, default=ROOT / "data/processed/roic_bands.csv")
    ap.add_argument("--universe", type=Path, default=ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv")
    ap.add_argument("--codes", default="", help="逐票列出触发年份与结局（逗号分隔）")
    ap.add_argument("--top", type=int, default=25, help="按触发年数列出前 N 家（宇宙内）")
    ap.add_argument("--horizon", type=int, default=3)
    args = ap.parse_args()

    annual, names, trig, q_trig = load(args.bands)
    universe = set()
    if args.universe.exists():
        with args.universe.open(encoding="utf-8") as fh:
            universe = {r["security_code"] for r in csv.DictReader(fh)}

    print(f"带文件 {args.bands.name}：年报行触发 谷 {sum(1 for t in trig if t[2]=='trough')} ／ 峰 {sum(1 for t in trig if t[2]=='peak')}；"
          f"季报行触发（只计数）谷 {q_trig['trough']} ／ 峰 {q_trig['peak']}")
    H = args.horizon
    print(f"判据：谷侧脱离 = 其后 {H} 年 ROE 最高 ≥ 十年中位/{EDGE}，完全回归 = ≥ 中位；峰侧对称。十年中位含当年，需 ≥4 年；其后 {H} 年须齐（未到期不计）。\n")

    per_code = collections.defaultdict(lambda: collections.Counter())
    for scope, codes in (("全市场", None), ("v6b 宇宙", universe)):
        for side in ("trough", "peak"):
            n = esc = full = pend = 0
            deep = collections.Counter()   # 按触发年偏离深度分桶
            cyc_split = collections.Counter()
            for code, year, s, w, cyc in trig:
                if s != side or (codes is not None and code not in codes):
                    continue
                res = judge(annual[code], year, side, H)
                if res is None:
                    pend += 1
                    continue
                med, cur, ext, out, back = res
                n += 1
                esc += out
                full += back
                ratio = (med / cur) if side == "trough" and cur > 0 else (cur / med if side == "peak" and med > 0 else float("inf"))
                bucket = "≥3× 或当年≤0" if ratio >= 3 or cur <= 0 else ("2~3×" if ratio >= 2 else "1.3~2×")
                deep[bucket, out] += 1
                cyc_split[cyc, out] += 1
                if codes is not None:
                    per_code[code][side, "n"] += 1
                    per_code[code][side, "esc"] += out
            label = "谷底对称守卫" if side == "trough" else "峰守卫"
            print(f"[{scope}] {label}：可判 {n}（未到期/数据不足 {pend}）→ {H} 年内脱离触发区 {esc}（{esc/n*100 if n else 0:.1f}%），完全回到中位 {full}（{full/n*100 if n else 0:.1f}%）")
            for cyc, tag in ((True, "建带判周期态（roe_window=9）"), (False, "建带判非周期态")):
                y, nn = cyc_split[cyc, True], cyc_split[cyc, False]
                if y + nn:
                    print(f"    {tag:>22}：{y+nn:4d} 例，脱离 {y}（{y/(y+nn)*100:.0f}%）")
            for b in ("1.3~2×", "2~3×", "≥3× 或当年≤0"):
                y, nn = deep[b, True], deep[b, False]
                if y + nn:
                    print(f"    偏离 {b:>10}：{y+nn:4d} 例，脱离 {y}（{y/(y+nn)*100:.0f}%）")
        print()

    rows = sorted(per_code.items(), key=lambda kv: -kv[1]["trough", "n"])
    print(f"宇宙内按谷守卫触发年数排前 {args.top} 家（可判年数／三年内脱离谷区数）：")
    for code, c in rows[: args.top]:
        if c["trough", "n"] == 0:
            break
        print(f"  {code} {names.get(code,''):<8} 谷 {c['trough','n']:2d}/{c['trough','esc']:2d}   峰 {c['peak','n']:2d}/{c['peak','esc']:2d}")

    if args.codes:
        print("\n逐票（年份：当年 ROE ／ 十年中位 → 其后三年极值 ⇒ 脱离?／回归?）")
        for code in args.codes.split(","):
            code = code.strip()
            print(f"  {code} {names.get(code, '?')}")
            for c, year, side, w, cyc in sorted(t for t in trig if t[0] == code):
                res = judge(annual[code], year, side, H)
                if res is None:
                    print(f"    {year} {side:6s} w={w:.2f} {'周期' if cyc else '非周期'}  未到期/数据不足")
                    continue
                med, cur, ext, out, back = res
                print(f"    {year} {side:6s} w={w:.2f} {'周期' if cyc else '非周期'}  {cur*100:6.1f}% ／ {med*100:6.1f}% → {ext*100:6.1f}%  ⇒ {'脱离' if out else '未脱离'}／{'回归' if back else '未回归'}")


if __name__ == "__main__":
    main()

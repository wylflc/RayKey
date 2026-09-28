"""OI-212 研究开关补丁：把 `--reset-guard` 写进建带脚本（先用于副本试跑，OI-205 重测作业结束后再用于正式脚本）。

    python3 patch_bands.py <目标 .py>
"""
import sys
from pathlib import Path

HELPER_ANCHOR = 'def entity_reset_for(code: str, as_of: str) -> str | None:'
HELPER = '''def reset_guard_anchor(code: str, as_of: str, latest_ratio: float, f_ttm: float, e_op, tax_norm, args):
    """OI-212 研究开关：主体重置后不足三个年报的行的周期守卫参照，返回 (当期比率 ÷ 十年中位 s, 周期锚比率) 或 None。

    周期位置一律用不受杠杆与少数股东影响的回报率在自身时序上的位置（比率 NOPAT ÷ 经营账面会被并表、少数股东与杠杆变化扭曲，
    跨重置不可比）：`s = TTM 因子 × 最新年报回报 ÷ 十年中位`，周期锚 = 最新年报比率 ÷ (最新年报回报 ÷ 五年中位)，
    与通用路径「峰谷坡道混向五年中位」同义。
    `pre_reset`（同类业务并入）：回报 = ROIC（`roic_inputs.roic_of`），窗口不截到重置日，取重置前后连续的年报。
    `peers`（重置前主体为壳、不可比）：回报 = 同业逐季面板年报加权 ROE，各同业的位置取中位（至少 2 家）。
    登记表 `data/reference/entity_reset_guard_anchor.csv`；数据不足或中位非正返回 None（仍按无守卫）。"""
    spec = RESET_GUARD_ANCHOR.get(code)
    if not spec:
        return None
    window = max(args.roe_years, 10)

    def position(values):
        if len(values) < 4 or values[-1] <= 0:
            return None
        m10, m5 = statistics.median(values[-window:]), statistics.median(values[-args.roe_years:])
        return (values[-1] / m10, values[-1] / m5) if m10 > 0 and m5 > 0 else None
    if spec["anchor"] == "pre_reset":
        hist = sorted(roic_inputs.years_before(ROIC_YEARS.get(code, {}), as_of, window + 1), key=lambda y: y.period)
        if tax_norm is not None:
            hist = roic_inputs.with_tax_rate(hist, tax_norm)
        rois = [roic_inputs.roic_of(y, prev) for prev, y in zip([None] + hist[:-1], hist)]
        pos = position([x for x in rois[-window:] if x is not None])
        return None if pos is None else (f_ttm * pos[0], latest_ratio / pos[1])
    found = []
    for peer in spec["peers"]:
        series = series_as_of(PEER_SERIES.get(peer, {}), as_of)
        roes = [_num(series[p].get("weightavg_roe")) for p in sorted(series)
                if p.endswith("12-31") and (series[p].get("notice_date") or "9999") <= as_of]
        pos = position([x / 100.0 for x in roes if x is not None])
        if pos:
            found.append(pos)
    if len(found) < 2:
        return None
    return f_ttm * statistics.median(p[0] for p in found), latest_ratio / statistics.median(p[1] for p in found)


'''

BRANCH_OLD = '''                    ratio_noncyc = ratios[-1] * f_ttm
                    ratio_cyc = ratio_noncyc
                    peak_w = trough_w = 0.0
                    band.peak_weight, band.trough_weight = 0.0, 0.0
                    nopat_cyclical = False
'''
BRANCH_NEW = '''                    ratio_noncyc = ratios[-1] * f_ttm
                    ratio_cyc = ratio_noncyc
                    peak_w = trough_w = 0.0
                    band.peak_weight, band.trough_weight = 0.0, 0.0
                    nopat_cyclical = False
                    # OI-212 研究开关 --reset-guard：重置行按登记的参照恢复峰（peak）或峰谷（both）守卫，坡道与通用路径同式
                    anchor = (reset_guard_anchor(code, available_at, ratios[-1], f_ttm, e_op, tax_norm, args)
                              if getattr(args, "reset_guard", "off") != "off" and guard_applies(code) else None)
                    if anchor is not None:
                        s_reset, ratio_cyc = anchor
                        ramp_r, k_r = args.roic_peak_ramp, args.roic_peak_k
                        if ramp_r > 0:
                            peak_w = min(1.0, max(0.0, (s_reset - (k_r - ramp_r)) / (2 * ramp_r)))
                        else:
                            peak_w = 1.0 if s_reset > k_r else 0.0
                        if args.reset_guard == "both" and s_reset > 0:
                            trough_w = (min(1.0, max(0.0, (1.0 / s_reset - (k_r - ramp_r)) / (2 * ramp_r))) if ramp_r > 0
                                        else (1.0 if 1.0 / s_reset > k_r else 0.0))
                        band.peak_weight, band.trough_weight = peak_w, trough_w
                        nopat_cyclical = peak_w >= 0.5
                        ROIC_STATS[f"主体重置·守卫参照（OI-212 {RESET_GUARD_ANCHOR[code]['anchor']}）"] += 1
'''

ARG_ANCHOR = '''    parser.add_argument("--cash-caliber", choices=roic_inputs.CASH_CALIBERS, default="nonop",'''
ARG_NEW = '''    parser.add_argument("--reset-guard", choices=("off", "peak", "both"), default="off",
                        help="研究开关（OI-212）：主体重置后不足三个年报的行按 --reset-guard-file 登记的参照（重置前主体或同业）"
                             "恢复周期守卫——peak=只峰侧，both=峰谷两侧；off=缺省＝生产（重置行无守卫）")
    parser.add_argument("--reset-guard-file", type=Path, default=RESET_GUARD_FILE, metavar="CSV",
                        help="OI-212 守卫参照登记表（security_code,anchor=pre_reset|peers,peer_codes 以分号分隔）")
'''

GLOBAL_ANCHOR = 'ENTITY_RESET_FILE = ROOT / "data/processed/entity_reset_dates.csv"\n'
GLOBAL_NEW = ('RESET_GUARD_FILE = ROOT / "data/reference/entity_reset_guard_anchor.csv"   # OI-212 研究开关的守卫参照\n'
              'RESET_GUARD_ANCHOR: dict[str, dict] = {}\n'
              'PEER_SERIES: dict[str, dict[str, dict]] = {}   # OI-212 同业参照的逐季面板（只在开关打开时载入）\n')

LOAD_ANCHOR = '''        if not ROIC_YEARS:
            print(f"**{args.statements_dir} 无三大报表**，roic 口径无法建带。"'''
LOAD_NEW = '''        if args.reset_guard != "off":
            with args.reset_guard_file.open(encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    RESET_GUARD_ANCHOR[r["security_code"].strip().zfill(6)] = dict(
                        anchor=r["anchor"].strip(), peers=[p.strip().zfill(6) for p in (r.get("peer_codes") or "").split(";") if p.strip()])
            peers = {p for v in RESET_GUARD_ANCHOR.values() for p in v["peers"]}
            PEER_SERIES.update(load_financials(peers, notice_cap=(args.notice_cap == "statutory")))
            print(f"主体重置守卫参照（OI-212 --reset-guard {args.reset_guard}）：{len(RESET_GUARD_ANCHOR)} 只 ← {args.reset_guard_file}")
'''


def main():
    path = Path(sys.argv[1])
    text = path.read_text(encoding='utf-8')
    for old, new, mode in ((GLOBAL_ANCHOR, GLOBAL_NEW, 'after'), (HELPER_ANCHOR, HELPER, 'before'),
                           (BRANCH_OLD, BRANCH_NEW, 'replace'), (ARG_ANCHOR, ARG_NEW, 'before'), (LOAD_ANCHOR, LOAD_NEW, 'before')):
        assert text.count(old) == 1, (old[:60], text.count(old))
        if mode == 'replace':
            text = text.replace(old, new)
        elif mode == 'after':
            text = text.replace(old, old + new)
        else:
            text = text.replace(old, new + old)
    path.write_text(text, encoding='utf-8')
    print('patched', path)


if __name__ == '__main__':
    main()

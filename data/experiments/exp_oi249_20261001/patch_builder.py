"""OI-249 研究开关：在内存中给建带脚本打补丁，不改 `scripts/build_historical_valuation_bands.py`。
开关缺省全关时与生产逐位相同。

* `--peak-relax volume`（C1）：峰守卫 w > 0 的带，若最新年报营收较两年前年报年复合 ≥ `--peak-relax-rev`（缺省 25%）、
  毛利率升幅 ≤ `--peak-relax-gm`（缺省 5pp），且两年窗口内无外生权益变动、购买法收购年与主体重置（同 OI-206 干净窗口），则 w := 0。
* `--peak-relax volume_noncommodity`（C1b）：同 C1，另须不属商品定价型行业（em2016，见 COMMODITY）。
* `--roic0-basis consistent`（C2）：`roic0' = roic0 × ratio0 ÷ ratio_cyc`（两者均正），终值回报随之。

    from patch_builder import load
    bhv = load()        # 返回已打补丁的模块
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'scripts' / 'build_historical_valuation_bands.py'

# 预登记的商品定价型行业（em2016 前缀）
COMMODITY = ('化石能源-煤炭', '化石能源-石油天然气', '有色金属-基本金属', '有色金属-稀有金属', '有色金属-贵金属', '钢铁-钢铁',
             '建材-水泥', '基础化工-化学原料', '基础化工-化肥农药', '基础化工-合成纤维及树脂', '农林牧渔-畜牧业-养殖',
             '轻工制造-造纸印刷-造纸', '交通运输-港口航运-航运')

HELPERS = '''
_OI249_COMMODITY = None


def _oi249_commodity(code: str) -> bool:
    """OI-249 C1b：em2016 属预登记的商品定价型行业。"""
    global _OI249_COMMODITY
    if _OI249_COMMODITY is None:
        _OI249_COMMODITY = set()
        with (ROOT / "data/reference/a_share_csrc_industry.csv").open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                em = (r.get("em2016") or "").strip()
                if any(em == p or em.startswith(p + "-") for p in OI249_COMMODITY_PREFIXES):
                    _OI249_COMMODITY.add(r["security_code"])
    return code in _OI249_COMMODITY


def _oi249_volume_driven(code, series, latest, history, x_cum, available_at, args) -> bool:
    """OI-249 C1：量驱动（营收两年复合 ≥ 门槛、毛利率升幅 ≤ 门槛、干净窗口），C1b 另除商品定价型。"""
    if latest is None or not str(latest.period).endswith("-12-31"):
        return False
    y = int(latest.period[:4])
    p0, p1, p2 = latest.period, f"{y - 1}-12-31", f"{y - 2}-12-31"
    a, b = series.get(p0), series.get(p2)
    if not a or not b:
        return False
    rev_a, rev_b = _num(a.get("total_operate_income")), _num(b.get("total_operate_income"))
    gm_a, gm_b = _num(a.get("gross_margin")), _num(b.get("gross_margin"))
    if None in (rev_a, rev_b, gm_a, gm_b) or rev_a <= 0 or rev_b <= 0:
        return False
    if (rev_a / rev_b) ** 0.5 - 1 < args.peak_relax_rev or gm_a - gm_b > args.peak_relax_gm:
        return False
    periods = [p2, p1, p0]
    if any(abs((x_cum.get(q) or 0.0) - (x_cum.get(p) or 0.0)) > 1e-6 for p, q in zip(periods, periods[1:])):
        return False
    if any(getattr(h, "annualized_months", 0) for h in history if p2 <= h.period <= p0):
        return False
    reset = entity_reset_for(code, available_at)
    if reset and p2 < reset <= p0:
        return False
    if args.peak_relax == "volume_noncommodity" and _oi249_commodity(code):
        return False
    return True


'''

PATCHES = [
    # 1. 辅助函数（放在建带函数之前）
    ('''def _build_band(code: str, name: str, tier: str, series: dict[str, dict], actions: list[dict],
''', HELPERS + '''def _build_band(code: str, name: str, tier: str, series: dict[str, dict], actions: list[dict],
'''),
    # 2. 量驱动放宽峰守卫（在峰谷坡道混合之前）
    ('''                w_any = max(peak_w, trough_w)
                ratio0 = (1.0 - w_any) * ratio_noncyc + w_any * ratio_cyc
''', '''                if (getattr(args, "peak_relax", "off") != "off" and peak_w > 0
                        and _oi249_volume_driven(code, series, latest, history, x_cum, available_at, args)):
                    peak_w = 0.0
                    band.peak_weight = 0.0
                    nopat_cyclical = False
                    ROIC_STATS["OI-249 量驱动放宽峰守卫"] += 1
                w_any = max(peak_w, trough_w)
                ratio0 = (1.0 - w_any) * ratio_noncyc + w_any * ratio_cyc
'''),
    # 3. 记下定价比率与窗口中位
    ('''            nopat_ps = ratio0 * bps_op
            band.nopat_ps = nopat_ps
''', '''            _oi249_r0, _oi249_rc = ratio0, locals().get("ratio_cyc")
            nopat_ps = ratio0 * bps_op
            band.nopat_ps = nopat_ps
'''),
    # 4. roic0 同口径（终值回报之前）
    ('''            roic_t = min(w + (roe_t - r), roic0)
''', '''            _r0, _rc = locals().get("_oi249_r0"), locals().get("_oi249_rc")
            if getattr(args, "roic0_basis", "median") == "consistent" and roic0 and _r0 and _rc and _r0 > 0 and _rc > 0:
                roic0 = roic0 * _r0 / _rc
                band.roic0 = roic0
                ROIC_STATS["OI-249 roic0 同口径"] += 1
            roic_t = min(w + (roe_t - r), roic0)
'''),
    # 5. 命令行
    ('''    parser.add_argument("--guard-scope", choices=("all", "cyclical_tags"), default="all",
''', '''    parser.add_argument("--peak-relax", choices=("off", "volume", "volume_noncommodity"), default="off",
                        help="研究开关（OI-249）：量驱动的峰守卫放宽（C1），volume_noncommodity 另除商品定价型行业（C1b）")
    parser.add_argument("--peak-relax-rev", type=float, default=0.25, help="研究开关（OI-249）：营收两年年复合门槛")
    parser.add_argument("--peak-relax-gm", type=float, default=5.0, help="研究开关（OI-249）：毛利率两年升幅上限（百分点）")
    parser.add_argument("--roic0-basis", choices=("median", "consistent"), default="median",
                        help="研究开关（OI-249 C2）：consistent = roic0 × ratio0 ÷ 窗口比率中位")
    parser.add_argument("--guard-scope", choices=("all", "cyclical_tags"), default="all",
'''),
]


# 生产建带脚本自 v4.226 起自带 `--peak-relax`（与本补丁 C1／C1b 逐字相同）；已有的块跳过，使本实验可重跑
MARKERS = ('def _oi249_volume_driven', 'OI-249 量驱动放宽峰守卫', '_oi249_r0, _oi249_rc', 'OI-249 roic0 同口径',
           'parser.add_argument("--peak-relax"')


def patched_source() -> str:
    text = SRC.read_text(encoding='utf-8')
    for (old, new), marker in zip(PATCHES, MARKERS):
        if marker in text:
            if marker == 'parser.add_argument("--peak-relax"':
                new = new[new.index('    parser.add_argument("--roic0-basis"'):]      # 只补 C2 的开关
                assert text.count(old) == 1, ('patch anchor not unique', text.count(old), old[:90])
                text = text.replace(old, new)
            continue
        assert text.count(old) == 1, ('patch anchor not unique', text.count(old), old[:90])
        text = text.replace(old, new)
    return text


def load():
    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))
    mod = types.ModuleType('build_historical_valuation_bands')
    mod.__file__ = str(SRC)
    mod.__dict__['OI249_COMMODITY_PREFIXES'] = COMMODITY
    sys.modules['build_historical_valuation_bands'] = mod
    exec(compile(patched_source(), str(SRC), 'exec'), mod.__dict__)
    return mod


if __name__ == '__main__':
    bhv = load()
    sys.argv = [str(SRC)] + sys.argv[1:]
    raise SystemExit(bhv.main())

"""OI-206 研究开关补丁：`--trail-basis per_share_clean` 与 `--trail-cap C`（配 `--roic-trail-weight 1` 使用）。

    python3 patch_bands.py <目标 .py>
"""
import sys
from pathlib import Path

HELPER_ANCHOR = '# ------------------------------------------------------------------ 建带\n@dataclass\nclass Band:'
HELPER = '''def trailing_per_share_cagr(code: str, history: list, series: dict[str, dict], actions: list[dict],
                            x_cum: dict, as_of: str, min_years: int = 3) -> float | None:
    """OI-206 研究开关：窗口内**每股** NOPAT 的年化增速（端点各取两年均值，式同 `roic_inputs.trailing_nopat_cagr`）。

    每股 = 年报 NOPAT ÷ 年报期末股数（`shares_at_period_end`），股数按期间送转折到窗口最新年报的股本基准。
    窗口内有外生权益年（|X_y| ≥ 5% 上年母公司权益，§6.5.1 第 2 条的识别）、购买法收购年（`consolidation_events.csv`，
    `annualized_months > 0`）或主体重置日时返回 None——增速腿不可用，不把增发、收购与主体变化带来的增长外推。"""
    ordered = [y for y in sorted(history, key=lambda x: x.period) if y.nopat is not None]
    if len(ordered) < min_years + 1:
        return None
    periods = [y.period for y in ordered]
    if any(abs((x_cum.get(b) or 0.0) - (x_cum.get(a) or 0.0)) > 1e-6 for a, b in zip(periods, periods[1:])):
        return None
    if any(getattr(y, "annualized_months", 0) for y in ordered):
        return None
    reset = entity_reset_for(code, as_of)
    if reset and periods[0] < reset <= periods[-1]:
        return None
    per_share = []
    for y in ordered:
        shares = shares_at_period_end(series, actions, y.period, y.parent_equity)
        if not shares or shares <= 0:
            return None
        per_share.append(y.nopat / (shares * split_factor(actions, y.period, periods[-1])))
    begin, end = statistics.mean(per_share[:2]), statistics.mean(per_share[-2:])
    span = (int(periods[-1][:4]) + int(periods[-2][:4]) - int(periods[0][:4]) - int(periods[1][:4])) / 2
    if begin <= 0 or end <= 0 or span < min_years - 1:
        return None
    return (end / begin) ** (1 / span) - 1


'''

CAGR_OLD = '''                g_trail = None
                cagr = roic_inputs.trailing_nopat_cagr(history)
'''
CAGR_NEW = '''                g_trail = None
                if getattr(args, "trail_basis", "total") == "per_share_clean":   # OI-206 研究开关
                    cagr = trailing_per_share_cagr(code, history, series, actions, x_cum, available_at)
                else:
                    cagr = roic_inputs.trailing_nopat_cagr(history)
'''
CAP_OLD = '''                    g_trail = cagr * args.roic_trail_weight * (1.0 - band.peak_weight) * damp
'''
CAP_NEW = '''                    g_trail = cagr * args.roic_trail_weight * (1.0 - band.peak_weight) * damp
                    if getattr(args, "trail_cap", 0.0) > 0:
                        g_trail = min(g_trail, args.trail_cap)                  # OI-206：增速腿单独封顶
'''
ARG_ANCHOR = '''    parser.add_argument("--reset-guard", choices=("off", "peak", "both"), default="off",'''
ARG_NEW = '''    parser.add_argument("--trail-basis", choices=("total", "per_share_clean"), default="total",
                        help="研究开关（OI-206）：利润增速腿口径——total=窗口内总额 NOPAT 增速（缺省）；per_share_clean=每股 NOPAT 增速，"
                             "窗口内有外生权益年、购买法收购年或主体重置时不可用。配 --roic-trail-weight 1 使用")
    parser.add_argument("--trail-cap", type=float, default=0.0, metavar="C",
                        help="研究开关（OI-206）：利润增速腿上限（周期守卫与利润回落折减之后），0=不设（缺省）")
'''


def main():
    path = Path(sys.argv[1])
    text = path.read_text(encoding='utf-8')
    for old, new, mode in ((HELPER_ANCHOR, HELPER, 'before'), (CAGR_OLD, CAGR_NEW, 'replace'), (CAP_OLD, CAP_NEW, 'replace'),
                           (ARG_ANCHOR, ARG_NEW, 'before')):
        assert text.count(old) == 1, (old[:60], text.count(old))
        text = text.replace(old, new) if mode == 'replace' else text.replace(old, new + old)
    path.write_text(text, encoding='utf-8')
    print('patched', path)


if __name__ == '__main__':
    main()

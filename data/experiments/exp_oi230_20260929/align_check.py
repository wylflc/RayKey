"""§12.1 买入线对齐容差（preregister.md「买入线」）：各臂面板在册 P/V 上查现行线 1.0034 的原线合格面（在册 11.689%）。
第一步由 DC_K0（口径修正、k 不变）定 L1：超出 0.2pp 重解，否则保留 1.0034；第二步 k 重估属同尺缩放不再对齐，
DC 用 L1，并记 DC 在 L1 下的合格面（重登在册合格面用）。"""
import shlex
import sys

from common import ARMS, EXP, PANEL, REGISTERED_SHARE, ROOT, save
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw
import align_buy_line as align


def main():
    spans = align.load_spans(PANEL)
    args = shlex.split(sw.BASE); line = 1 - float(args[args.index('--width') + 1])
    out, values = {}, {}
    for arm in ('OLD',) + ARMS:
        values[arm] = align.ratios(EXP / 'states' / arm / 'a_share_daily_states_adopted.csv', spans)
        solved, share, old_share, retained = align.resolve_line(values[arm], line, REGISTERED_SHARE, .2)
        out[arm] = dict(line=solved, width=round(1 - solved, 4), share=share, old_line_share=old_share, retained=retained, n=len(values[arm]))
        print(arm, out[arm], flush=True)
    l1 = out['DC_K0']['line']
    dc = values['DC']
    dc_share = sum(v <= l1 for v in dc) / len(dc)
    save('align_check.json', dict(registered_share=REGISTERED_SHARE, current_line=line, arms=out,
                                  l1=l1, l1_width=round(1 - l1, 4), l1_retained=out['DC_K0']['retained'],
                                  dc_share_at_l1=dc_share))
    print('L1', l1, 'retained', out['DC_K0']['retained'], 'DC share at L1', dc_share, flush=True)


if __name__ == '__main__':
    main()

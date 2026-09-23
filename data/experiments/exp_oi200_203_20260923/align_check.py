"""§12.1 买入线对齐容差：各臂面板在册 P/V 上检查原线 1.0454（在册合格面 17.771%），超出 0.2pp 给出重解线与对应 --width。"""
import shlex
import sys

from common import EXP, PANEL, ROOT, save
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw
import align_buy_line as align

REGISTERED_SHARE = 0.17771


def main():
    spans = align.load_spans(PANEL)
    args = shlex.split(sw.BASE); line = 1 - float(args[args.index('--width') + 1])
    out = {}
    for arm in ('OLD', 'CONTROL', 'MID', 'NEW'):
        values = align.ratios(EXP / 'states' / arm / 'a_share_daily_states_adopted.csv', spans)
        solved, share, old_share, retained = align.resolve_line(values, line, REGISTERED_SHARE, .2)
        out[arm] = dict(line=solved, width=round(1 - solved, 4), share=share, old_line_share=old_share, retained=retained, n=len(values))
        print(arm, out[arm], flush=True)
    save('align_check.json', dict(registered_share=REGISTERED_SHARE, current_line=line, arms=out))


if __name__ == '__main__':
    main()

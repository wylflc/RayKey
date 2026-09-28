"""§12.1 第 13 款机会／陷阱读数（估值层 + 14 起点策略层）与第 11 款案例归因：CONTROL 对主候选 TIERS(_ALIGNED)。"""
import subprocess
import sys

from common import EXP, FROZEN_ACTIONS, ROOT, load


def run(args, log):
    with (EXP / log).open('w') as out:
        subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)


def main():
    main_arm = load('verification.json')['main']
    state = main_arm.removesuffix('_ALIGNED')
    align = load('align_check.json')
    line_c = align['current_line']
    line_m = align['arms'][state]['line'] if main_arm.endswith('_ALIGNED') else line_c
    tag = main_arm.replace('_', '')
    run([ROOT / 'scripts/experimental/opportunity_trap_audit.py',
         '--states', f"CONTROL={EXP / 'states/CONTROL_build/a_share_daily_states_adopted.csv'}",
         f"{main_arm}={EXP / 'states' / f'{state}_build' / 'a_share_daily_states_adopted.csv'}",
         '--buy-line', f'CONTROL={line_c}', f'{main_arm}={line_m}',
         '--trades', f"CONTROL={EXP / 'trades' / 'CONTROLfull*_trades.csv'}", f"{main_arm}={EXP / 'trades' / f'{tag}full*_trades.csv'}",
         '--out', EXP / 'opportunity_trap.md'], 'opportunity_trap.log')
    run([ROOT / 'scripts/experimental/case_attribution.py',
         '--base', f"CONTROL={EXP / 'contrib_CONTROLfull20111101_trades.csv'}",
         '--arm', f"{main_arm}={EXP / f'contrib_{tag}full20111101_trades.csv'}",
         '--base-states', EXP / 'states/CONTROL/a_share_daily_states_adopted.csv',
         '--arm-states', EXP / 'states' / state / 'a_share_daily_states_adopted.csv',
         '--actions', FROZEN_ACTIONS, '--out', EXP / 'case_attribution.md'], 'case_attribution.log')


if __name__ == '__main__':
    main()

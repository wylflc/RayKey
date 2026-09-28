"""OI-227 第 13 款估值层（preregister.md 第二步）：答案卷中银行（不含保险）股票月在统一线 1.0495 与各银行线下的
买入区占比、机会捕捉、买入区机会／陷阱占比及相对基准率，按股票整簇自助；非金融在 1.0495 下的同口径读数作参照。

    python3 bank_zone.py      # → bank_zone.json、bank_zone.md
"""
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import bank_valuation  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402

STATES = ROOT / 'data/experiments/exp_land_v4215_20260928/states/H2/a_share_daily_states_adopted.csv'
LINES = (1.0495, 0.946, 0.677, 0.482)


def readout(rows, pv, line):
    eps = sorted({r['episode'] for r in rows if 'episode' in r})
    remap = {e: i for i, e in enumerate(eps)}
    local = [dict(r, episode=remap[r['episode']]) if 'episode' in r else r for r in rows]
    stocks, c = audit.counts(local, pv, line, len(eps))
    point = audit.rates(c)
    draws = audit.bootstrap({'x': c}, len(stocks))
    return {k: dict(point=point.get(k), ci=audit.interval(draws[('x', k)])) for k in point}, len(stocks)


def main():
    rows, _eps = audit.load_answer_key(audit.LABELS)
    banks = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    names = {r['code']: r.get('name', '') for r in rows}
    bank_rows = [r for r in rows if r['code'] in banks]
    nonfin_rows = [r for r in rows if r['code'] not in banks and not is_divspread_financial(r['code'], names.get(r['code'], ''))]
    pv = audit.load_pv(STATES, {(r['code'], r['date']) for r in rows})
    res = dict(bank_rows=len(bank_rows), nonfin_rows=len(nonfin_rows))
    res['nonfin@1.0495'], res['nonfin_stocks'] = readout(nonfin_rows, pv, 1.0495)
    for line in LINES:
        res[f'bank@{line}'], res['bank_stocks'] = readout(bank_rows, pv, line)
    (EXP / 'bank_zone.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    pct = lambda x: '—' if x is None else f'{x * 100:.1f}%'
    out = ['# OI-227 银行买入区读数（第 13 款估值层）', '', f"答案卷银行股票月 {res['bank_rows']}（{res['bank_stocks']} 只）；非金融 {res['nonfin_rows']}（{res['nonfin_stocks']} 只）。区间为按股票整簇自助的 5%～95%。", '',
           '| 口径 | 买入区占比 | 机会捕捉（月） | 机会捕捉（段） | 买入区机会占比 | 买入区陷阱占比 | 机会 ÷ 基准 | 陷阱 ÷ 基准 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in ['nonfin@1.0495'] + [f'bank@{line}' for line in LINES]:
        e = res[key]
        cell = lambda k, f=pct: f"{f(e[k]['point'])} [{f(e[k]['ci'][0])}, {f(e[k]['ci'][1])}]" if k in e else '—'
        ratio = lambda x: '—' if x is None or x != x else f'{x:.2f}'
        out.append(f"| {key} | {cell('zone_share')} | {cell('opp_capture_m')} | {cell('opp_capture_e')} | {cell('zone_opp_share')} | "
                   f"{cell('zone_trap_share')} | {cell('lift_opp', ratio)} | {cell('lift_trap', ratio)} |")
    (EXP / 'bank_zone.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()

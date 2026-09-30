"""重建状态对在册面板子集（OI-230 DC，OI-237 与 v4.222 落地所用）的逐行核对。

在册状态的行情多数止于 08-07、141 只止于 08-28：08-07 及以前须逐行一致；08-08～08-28 两边都有的行
单列（在册那段只有 141 只有行情，H2 截面系数 G 的银行集合不同，银行行可以不同）；08-28 以后为新增行。
估值带（逐报告期）与在册 `data/processed/roic_bands*.csv` 同代码逐行比较。

    python3 validate.py
"""
import collections
import json

from common import DC, EXP, PANEL_STATES, ROOT, STATES, build_codes

CUT_OLD, CUT_141 = '2026-08-07', '2026-08-28'


def rows(path):
    with path.open('rb') as f:
        header = f.readline().decode().rstrip('\r\n').lstrip('﻿').split(',')
        for line in f:
            text = line.decode().rstrip('\r\n')
            code, day = text.split(',', 2)[:2]
            yield code, day, text, header


def compare(name: str) -> dict:
    old, header = {}, None
    for code, day, text, header in rows(DC / name):
        old[(code, day)] = text
    stats = collections.Counter()
    diff_cols, diff_codes, examples = collections.Counter(), collections.Counter(), []
    seen = set()
    for code, day, text, new_header in rows(PANEL_STATES / name):
        assert new_header == header, (name, new_header, header)
        key = (code, day)
        seen.add(key)
        zone = 'le_0807' if day <= CUT_OLD else 'le_0828' if day <= CUT_141 else 'new'
        if key not in old:
            stats[f'{zone}:only_new'] += 1
            continue
        if old[key] == text:
            stats[f'{zone}:equal'] += 1
            continue
        stats[f'{zone}:differ'] += 1
        a, b = old[key].split(','), text.split(',')
        cols = [h for h, x, y in zip(header, a, b) if x != y]
        diff_cols.update(f'{zone}:{c}' for c in cols)
        diff_codes[f'{zone}:{code}'] += 1
        if len(examples) < 12 and zone == 'le_0807':
            examples.append(dict(code=code, date=day, cols={h: [x, y] for h, x, y in zip(header, a, b) if x != y}))
    for key in old.keys() - seen:
        stats[('le_0807' if key[1] <= CUT_OLD else 'le_0828') + ':only_old'] += 1
    return dict(stats=dict(sorted(stats.items())), diff_cols=dict(diff_cols.most_common(20)),
                diff_codes=dict(diff_codes.most_common(20)), examples=examples)


def bands(suffix: str) -> dict:
    codes = set(build_codes())

    def load(path):
        out = collections.Counter()
        with path.open(encoding='utf-8') as f:
            f.readline()
            for line in f:
                if line.split(',', 1)[0] in codes:
                    out[line] += 1
        return out
    old, new = load(ROOT / f'data/processed/roic_bands{suffix}.csv'), load(STATES / f'roic_bands{suffix}.csv')
    changed = sorted({line.split(',', 1)[0] for line in (old - new) + (new - old)})
    return dict(old_rows=sum(old.values()), new_rows=sum(new.values()), only_old=sum((old - new).values()),
                only_new=sum((new - old).values()), codes_changed=changed[:40], n_codes_changed=len(changed))


def main():
    out = dict(states={n: compare(n) for n in ('a_share_daily_states_adopted.csv', 'a_share_daily_states_hold.csv')},
               bands={s or 'base': bands(s) for s in ('', '_b2')})
    (EXP / 'validation.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    for n, r in out['states'].items():
        print(n, r['stats'], flush=True)
    for s, r in out['bands'].items():
        print('bands', s, {k: v for k, v in r.items() if k != 'codes_changed'}, flush=True)


if __name__ == '__main__':
    main()

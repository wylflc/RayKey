"""CONTROL must reproduce the stored states; summarize MID/NEW changes; cut panel subsets for the backtest."""
import csv
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from common import ARMS, EXP, OI202_OUTPUT_COLUMNS, STATE_FILES, digest, load, save

VALUE_FIELDS = ('intrinsic_value', 'valuation_ratio', 'band_low', 'band_high', 'status', 'roic_path')


def groups(path):
    """按代码分组流式读取（文件按代码成块）：产出 (代码, {键: 行文本}, 字段名)。"""
    with path.open(newline='', encoding='utf-8-sig') as f:
        fields = next(csv.reader([f.readline()]))
        kpos = [fields.index(k) for k in (('security_code', 'date') if 'date' in fields else ('security_code', 'report_date', 'available_at'))]
        code, block = None, {}
        for line in f:
            rec = next(csv.reader([line]))
            if rec[0] != code and block:
                yield code, block, fields
                block = {}
            code = rec[0]
            block[tuple(rec[i] for i in kpos)] = line
        if block:
            yield code, block, fields


def compare(name: str, left, right, allowed: set[str]) -> dict:
    """两份文件按代码块同步推进（不要求字典序，只要多数代码同序）；错位的块暂存待配对，同键行文本不同再按字段比。"""
    diff_fields, allowed_fields, codes, value_codes = Counter(), Counter(), Counter(), Counter()
    stats = dict(changed=0, only_allowed=0, total=0)
    only_left, only_right = [], []

    def match(code, la, fa, lb, fb):
        for k in la.keys() | lb.keys():
            stats['total'] += 1
            x, y = la.get(k), lb.get(k)
            if x == y:
                continue
            if x is None or y is None:
                (only_right if x is None else only_left).append(list(k)); codes[code] += 1; continue
            ra = dict(zip(fa, next(csv.reader([x])))); rb = dict(zip(fb, next(csv.reader([y]))))
            d = {f for f in set(ra) | set(rb) if ra.get(f, '') != rb.get(f, '')}
            if not d:
                continue
            stats['changed'] += 1; codes[code] += 1
            if d <= allowed:
                stats['only_allowed'] += 1
            diff_fields.update(d - allowed); allowed_fields.update(d & allowed)
            if d & set(VALUE_FIELDS):
                value_codes[code] += 1

    ga, gb = groups(left), groups(right)
    pend_a, pend_b = {}, {}
    while True:
        a, b = next(ga, None), next(gb, None)
        if a is None and b is None:
            break
        if a is not None and b is not None and a[0] == b[0]:
            match(a[0], a[1], a[2], b[1], b[2]); continue
        if a is not None:
            pend_a[a[0]] = a
        if b is not None:
            pend_b[b[0]] = b
        for code in list(pend_a.keys() & pend_b.keys()):
            x, y = pend_a.pop(code), pend_b.pop(code)
            match(code, x[1], x[2], y[1], y[2])
    for code, blk in pend_a.items():
        only_left += [list(k) for k in blk[1]][:5]; codes[code] += len(blk[1])
    for code, blk in pend_b.items():
        only_right += [list(k) for k in blk[1]][:5]; codes[code] += len(blk[1])
    return dict(file=name, rows=stats['total'], changed_rows=stats['changed'], only_allowed_rows=stats['only_allowed'],
                changed_fields=dict(diff_fields.most_common()), allowed_fields=dict(allowed_fields),
                changed_codes=len(codes), value_changed_codes=dict(value_codes.most_common()),
                only_in_left=len(only_left), only_in_right=len(only_right),
                unmatched_left_codes=sorted(pend_a), unmatched_right_codes=sorted(pend_b),
                sample_only_left=only_left[:20], sample_only_right=only_right[:20])


def job(args):
    arm, name = args
    left = EXP / 'old_inputs/data/processed' / name if arm == 'CONTROL' else EXP / 'states/CONTROL_build' / name
    allowed = OI202_OUTPUT_COLUMNS if arm == 'CONTROL' else set()
    result = compare(name, left, EXP / 'states' / f'{arm}_build' / name, allowed)
    result['arm'] = arm
    return result


def cut(arm: str, name: str, panel: set[str]) -> dict:
    src = EXP / 'states' / f'{arm}_build' / name
    dst = EXP / 'states' / arm / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with src.open('rb') as f, dst.open('wb') as out:
        out.write(f.readline())
        for line in f:
            if line.split(b',', 1)[0].decode().lstrip('﻿') in panel:
                out.write(line); kept += 1
    return dict(rows=kept, digest=digest(dst))


def main():
    jobs = [(arm, name) for arm in ARMS for name in STATE_FILES]
    with ProcessPoolExecutor(max_workers=min(len(jobs), 24)) as pool:
        results = list(pool.map(job, jobs))
    by_arm = defaultdict(dict)
    for r in results:
        by_arm[r['arm']][r['file']] = r
        print(r['arm'], r['file'], 'changed', r['changed_rows'], 'fields', list(r['changed_fields'])[:8],
              'only_allowed', r['only_allowed_rows'], flush=True)
    save('control_validation.json', by_arm['CONTROL'])
    save('arm_changes.json', {a: by_arm[a] for a in ('MID', 'NEW')})
    panel = set(load('before_manifest.json')['panel_codes'])
    subsets = {arm: {n: cut(arm, n, panel) for n in ('a_share_daily_states_adopted.csv', 'a_share_daily_states_hold.csv',
                                                     'roic_bands.csv')} for arm in ARMS}
    save('panel_subsets.json', subsets)


if __name__ == '__main__':
    main()

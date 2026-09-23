"""落地臂（EFL）对回测臂（EF）：逐日与状态文件逐字节相同，带文件只许 §6.5.3 输出列不同（用户 2026-09-24 裁定重定义）。

终值占比改按第 n1 + n 年分界后，显式期与终值两段的求和次序变了，V 在末位有 1e-16 量级的浮点差：四位小数的 V 与全部逐日文件
不变，只有 TTM EPS ≈ 0 的行 `pe_on_ttm_eps`（量级 1e17）露出差异。该列按相对差 < 1e-12 逐行核验并记录。"""
import csv
import os
from concurrent.futures import ProcessPoolExecutor

from common import EXP, OUTPUT_COLUMNS, STATE_FILES, digest, load, save
from verify import compare

ARM, TESTED = 'EFL', 'EF'
FLOAT_NOISE = {'pe_on_ttm_eps'}


def noise_rows(name):
    """逐行对齐（同一代码同序输出），核验 FLOAT_NOISE 列的差只是末位浮点差。"""
    rows = []
    with (EXP / 'states' / f'{TESTED}_build' / name).open() as fa, (EXP / 'states' / f'{ARM}_build' / name).open() as fb:
        for a, b in zip(csv.DictReader(fa), csv.DictReader(fb)):
            key = (a['security_code'], a['report_date'], a['available_at'])
            assert key == (b['security_code'], b['report_date'], b['available_at']), key
            for col in FLOAT_NOISE:
                if a[col] != b[col]:
                    x, y = float(a[col]), float(b[col])
                    rows.append(dict(key=list(key), column=col, tested=a[col], landed=b[col], rel=abs(x - y) / max(abs(x), abs(y))))
    return rows


def job(name):
    left, right = EXP / 'states' / f'{TESTED}_build' / name, EXP / 'states' / f'{ARM}_build' / name
    if name.startswith('roic_bands'):
        result = compare(name, left, right, OUTPUT_COLUMNS | FLOAT_NOISE)
        result['float_noise_rows'] = noise_rows(name)
        return result
    return dict(file=name, identical=digest(left) == digest(right))


def main():
    with ProcessPoolExecutor(max_workers=len(STATE_FILES)) as pool:
        results = dict(zip(STATE_FILES, pool.map(job, STATE_FILES)))
    ok = True
    for name, r in results.items():
        if 'identical' in r:
            ok &= r['identical']
        else:
            ok &= not (r['changed_fields'] or r['unmatched_left_codes'] or r['unmatched_right_codes']
                       or r['only_in_left'] or r['only_in_right'])
            ok &= all(x['rel'] < 1e-12 for x in r['float_noise_rows'])
        print(name, {k: v for k, v in r.items() if k in ('identical', 'changed_rows', 'only_allowed_rows', 'changed_fields', 'allowed_fields')},
              'float_noise', len(r.get('float_noise_rows', [])), max((x['rel'] for x in r.get('float_noise_rows', [])), default=0), flush=True)
    save('land_verify.json', {'arm': ARM, 'tested_arm': TESTED, 'pass': ok, 'files': results, 'job_id': os.getenv('SLURM_JOB_ID')})
    assert ok, 'EFL differs from EF beyond output columns'


if __name__ == '__main__':
    main()

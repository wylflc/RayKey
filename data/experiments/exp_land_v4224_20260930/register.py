"""按裁定臂 K1 重登 BASE 全样本与剔除集 A 共 28 条汇总（估值输入变动；OI-227／OI-230 先例，§12.279、§12.282）。

v4.222 改 BASE 开关后台账未登记新 BASE，本批同时补上：新登记键的 `策略` 名带 v4.222 开关，旧键保留不删。

    python3 register.py    # → data/backtest/summary_BASE*.csv、scan_summaries.csv、registration.json
"""
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
import clean_derived_artifacts as ledger  # noqa: E402
from run import A_SET  # noqa: E402


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    ruling = json.loads((EXP / 'user_ruling.json').read_text())
    arm = ruling['registered_arm']
    rows = [r for r in read(EXP / 'summary_rows.csv') if r['arm'] == arm and r['group'] in ('full', 'A')]
    assert len(rows) == 28 and all(r['负现金日数'] == '0' and r['计量版本'] == sw.METRIC_VERSION for r in rows)
    key = lambda r: (r['扫描标签'], r['策略'], r['计量版本'])
    before = {key(r): r for r in read(ledger.MERGED)}
    committed_csv = subprocess.check_output(['git', 'show', 'HEAD:data/backtest/scan_summaries.csv'], cwd=ROOT, text=True)
    committed = {key(r): r for r in csv.DictReader(io.StringIO(committed_csv))}
    paths, published, touched = [], [], set()
    for r in rows:
        tag = sw.summary_tag('BASE', r['start'], ','.join(A_SET) if r['group'] == 'A' else '')
        clean = {k: x for k, x in r.items() if k not in ('group', 'arm', 'start', 'tag')}
        suffix = '_' + r['tag']
        assert clean['策略'].endswith(suffix)
        clean['策略'] = clean['策略'][:-len(suffix)] + '_' + tag
        target = sw.OUT_DIR / f'summary_{tag}.csv'
        old = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        tmp = target.with_name('.' + target.name + '.v4224')
        with tmp.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(clean)); w.writeheader(); w.writerow(clean)
        tmp.replace(target); paths.append(target); touched.add((tag, clean['策略'], clean['计量版本']))
        published.append(dict(path=str(target.relative_to(ROOT)), before_sha256=old, after_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    names = {p.name for p in paths}
    import os
    with os.scandir(sw.OUT_DIR) as it:
        entries = [e for e in it if e.name in names]
    ledger.write_ledger(entries)
    after = {key(r): r for r in read(ledger.MERGED)}
    assert before.keys() <= after.keys(), '旧键不得删除'
    assert touched <= after.keys() and len(touched) == 28
    untouched = {k: r for k, r in committed.items() if k not in touched}
    assert untouched.keys() <= after.keys() and all(after[k] == r for k, r in untouched.items()), '本批之外的已登记行不得改写'
    overwritten = sum(1 for k in touched if k in committed)
    (EXP / 'registration.json').write_text(json.dumps(dict(registered_base_rows=28, overwritten_keys=overwritten, new_keys=len(after) - len(before),
        input_epoch='v4224_20260930', precedent='OI-230 §12.282 重登（v4.221）', arm=arm, A=A_SET, run_job='27400107',
        entry_point='clean_derived_artifacts.write_ledger', published=published), ensure_ascii=False, indent=2) + '\n')
    print(f'REGISTERED 28 BASE summaries (overwritten {overwritten}, new keys {len(after) - len(before)}); other ledger rows preserved.')


if __name__ == '__main__':
    main()

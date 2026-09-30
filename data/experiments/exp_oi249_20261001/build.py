"""OI-249 建带：同一建带脚本（本目录 patch_builder.py）按五臂并行重建样本代码与个案代码的带。

臂：ctrl（开关全关，复现生产）、c1（量驱动放宽）、c1b（另除商品定价型）、c2（roic0 同口径）、c12（c1 + c2）。
代码：OI-245 第一段口径的面板在册、3 年回报可得的代码，加个案代码（preregister.md 读数第 5 条）。

    python3 build.py      # → bands_<臂>.csv、build.json
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP.parent / 'exp_oi245_20260930'))
import observations as obs1  # noqa: E402

PROD_FLAGS = ('--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 '
              '--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded '
              '--roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0 '
              '--minority-basis earnings --wc-aggregation operating --cash-caliber nonop --equity-anchor guarded '
              '--restricted-cash notes_wc --wacc-weights unlevered --reset-guard both --rd-capitalize on '
              '--fade-shape exponential --fade-lambda 0.12 --fade-horizon 50 --roic-ic-floor 0.1').split()   # §6.7 第 2 步
VARIANTS = {'ctrl': [], 'c1': ['--peak-relax', 'volume'], 'c1b': ['--peak-relax', 'volume_noncommodity'],
            'c2': ['--roic0-basis', 'consistent'], 'c12': ['--peak-relax', 'volume', '--roic0-basis', 'consistent']}
CASES = {'300308': '中际旭创', '300502': '新易盛', '300394': '天孚通信', '002371': '北方华创', '300274': '阳光电源', '300750': '宁德时代',
         '002714': '牧原股份', '002466': '天齐锂业', '002460': '赣锋锂业', '000792': '盐湖股份', '601088': '中国神华', '002128': '电投能源',
         '600438': '通威股份'}


def codes():
    nonfin = obs1.load_nonfin()
    sample = {c for (c, _m), (panel, _pv, f3, _f5) in nonfin.items() if panel and f3 is not None}
    return sorted(sample), sorted(sample | set(CASES))


def main():
    sample, allc = codes()
    procs, t0 = {}, time.time()
    for name, extra in VARIANTS.items():
        env = dict(os.environ, RK_STMT_GAP_LOG=str(EXP / f'.gaps_{name}.csv'))
        log = (EXP / f'.build_{name}.log').open('w')
        procs[name] = (subprocess.Popen([sys.executable, str(EXP / 'patch_builder.py'), '--codes', ','.join(allc), *PROD_FLAGS, *extra,
                                         '--out-bands', str(EXP / f'bands_{name}.csv'), '--out-daily', str(EXP / f'.daily_{name}.csv')],
                                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env), log)
    rc = {}
    for name, (p, log) in procs.items():
        rc[name] = p.wait()
        log.close()
    for name in VARIANTS:
        for tmp in (EXP / f'.daily_{name}.csv', EXP / f'.gaps_{name}.csv'):
            tmp.unlink(missing_ok=True)
    stats = {}
    for name in VARIANTS:
        text = (EXP / f'.build_{name}.log').read_text(encoding='utf-8', errors='replace')
        stats[name] = [line.strip() for line in text.splitlines() if 'OI-249' in line][:3]
    out = dict(sample_codes=len(sample), built_codes=len(allc), returncodes=rc, seconds=round(time.time() - t0), stats=stats)
    (EXP / 'build.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    assert all(v == 0 for v in rc.values()), rc


if __name__ == '__main__':
    main()

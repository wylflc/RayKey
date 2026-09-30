"""build.py 的 K1 对正式比对更正后重跑（首跑 P/V 比例方向写反），只改写 build_check.json 的 k1_vs_current 统计。

    python3 recheck.py
"""
import json
from build import EXP, FILES, compare_k1

check = json.loads((EXP / 'build_check.json').read_text())
for name in FILES:
    sha = check['k1_vs_current'][name].get('sha256')
    check['k1_vs_current'][name] = dict(compare_k1(name), sha256=sha)
    print(name, check['k1_vs_current'][name], flush=True)
check['note'] = '首跑 bank_ratio_bad 为比对脚本 P/V 方向写反所致，已更正重跑'
(EXP / 'build_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')

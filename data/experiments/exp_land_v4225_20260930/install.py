"""v4.225 安装：NEW 三侧逐日状态替换正式状态（先验：OLD 逐字节复现正式状态；NEW 去掉保险行后与正式逐字节相同、保险行不减少（`verify_new.json`）；落地口径重算的预登记主读数 c_保险 区间含 0；正式状态仍为冻结版本）。
旧口径状态即 states/OLD（与安装前正式状态逐字节相同），保留作复现。

    python3 install.py     # → publication.json
"""
import hashlib
import json
import os
import shutil

from build import EXP, FILES, PROC, digest


def main():
    check = json.loads((EXP / 'build_check.json').read_text())
    verify = json.loads((EXP / 'verify_new.json').read_text())
    main_label = next(iter(verify['landed']['same_ruler']))
    lo, hi = verify['landed']['same_ruler'][main_label]['I1c_landed']['c_ins_ci']
    assert lo <= 0 <= hi, ('落地口径未过预登记判据', lo, hi)
    for name in FILES:
        rep, new, side = check['reproduction'][name], check['new_vs_current'][name], verify['sides'][name]
        assert rep['identical'], name
        assert side['non_insurer_identical'] and side['insurer_removed'] == 0 and side['insurer_changed'] > 0, (name, side)
        assert digest(PROC / name) == rep['current'], (name, '正式状态已不是冻结版本')
        assert digest(EXP / 'states/NEW' / name) == new['sha256'], name
    installed = {}
    for name in FILES:
        target = PROC / name
        tmp = target.with_name('.' + name + '.v4225')
        shutil.copyfile(EXP / 'states/NEW' / name, tmp)
        os.replace(tmp, target)
        installed[name] = dict(before=check['reproduction'][name]['current'], after=digest(target))
        assert installed[name]['after'] == check['new_vs_current'][name]['sha256'], name
        print('INSTALLED', name, flush=True)
    ruling = json.loads((EXP / 'user_ruling.json').read_text())
    (EXP / 'publication.json').write_text(json.dumps(dict(arm='NEW', insurer_method='V_DDM × 前 36 个自然月末银行 G 中位（I1c）',
        buy_line=ruling['buy_line'], registered_share_pct=ruling['registered_share_pct'], previous_registered_share_pct=16.916,
        installed=installed, old_states='states/OLD（与安装前正式状态逐字节相同）'), ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()

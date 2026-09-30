"""v4.224 安装：K1 三侧逐日状态替换正式状态（先验：K7045 逐字节复现正式状态、K1 只改银行行且比例正确、正式状态仍为冻结版本）。
旧口径状态即 states/K7045（与安装前正式状态逐字节相同），保留作复现。

    python3 install.py     # → publication.json
"""
import hashlib
import json
import os
import shutil

from build import EXP, FILES, PROC, digest


def main():
    check = json.loads((EXP / 'build_check.json').read_text())
    for name in FILES:
        rep, k1 = check['reproduction'][name], check['k1_vs_current'][name]
        assert rep['identical'], name
        assert k1['bank_ratio_bad'] == 0 and k1['other_changed'] == 0 and k1['insurer_changed'] == 0 and k1['bank_changed'] > 0, (name, k1)
        assert digest(PROC / name) == rep['current'], (name, '正式状态已不是冻结版本')
        assert digest(EXP / 'states/K1' / name) == k1['sha256'], name
    installed = {}
    for name in FILES:
        target = PROC / name
        tmp = target.with_name('.' + name + '.v4224')
        shutil.copyfile(EXP / 'states/K1' / name, tmp)
        os.replace(tmp, target)
        installed[name] = dict(before=check['reproduction'][name]['current'], after=digest(target))
        assert installed[name]['after'] == check['k1_vs_current'][name]['sha256'], name
        print('INSTALLED', name, flush=True)
    (EXP / 'publication.json').write_text(json.dumps(dict(arm='K1', bank_scale=1.0, buy_line=1.0034, registered_share_pct=16.916,
        previous_registered_share_pct=11.761, alignment_exception='§12.1 同尺缩放不做对齐', installed=installed,
        old_states='states/K7045（与安装前正式状态逐字节相同）'), ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()

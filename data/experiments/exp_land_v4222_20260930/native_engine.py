"""原生引擎（不打任何补丁）按冻结的 v4.221 公司行动运行，供 reproduce.py 调用。"""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt  # noqa: E402

if __name__ == '__main__':
    bt.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
    assert bt.ACTIONS.exists(), bt.ACTIONS
    raise SystemExit(bt.main())

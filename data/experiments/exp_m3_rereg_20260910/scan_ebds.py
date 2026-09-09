"""三臂扫描：与 §12.220 同一候选实现（high_base_engine.py：低性价比去融资、其余完整恢复 BASE），私有落点，不进台账。"""
import inspect
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw

if __name__ == '__main__':
    i = sys.argv.index('--cache-dir'); cache = Path(sys.argv[i + 1]); del sys.argv[i:i + 2]
    cache.mkdir(parents=True, exist_ok=True)
    sw.OUT_DIR = cache; sw.RUN_DIR = cache / 'private'
    sw.BASE += f' --equity-bond-log-dir {cache.parent.parent / "daily" / cache.name}'
    original = inspect.getsource(sw.run_one)
    target = 'str(ROOT / "scripts/backtest_valuation_strategy.py")'
    replacement = 'str(ROOT / "data/experiments/exp_equity_bond_20260909/high_base_engine.py")'
    assert original.count(target) == 1
    exec(compile(original.replace(target, replacement), __file__, 'exec'), sw.__dict__)
    sw.main()

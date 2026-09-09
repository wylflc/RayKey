"""OI-171 EBDS03 第 4 款批次的统一启动器：所有回测走 §12.220 的股债包装引擎（high_base_engine.py：低性价比去融资、其余完整恢复
BASE），summary 落私有目录、不进台账（--cache-dir）。
用法：python3 launch.py --cache-dir <dir> --sweep <sweep_backtest_configs 参数...>     → 扫描（含去赢家第二遍）
      python3 launch.py --cache-dir <dir> <脚本路径> <脚本参数...>                   → 以 __main__ 运行 ex_winner_dose.py 等
"""
import inspect
import runpy
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw  # noqa: E402


def patch(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    sw.OUT_DIR = cache
    sw.RUN_DIR = cache / 'private'
    sw.BASE += f' --equity-bond-log-dir {EXP / "daily" / cache.name}'
    src = inspect.getsource(sw.run_one)
    target = 'str(ROOT / "scripts/backtest_valuation_strategy.py")'
    assert src.count(target) == 1, 'run_one 的引擎路径写法变了，先对齐 launch.py'
    exec(compile(src.replace(target, 'str(ROOT / "data/experiments/exp_equity_bond_20260909/high_base_engine.py")'),
                 str(EXP / 'launch.py'), 'exec'), sw.__dict__)


if __name__ == '__main__':
    i = sys.argv.index('--cache-dir')
    cache = Path(sys.argv[i + 1]).resolve()
    del sys.argv[i:i + 2]
    patch(cache)
    if sys.argv[1] == '--sweep':
        sys.argv = [str(ROOT / 'scripts/sweep_backtest_configs.py')] + sys.argv[2:]
        sw.main()
    else:
        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name='__main__')

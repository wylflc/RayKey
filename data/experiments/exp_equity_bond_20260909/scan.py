"""Formal scanner with isolated summary files."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sw

if __name__ == "__main__":
    i = sys.argv.index("--cache-dir")
    cache = Path(sys.argv[i+1]); del sys.argv[i:i+2]
    cache.mkdir(parents=True, exist_ok=True)
    sw.OUT_DIR = cache; sw.RUN_DIR = cache / "private"
    sw.BASE += f' --equity-bond-log-dir {cache.parent.parent / "daily" / cache.name}'
    sw.main()

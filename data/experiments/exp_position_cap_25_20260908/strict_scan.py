"""Use the formal scanner and BASE, routing only engine execution to the local guard."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sw

original_run = subprocess.run


def routed_run(command, *args, **kwargs):
    if isinstance(command, list) and len(command) > 1 and command[1] == str(ROOT / "scripts/backtest_valuation_strategy.py"):
        command = list(command)
        command[1] = str(Path(__file__).with_name("strict_cap_engine.py"))
    return original_run(command, *args, **kwargs)


if __name__ == "__main__":
    sw.subprocess.run = routed_run
    sw.main()

"""Experiment-only guard for the one-lot fallback bypassing position-cap room."""
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_valuation_strategy as bt

if "--cap-lot-guard" in sys.argv:
    sys.argv.remove("--cap-lot-guard")
    source = inspect.getsource(bt.run)
    before = """                if lots_n <= 0:
                    # 高价股"""
    after = """                if lots_n <= 0:
                    if position_cap and bp * lot_size > room + 1e-8:
                        stats["单股上限·余量不足一手"] += 1
                        continue
                    # 高价股"""
    assert source.count(before) == 1, "Engine source changed; review guard insertion"
    exec(compile(source.replace(before, after), __file__, "exec"), bt.__dict__)
    guarded_run = bt.run

    def run_with_diagnostics(*args, **kwargs):
        result = guarded_run(*args, **kwargs)
        label = sys.argv[sys.argv.index("--label-suffix") + 1]
        directory = Path(__file__).resolve().parent / "strict_guard_events"
        directory.mkdir(exist_ok=True)
        (directory / f"{label}.json").write_text(json.dumps({
            "label": label, "guarded_buy_opportunities": result["stats"].get("单股上限·余量不足一手", 0),
            "position_cap": kwargs.get("position_cap"), "stats": result["stats"],
        }, ensure_ascii=False, indent=2) + "\n")
        return result

    bt.run = run_with_diagnostics

if __name__ == "__main__":
    bt.main()

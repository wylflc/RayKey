"""Merge only this experiment's rows through the repository ledger writer."""
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clean_derived_artifacts import write_ledger
from sweep_backtest_configs import summary_tag


def main():
    with (EXP / "summary_rows.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    with tempfile.TemporaryDirectory(prefix="raykey_cap25_ledger_") as directory:
        for source in rows:
            row = dict(source)
            group, arm, start = (row.pop(key) for key in ("group", "arm", "start"))
            excluded = group.endswith("A") or group.endswith("U")
            if group.endswith("U"):
                challenger = "PC25SSEP08" if group.startswith("strict_") else "PC25SEP08"
                arm = f"U@{challenger}{arm}"
            tag = summary_tag(arm, start, "fixed" if excluded else "")
            path = Path(directory) / f"summary_{tag}.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
        with os.scandir(directory) as entries:
            result = write_ledger(list(entries), apply=True)
    # Fixed-U scans use ordinary labels; restore the ordinary A cache so future
    # baseline consumers do not mistake a six-name U exclusion for the A set.
    for group in ("full", "A", "strict_full", "strict_A"):
        for path in (EXP / "summaries" / group).glob("summary_*.csv"):
            shutil.copyfile(path, ROOT / "data/backtest" / path.name)
    info = {"current_rows_merged": result.current_added, "archive_rows_merged": result.archive_added,
            "arm_names_after": len(result.arms), "ordinary_A_summary_cache_restored": True}
    (EXP / "ledger_update.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info))


if __name__ == "__main__":
    main()

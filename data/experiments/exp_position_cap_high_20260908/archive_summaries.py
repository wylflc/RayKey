"""Merge only this experiment through the canonical ledger writer."""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from clean_derived_artifacts import write_ledger
from sweep_backtest_configs import summary_tag


def main():
    verification = json.loads((EXP / "verification.json").read_text())
    assert verification["inputs_unchanged"] and verification["ordinary_A_summary_cache_restored"]
    with (EXP / "summary_rows.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    with tempfile.TemporaryDirectory(prefix="raykey_caphigh_ledger_") as directory:
        for source in rows:
            row = dict(source)
            group, arm, start = (row.pop(key) for key in ("group","arm","start"))
            excluded = group != "full"
            if group.startswith("U"):
                arm = f"{group}@HIGHSEP08{arm}"
            path = Path(directory) / f"summary_{summary_tag(arm,start,'fixed' if excluded else '')}.csv"
            with path.open("w",newline="") as handle:
                writer = csv.DictWriter(handle,fieldnames=list(row),lineterminator="\n")
                writer.writeheader()
                writer.writerow(row)
        with os.scandir(directory) as entries:
            result = write_ledger(list(entries),apply=True)
    info = {"current_rows_merged":result.current_added,"archive_rows_merged":result.archive_added,
            "arm_names_after":len(result.arms),"union_labels_scoped_to_experiment":True}
    (EXP / "ledger_update.json").write_text(json.dumps(info,indent=2)+"\n")
    print(json.dumps(info))


if __name__ == "__main__":
    main()

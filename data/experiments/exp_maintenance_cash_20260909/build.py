"""Build isolated cash-model arms and prove default-off state equivalence."""
import bisect
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import sweep_backtest_configs as sw
from align_buy_line import load_spans, ratios
from roic_anchor_check import ANCHORS

WEIGHTS = {"BASE": 0, "WCREP": 0, "MC050": .5, "MC100": 1., "MC150": 1.5}


def save(name, obj):
    (EXP / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+"\n")


def fingerprint(paths):
    result = {}
    for p in sorted(paths):
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024), b""):
                h.update(chunk)
        result[str(p.relative_to(ROOT))] = {"bytes":p.stat().st_size,"sha256":h.hexdigest()}
    return result


def run(cmd, log, env=None):
    print(datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"), shlex.join(cmd), flush=True)
    with log.open("w") as f:
        subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                       env={**os.environ, **(env or {})}, check=True)


def canonical_digest(path, codes):
    h, n = hashlib.sha256(), 0
    with path.open(newline="") as f:
        reader=csv.reader(f); header=next(reader); i=header.index("security_code")
        h.update((",".join(header)+"\n").encode())
        for row in reader:
            if codes is None or row[i] in codes:
                h.update((",".join(row)+"\n").encode()); n+=1
    return {"sha256":h.hexdigest(),"rows":n}


def main():
    args=shlex.split(sw.BASE)
    base_paths={option:ROOT/args[args.index(option)+1]
                for option in ("--daily-states","--hold-states","--universe-file")}
    panel=base_paths["--universe-file"]
    with panel.open() as f:
        panel_codes={r["security_code"] for r in csv.DictReader(f)}
    with (ROOT/"data/processed/a_share_pool_model_bands_adopted.csv").open() as f:
        pool_codes={r["security_code"] for r in csv.DictReader(f)}
    codes=panel_codes | pool_codes | {a[0] for a in ANCHORS}
    code_file=EXP/"codes.txt";code_file.write_text("\n".join(sorted(codes))+"\n")
    ends=Counter(); sources=set(base_paths.values())
    for code in sorted(codes):
        p=ROOT/f"data/raw/ohlcv/{code}.csv"
        if not p.exists():
            if code in panel_codes: raise RuntimeError(f"Missing panel price: {p}")
            continue
        sources.add(p)
        if code in panel_codes:
            with p.open("rb") as f:
                header=f.readline().decode("utf-8-sig").strip().split(",")
                f.seek(0,2);size=f.tell();f.seek(max(0,size-4096))
                row=next(csv.reader(f.read().decode().splitlines()[-1:]))
            ends[row[header.index("date")]]+=1
    for directory in ("data/raw/financials", "data/raw/financials_statements"):
        sources.update((ROOT/directory).rglob("*.csv"))
    for name in ("data/raw/ohlcv/INDEX_000001.csv", "data/raw/corporate_actions/a_share_corporate_actions.csv",
                 "data/raw/a_share_delisted_roster.csv", "data/raw/a_share_securities.csv",
                 "data/reference/cost_of_equity_inputs.csv", "data/reference/consolidation_events.csv",
                 "data/processed/entity_reset_dates.csv", "data/interim/statement_restatements.csv",
                 "data/processed/a_share_pool_model_bands_adopted.csv",
                 "scripts/intrinsic_value.py", "scripts/roic_inputs.py", "scripts/build_historical_valuation_bands.py",
                 "scripts/backtest_valuation_strategy.py", "scripts/sweep_backtest_configs.py",
                 "scripts/rebuild_bank_bands.py", "scripts/build_hold_daily_states.py",
                 "docs/000_Ashare_workflow.md"):
        p=ROOT/name
        if p.exists(): sources.add(p)
    sources|={EXP/"build.py",EXP/"preregister.md",code_file}
    before=fingerprint(sources)
    doc=(ROOT/"docs/000_Ashare_workflow.md").read_text()
    match=re.search(r"# 2\. 构建 ROIC 带与逐日状态\n(.*?)\s+--out-bands",doc,re.S)
    common=[t for t in match.group(1).split() if t!="\\"]
    assert common[:2]==["python3","scripts/build_historical_valuation_bands.py"]
    common.remove("--all")
    common[0]=sys.executable
    common += ["--codes-file",str(code_file)]
    divspread=re.search(r"rebuild_bank_bands\.py (divspread:[0-9.]+)",doc).group(1)
    save("manifest.json", {"started_beijing":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "job_id":os.environ.get("SLURM_JOB_ID"),"base":sw.BASE,"starts":sw.DEFAULT_STARTS,
        "metric":sw.METRIC_VERSION,"panel_codes":len(panel_codes),"build_codes":len(codes),
        "price_ends":dict(sorted(ends.items())),"inputs":before,"build_command":common,
        "weights":WEIGHTS,"candidate_combinations":10,
        "single_company_sample_seconds":{"off":6.54,"weight1":3.69}})
    prior=[]; alignment={}; config=[]
    base_line=1-float(args[args.index("--width")+1])
    for tag,weight in WEIGHTS.items():
        directory=EXP/"val"/tag;directory.mkdir(parents=True,exist_ok=True)
        for side in ("base","b2"):
            band=directory/f"roic_bands_{side}.csv"
            raw=directory/f"roic_raw_{side}.csv"
            command=common+["--maintenance-weight",str(weight),"--out-bands",str(band),"--out-daily",str(raw)]
            if tag!="BASE":command += ["--wc-aggregation","reported"]
            if side=="b2":command += ["--ttm-trust","on","--ttm-trust-delta","0.02"]
            run(command,directory/f"build_{side}.log",{"RK_STMT_GAP_LOG":str(directory/f"gaps_{side}.csv")})
            run([sys.executable,"scripts/rebuild_bank_bands.py",divspread,
                 str(directory/f"states_{side}.csv"),str(raw),str(band)],directory/f"bank_{side}.log")
            raw.unlink()
        run([sys.executable,"scripts/build_hold_daily_states.py","--base",str(directory/"states_base.csv"),
             "--b2",str(directory/"states_b2.csv"),"--out",str(directory/"states_hold.csv")],directory/"merge.log")
        if tag=="BASE":
            for side,option in [("base","--daily-states"),("hold","--hold-states")]:
                a=canonical_digest(directory/f"states_{side}.csv",None)
                b=canonical_digest(base_paths[option],codes)
                prior.append({"side":side,"rebuilt":a,"production_subset":b,"equal":a==b})
                save("baseline_equivalence.json",prior)
                if a!=b:raise RuntimeError(f"BASE subset mismatch: {side}; see baseline_equivalence.json")
        values=ratios(directory/"states_base.csv",load_spans(panel))
        if tag=="BASE":
            base_share=bisect.bisect_right(values,base_line)/len(values)
            line=base_line
        else:
            line=round(values[min(int(base_share*len(values)),len(values)-1)],4)
        alignment[tag]={"observations":len(values),"buy_line":line,
                        "old_line_share":bisect.bisect_right(values,base_line)/len(values),
                        "aligned_share":bisect.bisect_right(values,line)/len(values)}
        states=f"--daily-states {directory.relative_to(ROOT)}/states_base.csv --hold-states {directory.relative_to(ROOT)}/states_hold.csv"
        if tag=="BASE":config.append(f"BASE|{states}")
        elif tag=="WCREP":config.append(f"WCREPSEP09|{states} --width {1-line:.4f} --swap-margin 0.15")
        else:
            for margin in (.14,.15,.16):
                label=f"{tag}M{round(margin*100):02}SEP09"
                config.append(f"{label}|{states} --width {1-line:.4f} --swap-margin {margin:.2f}")
        save("alignment.json",alignment)
        run([sys.executable,"scripts/experimental/roic_anchor_check.py","--bands",
             str(directory/"roic_bands_base.csv"),"--tag",tag],EXP/f"anchors_{tag}.txt")
    (EXP/"configs.txt").write_text("\n".join(config)+"\n")
    unchanged=fingerprint(sources)==before
    save("build_verification.json",{"inputs_unchanged":unchanged,"baseline_equivalence":prior,
                                    "completed_beijing":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()})
    assert unchanged,"Source inputs changed during rebuild"
    print("BUILD COMPLETE",flush=True)


if __name__=="__main__":main()

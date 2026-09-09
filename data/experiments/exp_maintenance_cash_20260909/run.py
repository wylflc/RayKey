"""Run the registered nine combinations, full/A/U, without global cache writes."""
import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(EXP))
from build import fingerprint, save
sys.path.insert(0,str(ROOT/"scripts"))
import sweep_backtest_configs as sw


def scan(config,group,workers,exclude=None):
    command=[sys.executable,str(EXP/"scan.py"),str(EXP/config),
             "--cache-dir",str(EXP/"summaries"/group),"--out",str(EXP/f"sweep_{group}.txt"),
             "--workers",str(workers),"--title","持续现金占用代理：强度与换仓边际配对检验"]
    if exclude:command += ["--exclude-codes",",".join(exclude)]
    with (EXP/f"report_{group}.txt").open("w") as f:
        subprocess.run(command,stdout=f,cwd=ROOT,check=True)
    lines=[s for s in (EXP/f"sweep_{group}.txt").read_text().splitlines() if s and not s.startswith("#")]
    assert all(not s.endswith(("|ERR","|EMPTY")) for s in lines),f"Failed paths: {group}"
    report=EXP/f"report_{group}.txt"
    report.write_text("\n".join(s.rstrip() for s in report.read_text().splitlines())+"\n")
    return len(lines)


def summaries(labels,cache,excluded=False):
    out={}
    for label in labels:
        out[label]={}
        for start in sw.DEFAULT_STARTS:
            p=EXP/"summaries"/cache/f"summary_{sw.summary_tag(label,start,'fixed' if excluded else '')}.csv"
            with p.open() as f:
                row=next(csv.DictReader(f))
            assert row["计量版本"]==sw.METRIC_VERSION
            out[label][start]=row
    return out


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--workers",type=int,default=48)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    assert args.workers<=int(os.environ.get("SLURM_CPUS_PER_TASK",args.workers))
    build_manifest=json.loads((EXP/"manifest.json").read_text())
    assert json.loads((EXP/"build_verification.json").read_text())["inputs_unchanged"]
    assert sw.BASE==build_manifest["base"] and sw.DEFAULT_STARTS==build_manifest["starts"]
    protected={ROOT/name for name in build_manifest["inputs"]}
    assert fingerprint(protected)==build_manifest["inputs"],"Build inputs changed"
    files=protected|{EXP/"scan.py",EXP/"run.py",EXP/"configs.txt"}
    original=fingerprint(files)
    save("scan_manifest.json",{"started_beijing":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "job_id":os.environ.get("SLURM_JOB_ID"),"inputs":original,"workers":args.workers})
    configs={}
    for line in (EXP/"configs.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            label,extra=line.split("|",1);configs[label]=extra
    labels=list(configs)
    if not args.resume:
        n=scan("configs.txt","full_A",args.workers)
        assert n==len(labels)*len(sw.DEFAULT_STARTS)*2
    groups={"full":summaries(labels,"full_A"),"A":summaries(labels,"full_A",True)}
    anchor=sw.EX5_ANCHOR_START
    a=set(groups["full"]["BASE"][anchor]["前五赢家"].split("/"))-{''}
    assert a
    unions={};winner_sets={}
    for label in labels[1:]:
        b=set(groups["full"][label][anchor]["前五赢家"].split("/"))-{''}
        assert b
        u=tuple(sorted(a|b));unions.setdefault(u,[]).append(label)
        winner_sets[label]={"A":sorted(a),"B":sorted(b),"U":list(u)}
    save("winner_sets.json",winner_sets)
    union_groups={};executed=len(labels)*len(sw.DEFAULT_STARTS)*2
    for i,(u,candidates) in enumerate(unions.items(),1):
        group=f"U{i}";group_labels=["BASE",*candidates]
        reuse=set(u)==a
        if reuse:
            groups[group]={label:groups["A"][label] for label in group_labels}
            (EXP/f"report_{group}.txt").write_text("U=A，复用全样本/A报告中的相同臂。\n")
        else:
            config=f"configs_{group}.txt"
            (EXP/config).write_text("\n".join(f"{label}|{configs[label]}" for label in group_labels)+"\n")
            if not args.resume or not (EXP/f"sweep_{group}.txt").exists():
                n=scan(config,group,args.workers,list(u))
                assert n==len(group_labels)*len(sw.DEFAULT_STARTS)
            executed+=len(group_labels)*len(sw.DEFAULT_STARTS)
            groups[group]=summaries(group_labels,group,True)
        union_groups[group]={"codes":list(u),"candidates":candidates,"reused_A":reuse}
    rows=[{"group":group,"arm":label,"start":start,**row}
          for group,arms in groups.items() for label,paths in arms.items() for start,row in paths.items()]
    with (EXP/"summary_rows.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)
    # Formal BASE must reproduce the last completed original-engine experiment.
    previous=ROOT/"data/experiments/exp_position_cap_high_20260908/summary_rows.csv"
    old={}
    with previous.open() as f:
        for row in csv.DictReader(f):
            if row["arm"]=="BASE" and row["group"] in ("full","A"):
                old[(row["group"],row["start"])]=row
    checks=[];diagnostics=[]
    for group in ("full","A"):
        for start,row in groups[group]["BASE"].items():
            prev=old[(group,start)]
            for field in sw.FIELDS:
                assert row[field]==prev[field],(group,start,field,row[field],prev[field])
            for field in ("前五赢家","首个净值日","末次净值日"):
                assert row[field]==prev[field],(group,start,field)
            checks.append(f"{group}:{start}:all_report_fields_identical")
    unchanged=fingerprint(files)==original
    save("verification.json",{"completed_beijing":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "inputs_unchanged":unchanged,"executed_paths":executed,"summary_rows":len(rows),
        "baseline_checks":checks,"union_groups":union_groups,
        "candidate_models":3,"candidate_combinations":10,"metric":sw.METRIC_VERSION})
    assert unchanged
    print(f"SCAN COMPLETE: {executed} paths, {len(rows)} summary rows",flush=True)


if __name__=="__main__":main()

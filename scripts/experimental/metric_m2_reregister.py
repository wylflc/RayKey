#!/usr/bin/env python3
"""计量口径 m1 → m2 的同批重算与重登（工作流 §12.1 第 2 款）。

BASE 与在评候选（OI-145：`BUY2`／`SB1_BUY2`）在 14 个标准起点上按全样本／剔除集 A／剔除集 U 三组重跑，
核对交易路径逐位不变（`年化_交易日口径` 等于旧 `年化`，期末资产、回撤、滚 5、换手相同；2011 锚点逐日净值与
逐笔产物逐字节相同），再出新旧读数、Δ 与 §12.1 第 2 款／第 4 款判定翻转表，并以 `M2REG20260905_` 前缀归档台账。

用法：
    python3 scripts/experimental/metric_m2_reregister.py sweep --workers 30
    python3 scripts/experimental/metric_m2_reregister.py report
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import csv
import filecmp
import hashlib
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep  # noqa: E402
import backtest_valuation_strategy as bt  # noqa: E402
import clean_derived_artifacts as archive  # noqa: E402
from dose_table import verdict  # noqa: E402

EXP = ROOT / "data/experiments/exp_metric_m2"
TROUGH = ROOT / "data/experiments/exp_trough_guard_review"
SB1 = ROOT / "data/experiments/exp_sb1_daily_buys"
ARMS = (("BASE", ""), ("BUY2", "--max-daily-buys 2"), ("SB1_BUY2", "--swap-source-block 1 --max-daily-buys 2"))
CANDIDATES = ("BUY2", "SB1_BUY2")
LEDGER_PREFIX = "M2REG20260905_"
# 新旧口径下应当逐位相同的交易路径读数（旧 `年化` 对新 `年化_交易日口径`）
PATH_KEYS = (("年化", "年化_交易日口径"), ("最大回撤", "最大回撤"), ("滚动5年年化中位", "滚动5年年化中位"),
             ("滚动5年年化P25", "滚动5年年化P25"), ("滚动5年回撤中位", "滚动5年回撤中位"),
             ("滚动5年Calmar中位", "滚动5年Calmar中位"), ("互不重叠5年块中位", "互不重叠5年块中位"),
             ("年均换手", "年均换手"), ("平均仓位", "平均仓位"))
# 因口径而变的读数
CHANGED_KEYS = ("年化", "Sharpe", "Calmar", "滚动5年Sharpe中位", "滚动3年Sharpe中位")
DELTA_KEYS = (("主读数", "滚动5年年化中位"), ("复利读数", "年化"), ("坏情形", "滚动5年年化P25"), ("闸门", "滚动5年回撤中位"))


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save_json(name: str, data) -> None:
    (EXP / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_pass(arms, excluded: str, workers: int, out) -> None:
    jobs = [(label, extra, start, excluded) for label, extra in arms for start in sweep.DEFAULT_STARTS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, line in enumerate(pool.map(sweep.run_one, jobs), 1):
            if len(line.split("|")) != 2 + len(sweep.FIELDS):
                raise RuntimeError(line)
            out.write(line + "\n")
            out.flush()
            if i % 14 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)


def top5(directory: Path, label: str) -> set[str]:
    path = directory / f"summary_{sweep.summary_tag(label, sweep.EX5_ANCHOR_START)}.csv"
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["策略"].startswith("trend_")]
    return {c for c in rows[-1][sweep.EX5_FIELD].split("/") if c}


def do_sweep(workers: int) -> None:
    old = json.loads((TROUGH / "manifest.json").read_text(encoding="utf-8"))
    assert sweep.BASE == old["base"], "BASE 与 m1 在册实验不一致，先核对再跑"
    assert sweep.DEFAULT_STARTS == old["starts"]
    assert sweep.METRIC_VERSION == bt.METRIC_VERSION == "m2"
    EXP.mkdir(parents=True, exist_ok=True)
    manifest = dict(base=sweep.BASE, starts=sweep.DEFAULT_STARTS, metric_version=bt.METRIC_VERSION,
                    engine_sha256_m2=sha(ROOT / "scripts/backtest_valuation_strategy.py"),
                    engine_sha256_m1=old["engine_sha256"], m1_sources=dict(base=str(TROUGH.relative_to(ROOT)),
                                                                          candidates=str(SB1.relative_to(ROOT))),
                    started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sweep.OUT_DIR = EXP / "summaries"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    arms = [(label, extra + f" --out-dir {sweep.OUT_DIR}") for label, extra in ARMS]
    a_m1 = top5(TROUGH / "summaries", "BASE")
    with (EXP / "sweep.txt").open("w", encoding="utf-8") as out:
        out.write(sweep.metric_header() + "\n")
        print(f"第一遍（全样本）：{len(arms)} 臂 × {len(sweep.DEFAULT_STARTS)} 起点", flush=True)
        run_pass(arms, "", workers, out)
        a_m2 = top5(sweep.OUT_DIR, "BASE")
        assert a_m2 == a_m1, (a_m1, a_m2)      # 赢家取自 contrib，与指标口径无关，必须相同
        excluded = ",".join(sorted(a_m2))
        out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{excluded}\n")
        print(f"第二遍（剔除集 A {excluded}）", flush=True)
        run_pass(arms, excluded, workers, out)
    manifest["A"] = sorted(a_m2)
    manifest["U"] = {}
    for cand in CANDIDATES:
        union = sorted(a_m2 | top5(EXP / "summaries", cand))
        manifest["U"][cand] = union
        sweep.OUT_DIR = EXP / f"summaries_union_{cand}"
        sweep.OUT_DIR.mkdir(exist_ok=True)
        union_arms = [(label, extra + f" --out-dir {sweep.OUT_DIR}") for label, extra in ARMS if label in ("BASE", cand)]
        with (EXP / f"sweep_union_{cand}.txt").open("w", encoding="utf-8") as out:
            out.write(sweep.metric_header() + "\n")
            for line in (EXP / "sweep.txt").read_text(encoding="utf-8").splitlines():
                if line.split("|", 1)[0] in ("BASE", cand):       # 全样本行照抄，使并集文件自含、--report 两组齐全
                    out.write(line + "\n")
            out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{','.join(union)}\n")
            print(f"剔除集 U（{cand}）：{','.join(union)}", flush=True)
            run_pass(union_arms, ",".join(union), workers, out)
    # 2011 锚点逐日／逐笔产物：与 m1 实验保存的同名产物逐字节核对交易路径
    art = EXP / "artifacts"
    art.mkdir(exist_ok=True)
    cmd = ([sys.executable, str(ROOT / "scripts/backtest_valuation_strategy.py")] + shlex.split(sweep.BASE)
           + ["--since", sweep.EX5_ANCHOR_START, "--out-dir", str(art), "--label-suffix", "_m2_BASE", "--artifacts"])
    with (EXP / "diag_BASE_2011.txt").open("w", encoding="utf-8") as out:
        subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)
    manifest["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_json("manifest.json", manifest)
    for name, title in (("sweep", "计量口径 m2：BASE 与 OI-145 候选"),) + tuple(
            (f"sweep_union_{c}", f"计量口径 m2：{c} 对 BASE，统一剔除赢家并集 U") for c in CANDIDATES):
        with (EXP / f"report_{name.removeprefix('sweep_') if name != 'sweep' else 'main'}.txt").open(
                "w", encoding="utf-8") as out, redirect_stdout(out):
            sweep.report(EXP / f"{name}.txt", title)
    print("扫描完成", flush=True)


def read_summary(directory: Path, label: str, start: str, exclude: bool) -> dict[str, str]:
    path = directory / f"summary_{sweep.summary_tag(label, start, 'x' if exclude else '')}.csv"
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["策略"].startswith("trend_")]
    return rows[-1]


def load_groups():
    """返回 {组名: {"m1": arms, "m2": arms}}；arms = {臂: {起点: {字段: float}}}。
    全样本／A 的 m1 读数来自 m1 实验的 summary CSV（全精度），m2 来自本实验 summary CSV；
    U 的两版都来自扫描输出行（六位小数）。"""
    def from_csv(directory_of, exclude):
        arms = {}
        for label, _extra in ARMS:
            arms[label] = {}
            for start in sweep.DEFAULT_STARTS:
                row = read_summary(directory_of(label), label, start, exclude)
                arms[label][start] = {k: (float(v) if v not in ("", None) and _is_num(v) else v) for k, v in row.items()}
        return arms

    m1_dir = lambda label: (TROUGH if label == "BASE" else SB1) / "summaries"
    m2_dir = lambda _label: EXP / "summaries"
    groups = {"全样本": {"m1": from_csv(m1_dir, False), "m2": from_csv(m2_dir, False)},
              "剔除集A": {"m1": from_csv(m1_dir, True), "m2": from_csv(m2_dir, True)}}
    for cand in CANDIDATES:
        old, *_o, old_version, _f = sweep.load_scan(SB1 / f"sweep_union_{cand}.txt")
        new, *_n, new_version, _g = sweep.load_scan(EXP / f"sweep_union_{cand}.txt")
        assert old_version == "m1" and new_version == "m2", (old_version, new_version)
        groups[f"剔除集U({cand})"] = {"m1": {k: dict(v) for k, v in old[sweep.EX5_PREFIX].items()},
                                     "m2": {k: dict(v) for k, v in new[sweep.EX5_PREFIX].items()}}
    return groups


def _is_num(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def paired(arms, label: str, key: str) -> float:
    base, arm = arms["BASE"], arms[label]
    common = [s for s in arm if s in base]
    return statistics.median(arm[s][key] - base[s][key] for s in common)


def level(arms, label: str, key: str) -> float:
    vals = [v[key] for v in arms[label].values() if v[key] == v[key]]
    return statistics.median(vals) if vals else float("nan")


RATIO_ITEMS = {"滚5Calmar", "滚5Sharpe", "Calmar", "Sharpe"}      # 第 4 款里以比率为单位的四项
DISPLAY_RATIO_BAND = 0.005       # 报表两位小数显示读法：|Δ| < 0.005 显示为 −0.00，§12.188 登记时即按此读为不劣


def clause4(arms_u, label: str, ratio_band: float = sweep.NOISE_BAND):
    """§12.1 第 4 款「去赢家全面优秀」：标准指标集（不计换手、仓位、长跑）各项变好方向的配对差中位 ≥ −0.15pp，
    或至多一项落在 [−1pp, −0.15pp)。百分率项阈值 0.0015；比率项（Calmar／Sharpe）的阈值由 `ratio_band` 给：
    0.0015 为严格读法，0.005 为报表两位小数显示读法（第 4 款未写明比率项单位，两种读法都报）。"""
    items = []
    for name, key, _scale, _w, _p, good in sweep.STANDARD_SET:
        if name in ("换手", "仓位"):
            continue
        items.append((name, paired(arms_u, label, key) * good))
    band = lambda name: ratio_band if name in RATIO_ITEMS else sweep.NOISE_BAND
    bad = [(n, d) for n, d in items if d < -band(n)]
    ok = not bad or (len(bad) == 1 and bad[0][1] >= -sweep.RULING_TOLERANCE)
    return ok, items, bad


def do_report() -> None:
    manifest = json.loads((EXP / "manifest.json").read_text(encoding="utf-8"))
    groups = load_groups()
    lines: list[str] = []
    say = lines.append
    say(f"# 计量口径 m1 → m2 同批重算（{manifest['finished_utc']} UTC）")
    say(f"BASE 与 OI-145 候选 BUY2／SB1_BUY2，14 起点 × 全样本／A／U。引擎 m1 {manifest['engine_sha256_m1'][:12]} → m2 {manifest['engine_sha256_m2'][:12]}。")
    say(f"A = {'/'.join(manifest['A'])}；U = " + "；".join(f"{c} {'/'.join(u)}" for c, u in manifest["U"].items()))

    # 1) 交易路径逐位核对
    say("\n## 1. 交易路径核对（m2 的 `年化_交易日口径` 对 m1 的 `年化`，其余同名列直接相等）")
    identity_rows, worst = [], 0.0
    for gname, pair in groups.items():
        tol = 1e-6 if gname.startswith("剔除集U") else 1e-9
        for label in pair["m1"]:
            for start in sweep.DEFAULT_STARTS:
                o, n = pair["m1"][label][start], pair["m2"][label][start]
                for ok_, nk in PATH_KEYS:
                    if gname.startswith("剔除集U") and nk not in n:
                        continue
                    diff = abs(float(o[ok_]) - float(n[nk]))
                    worst = max(worst, diff)
                    identity_rows.append(dict(group=gname, arm=label, start=start, key=ok_, m1=o[ok_], m2=n[nk], diff=diff))
                    if diff > tol:
                        say(f"  ✗ {gname} {label} {start} {ok_}: m1 {o[ok_]} m2 {n[nk]}")
    n_paths = sum(len(p["m1"]) * len(sweep.DEFAULT_STARTS) for p in groups.values())
    say(f"  核对 {n_paths} 条路径 × {len(PATH_KEYS)} 项，最大绝对差 {worst:.3e}（全样本／A 读 summary CSV 全精度，U 读六位小数输出行）")
    eq_old = sorted(TROUGH.glob("artifacts/*_trough_BASE_equity.csv"))[0]
    eq_new = sorted(EXP.glob("artifacts/*_m2_BASE_equity.csv"))[0]
    tr_old = sorted(TROUGH.glob("artifacts/*_trough_BASE_trades.csv"))[0]
    tr_new = sorted(EXP.glob("artifacts/*_m2_BASE_trades.csv"))[0]
    art = {"equity_identical": filecmp.cmp(eq_old, eq_new, shallow=False),
           "trades_identical": filecmp.cmp(tr_old, tr_new, shallow=False),
           "equity_rows": sum(1 for _ in eq_new.open(encoding="utf-8")) - 1}
    say(f"  2011-11-01 锚点逐日净值 {art['equity_rows']} 行逐字节相同：{art['equity_identical']}；逐笔产物逐字节相同：{art['trades_identical']}")

    # 2) 新旧水平与 Δ
    say("\n## 2. 因口径而变的读数（各起点再取中位；Δ 为逐起点配对差中位，pp 或比率单位）")
    metric_rows = []
    for gname, pair in groups.items():
        say(f"\n### {gname}")
        say("| 臂 | 年化 m1 | 年化 m2 | Sharpe m1 | Sharpe m2 | Calmar m1 | Calmar m2 | 滚5Sharpe m1 | 滚5Sharpe m2 | 滚5Calmar |")
        say("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for label in pair["m1"]:
            v = {}
            for ver in ("m1", "m2"):
                for key in CHANGED_KEYS + ("滚动5年Calmar中位",):
                    v[(ver, key)] = level(pair[ver], label, key)
                    metric_rows.append(dict(group=gname, arm=label, version=ver, metric=key, level=v[(ver, key)],
                                            paired_delta=(paired(pair[ver], label, key) if label != "BASE" else 0.0)))
            say(f"| {label} | {v[('m1','年化')]*100:.2f} | {v[('m2','年化')]*100:.2f} | {v[('m1','Sharpe')]:.3f} | {v[('m2','Sharpe')]:.3f} "
                f"| {v[('m1','Calmar')]:.3f} | {v[('m2','Calmar')]:.3f} | {v[('m1','滚动5年Sharpe中位')]:.3f} | {v[('m2','滚动5年Sharpe中位')]:.3f} "
                f"| {v[('m2','滚动5年Calmar中位')]:.3f} |")
        if any(l != "BASE" for l in pair["m1"]):
            say("\n| 臂 | Δ主 m1 | Δ主 m2 | Δ复利 m1 | Δ复利 m2 | ΔP25 m1 | ΔP25 m2 | Δ滚5回撤 m1 | Δ滚5回撤 m2 | ΔSharpe m1 | ΔSharpe m2 | Δ滚5Sharpe m1 | Δ滚5Sharpe m2 |")
            say("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
            for label in pair["m1"]:
                if label == "BASE":
                    continue
                cells = []
                for _name, key in DELTA_KEYS:
                    cells += [f"{paired(pair['m1'], label, key)*100:+.2f}", f"{paired(pair['m2'], label, key)*100:+.2f}"]
                for key in ("Sharpe", "滚动5年Sharpe中位"):
                    cells += [f"{paired(pair['m1'], label, key):+.3f}", f"{paired(pair['m2'], label, key):+.3f}"]
                say(f"| {label} | " + " | ".join(cells) + " |")

    # 3) 判定翻转
    say("\n## 3. 判定（§12.1 第 2 款双门槛；第 4 款 U 全面性）")
    flips = {}
    for cand in CANDIDATES:
        v1 = verdict(groups["全样本"]["m1"], groups["剔除集A"]["m1"], cand)
        v2 = verdict(groups["全样本"]["m2"], groups["剔除集A"]["m2"], cand)
        u1, u2 = groups[f"剔除集U({cand})"]["m1"], groups[f"剔除集U({cand})"]["m2"]
        ok1, _i1, bad1 = clause4(u1, cand)
        ok2, items2, bad2 = clause4(u2, cand)
        dk1, _d1, dbad1 = clause4(u1, cand, DISPLAY_RATIO_BAND)
        dk2, _d2, dbad2 = clause4(u2, cand, DISPLAY_RATIO_BAND)
        unit = lambda n, d: f"{n} {d:+.4f}" if n in RATIO_ITEMS else f"{n} {d*100:+.2f}pp"
        flips[cand] = dict(clause2_m1=v1, clause2_m2=v2, clause2_flipped=(v1.split("（")[0] != v2.split("（")[0]),
                           clause4_strict_m1=ok1, clause4_strict_m2=ok2, clause4_strict_flipped=(ok1 != ok2),
                           clause4_display_m1=dk1, clause4_display_m2=dk2, clause4_display_flipped=(dk1 != dk2),
                           clause4_bad_strict_m1=[(n, round(d, 6)) for n, d in bad1],
                           clause4_bad_strict_m2=[(n, round(d, 6)) for n, d in bad2],
                           clause4_bad_display_m1=[(n, round(d, 6)) for n, d in dbad1],
                           clause4_bad_display_m2=[(n, round(d, 6)) for n, d in dbad2],
                           clause4_items_m2={n: round(d, 6) for n, d in items2})
        say(f"- {cand}：第 2 款 m1「{v1}」→ m2「{v2}」{'（翻转）' if flips[cand]['clause2_flipped'] else '（不变）'}；"
            f"第 4 款 U 全面性（比率项按报表两位小数读法，|Δ| < 0.005 视为不劣）m1 {'通过' if dk1 else '不通过'} → m2 {'通过' if dk2 else '不通过'}"
            f"{'（翻转）' if dk1 != dk2 else '（不变）'}"
            + (f"，越带项 {', '.join(unit(n, d) for n, d in dbad2)}" if dbad2 else "")
            + f"；比率项按 0.0015 严格读法 m1 {'通过' if ok1 else '不通过'} → m2 {'通过' if ok2 else '不通过'}"
            f"{'（翻转）' if ok1 != ok2 else '（不变）'}"
            + (f"，越带项 m1 {', '.join(unit(n, d) for n, d in bad1)}；m2 {', '.join(unit(n, d) for n, d in bad2)}" if bad1 or bad2 else ""))

    # 4) 在册读数（BASE，m2）
    say("\n## 4. BASE 在册读数（m2，各起点再取中位；长跑为单起点水平）")
    for gname in ("全样本", "剔除集A"):
        arms = groups[gname]["m2"]["BASE"]
        med = lambda k: statistics.median(v[k] for v in arms.values())
        say(f"- {gname}：年化中位 {med('年化')*100:.2f}、Calmar {med('Calmar'):.2f}、Sharpe {med('Sharpe'):.2f}、"
            f"滚5 Sharpe {med('滚动5年Sharpe中位'):.2f}、滚5 Calmar {med('滚动5年Calmar中位'):.2f}、滚3 Sharpe {med('滚动3年Sharpe中位'):.2f}；"
            f"长跑 2009-11 CAGR {arms['2009-11-01']['年化']*100:.2f}／MDD {arms['2009-11-01']['最大回撤']*100:.1f}、"
            f"2011-11 CAGR {arms['2011-11-01']['年化']*100:.2f}／MDD {arms['2011-11-01']['最大回撤']*100:.1f}；"
            f"rf覆盖率 最小 {min(v['rf覆盖率'] for v in arms.values())*100:.1f}%")
        worst5 = min(arms.items(), key=lambda kv: kv[1]["滚动5年年化最差"])
        mdd = max(arms.items(), key=lambda kv: kv[1]["最大回撤"])
        mr = min(arms.items(), key=lambda kv: kv[1]["最低担保比例"])
        mb = min(arms.items(), key=lambda kv: kv[1]["最低股票同跌缓冲"])
        say(f"  跨起点尾部：最差滚5 {worst5[1]['滚动5年年化最差']*100:.2f}（{worst5[0]}，窗末 {worst5[1]['滚动5年年化最差窗口末日']}）；"
            f"最深 MDD {mdd[1]['最大回撤']*100:.2f}（{mdd[0]}，{mdd[1]['回撤区间']}）；"
            f"最低担保比例 {mr[1]['最低担保比例']*100:.2f}（{mr[0]}，{mr[1]['最低担保比例日']}）；"
            f"最低股票同跌缓冲 {mb[1]['最低股票同跌缓冲']*100:.2f}（{mb[0]}，{mb[1]['最低股票同跌缓冲日']}）、"
            f"同日总资产冲击缓冲 {mb[1]['最低总资产冲击缓冲']*100:.2f}；"
            f"强平 {sum(int(v['强平次数']) for v in arms.values())} 次／{sum(1 for v in arms.values() if v['强平次数'] > 0)} 起点；"
            f"5 年亏损起点 {sum(1 for v in arms.values() if v['滚动5年为负的窗口占比'] > 0)}/14；数据末端 {max(v['末次净值日'] for v in arms.values())}")

    (EXP / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (EXP / "paired_metrics_m1_m2.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(metric_rows[0]))
        w.writeheader()
        w.writerows(metric_rows)
    with (EXP / "path_identity.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(identity_rows[0]))
        w.writeheader()
        w.writerows(identity_rows)
    save_json("verdict_flips.json", flips)
    manifest["artifact_identity"] = art
    manifest["path_identity_max_abs_diff"] = worst
    manifest["paths_checked"] = n_paths
    # 台账归档：同批 m2 摘要以前缀入 scan_summaries.csv；旧 m1 行在 data/archive/scan_summaries_m1.csv，数臂用 scan_arms_index.csv（§12.1 第 12 款）
    entries = [SimpleNamespace(name=f"summary_{LEDGER_PREFIX}" + p.name.removeprefix("summary_"), path=str(p))
               for p in (EXP / "summaries").glob("summary_*.csv")]
    for cand in CANDIDATES:
        entries += [SimpleNamespace(name=f"summary_{LEDGER_PREFIX}U{cand}_" + p.name.removeprefix("summary_"), path=str(p))
                    for p in (EXP / f"summaries_union_{cand}").glob("summary_*.csv")]
    before = sum(1 for _ in archive.MERGED.open(encoding="utf-8")) - 1 if archive.MERGED.exists() else 0
    rows = archive.write_ledger(entries).current   # 分流写两本台账并重建 scan_arms_index.csv（§12.1 第 12 款数臂）
    manifest["ledger"] = dict(archived=len(entries), rows_before=before, rows_after=len(rows))
    save_json("manifest.json", manifest)
    print("\n".join(lines))
    print(f"\n台账 {before} → {len(rows)} 行（归档 {len(entries)} 份）；报告 {EXP / 'report.txt'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("sweep", "report"))
    ap.add_argument("--workers", type=int, default=30)
    args = ap.parse_args()
    if args.step == "sweep":
        do_sweep(args.workers)
    else:
        do_report()


if __name__ == "__main__":
    main()

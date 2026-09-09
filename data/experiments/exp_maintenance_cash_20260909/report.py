"""Write current valuation diagnostics and paired backtest tables."""
import argparse
from collections import Counter,defaultdict
import csv
import json
import math
from pathlib import Path
import statistics as st
import sys

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(ROOT/"scripts/experimental"))
import sweep_backtest_configs as sw
from ex_winner_symmetry_report import CLAUSE4


def number(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None


def write_csv(name,rows):
    with (EXP/name).open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)


def valuation_report():
    with (ROOT/"data/processed/a_share_pool_model_bands_adopted.csv").open() as f:
        core={r["security_code"] for r in csv.DictReader(f)}
    all_bands={};latest={}
    for tag in ("BASE","WCREP","MC050","MC100","MC150"):
        rows={}
        with (EXP/"val"/tag/"roic_bands_base.csv").open() as f:
            for r in csv.DictReader(f):rows[(r["security_code"],r["report_date"])]=r
        all_bands[tag]=rows
        last={}
        for (code,period),r in rows.items():
            if code not in last or period>last[code]["report_date"]:last[code]=r
        latest[tag]=last
    checks={};prev="WCREP"
    for tag in ("MC050","MC100","MC150"):
        violations=[]
        for key,r in all_bands[tag].items():
            old=all_bands[prev][key]
            if r["status"]==old["status"]=="ok":
                if number(r["intrinsic_value"])>number(old["intrinsic_value"])+.0002:
                    violations.append({"code":key[0],"period":key[1],"before":old["intrinsic_value"],"after":r["intrinsic_value"]})
        checks[f"{prev}_to_{tag}"]=violations
        prev=tag
    rows=[];overview={}
    for tag in ("WCREP","MC050","MC100","MC150"):
        counts=Counter();changes=[];cash_changes=[]
        for code in sorted(core):
            if code not in latest["BASE"]:continue
            b=latest["BASE"][code];a=all_bands[tag][(code,b["report_date"])]
            control=all_bands["WCREP"][(code,b["report_date"])]
            v0=number(b["intrinsic_value"]);v1=number(a["intrinsic_value"])
            vc=number(control["intrinsic_value"])
            change=(v1/v0-1) if b["status"]==a["status"]=="ok" and v0 and v1 else None
            cash_change=v1/vc-1 if vc and v1 and control["status"]==a["status"]=="ok" else None
            if control["status"]=="ok":
                if a["status"]!="ok":counts["cash_rejected"]+=1
                elif cash_change is not None and cash_change<-.00001:
                    counts["cash_reduced"]+=1;cash_changes.append(cash_change)
                else:counts["cash_unchanged"]+=1
            if b["status"]=="ok":
                counts["base_latest_ok"]+=1
                if a["status"]!="ok":counts["new_rejected"]+=1
                elif change is not None and change<-.00001:counts["reduced"]+=1;changes.append(change)
                elif change is not None and change>.00001:counts["increased"]+=1
                else:counts["unchanged"]+=1
            counts["status:"+a["maintenance_status"]]+=1
            rows.append({"arm":tag,"security_code":code,"security_name":b["security_name"],
                "report_date":b["report_date"],"available_at":b["available_at"],"base_status":b["status"],
                "arm_status":a["status"],"base_value":v0,"arm_value":v1,"change":change,
                "wc_control_value":vc,"change_vs_wc":cash_change,
                "base_path":b["roic_path"],"cash_ratio":a["maintenance_ratio"],
                "cash_raw_ratio":a["maintenance_raw_ratio"],"proxy_status":a["maintenance_status"],
                "intervals":a["maintenance_intervals"],"positive_intervals":a["maintenance_positive_intervals"],
                "net_reinvestment":a["maintenance_net_reinvestment"],"growth_allowance":a["maintenance_growth_allowance"],
                "nopat_total":a["maintenance_nopat_total"],"rejection_reason":a["reason"],"cash_blocked":a["cash_blocked"]})
        overview[tag]={"counts":dict(counts),"median_reduction_affected":st.median(changes) if changes else None,
                       "median_cash_reduction_affected":st.median(cash_changes) if cash_changes else None,
                       "all_history_proxy_status":dict(Counter(r["maintenance_status"] for r in all_bands[tag].values())),
                       "all_history_cash_blocked":sum(r["cash_blocked"]=="Y" for r in all_bands[tag].values())}
    write_csv("current_valuation_changes.csv",rows)
    (EXP/"valuation_diagnostics.json").write_text(json.dumps({"overview":overview,"monotonicity_violations":checks},ensure_ascii=False,indent=2)+"\n")
    assert not any(checks.values()),"Increasing cash burden raised a comparable valuation"
    text=["# 当前公司估值诊断", "", "同一报告期、同一股本口径比较；为原始研究带，未叠加预告或报告后的除权，不是现价交易建议。缺代理沿用原值不等于确认没有维持负担。", "",
          "相对原BASE的综合变化（包含营运资金数据修正）：", "",
          "| 强度 | 原最新有效带 | 降低 | 升高 | 新增拒绝 | 不变 | 降低者中位变化 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for tag,d in overview.items():
        c=d["counts"];change=d["median_reduction_affected"]
        change_text=f"{change*100:.2f}%" if change is not None else "—"
        text.append(f"| {tag} | {c.get('base_latest_ok',0)} | {c.get('reduced',0)} | {c.get('increased',0)} | {c.get('new_rejected',0)} | {c.get('unchanged',0)} | {change_text} |")
    text += ["", "现金约束本身的增量（相对WCREP数据控制）：", "",
             "| 强度 | 降低 | 新增拒绝 | 不变 | 降低者中位变化 |", "| --- | ---: | ---: | ---: | ---: |"]
    for tag in ("MC050","MC100","MC150"):
        d=overview[tag];c=d["counts"]
        text.append(f"| {tag} | {c['cash_reduced']} | {c['cash_rejected']} | {c['cash_unchanged']} | {d['median_cash_reduction_affected']:.2%} |")
    text += ["", "中心档现金约束示例（降幅较大者与新增拒绝）：", "", "| 公司 | 报告期 | 原值 | WCREP | 现金修正值 | 相对WCREP变化 | 占用代理 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    selected=sorted((r for r in rows if r["arm"]=="MC100" and r["base_status"]=="ok" and float(r["cash_ratio"])>0 and (r["arm_status"]!="ok" or (r["change_vs_wc"] is not None and r["change_vs_wc"]<-.00001))),key=lambda r:r["change_vs_wc"] if r["change_vs_wc"] is not None else -2)
    for r in selected[:20]:
        new=f"{r['arm_value']:.2f}" if r["arm_status"]=="ok" else "现金约束后不可估"
        change=f"{r['change_vs_wc']*100:.1f}%" if r["change_vs_wc"] is not None else "—"
        text.append(f"| {r['security_name']} {r['security_code']} | {r['report_date']} | {r['base_value']:.2f} | {r['wc_control_value']:.2f} | {new} | {change} | {float(r['cash_ratio']):.1%} |")
    text += ["", "全部公司与估计组成见 current_valuation_changes.csv；历史覆盖与负担单调性检查见 valuation_diagnostics.json。"]
    (EXP/"valuation_readout.md").write_text("\n".join(text)+"\n")
    print(json.dumps(overview,ensure_ascii=False),flush=True)


def backtest_report():
    with (EXP/"summary_rows.csv").open() as f: rows=list(csv.DictReader(f))
    groups=defaultdict(lambda:defaultdict(dict))
    for r in rows:groups[r["group"]][r["arm"]][r["start"]]=r
    paired=[];decisions=[];qualifications={}
    for group,arms in groups.items():
        base=arms["BASE"]
        for arm,paths in arms.items():
            assert set(paths)==set(base)==set(sw.DEFAULT_STARTS)
            for key in sw.FIELDS:
                vals=[sw._field_value(paths[s],key) for s in sw.DEFAULT_STARTS]
                delta=[sw._field_value(paths[s],key)-sw._field_value(base[s],key) for s in sw.DEFAULT_STARTS]
                paired.append({"group":group,"arm":arm,"metric":key,"level_median":st.median(vals),
                               "paired_delta_median":st.median(delta),"positive_starts":sum(d>0 for d in delta),"starts":len(delta)})
            if group.startswith("U") and arm!="BASE":
                bad=[]
                for key,scale,good in CLAUSE4:
                    d=st.median((number(paths[s][key])-number(base[s][key]))*scale*good for s in sw.DEFAULT_STARTS)
                    noise=.005 if scale==1 else .15
                    floor=.033 if scale==1 else 1
                    if d < -noise:bad.append({"metric":key,"oriented_delta":d,"beyond_one_pp":d < -floor})
                qualifications[arm]={"group":group,"excellent":not bad or (len(bad)==1 and not bad[0]["beyond_one_pp"]),"inferior":bad}
    write_csv("paired_metrics.csv",paired)
    cash_only=[]
    for group in ("full","A"):
        control=groups[group]["WCREPSEP09"]
        for arm,paths in groups[group].items():
            if not arm.startswith("MC"):continue
            for key in sw.FIELDS:
                delta=[sw._field_value(paths[s],key)-sw._field_value(control[s],key) for s in sw.DEFAULT_STARTS]
                cash_only.append({"group":group,"arm":arm,"metric":key,"paired_delta_vs_wc":st.median(delta),
                                  "positive_starts":sum(d>0 for d in delta),"starts":len(delta)})
    write_csv("paired_vs_wc_control.csv",cash_only)
    index={(r["group"],r["arm"],r["metric"]):r for r in paired}
    def metric(group,arm,key):return index[(group,arm,key)]
    candidates=[a for a in groups["full"] if a!="BASE"]
    for arm in candidates:
        reasons=[];verdict="初步通过"
        track="A" if arm=="WCREPSEP09" else "B"
        for key in ("滚动5年年化中位","年化"):
            a=metric("full",arm,key)["paired_delta_median"];b=metric("A",arm,key)["paired_delta_median"]
            if track=="A":
                if a < -sw.RULING_TOLERANCE:
                    verdict="不采纳";reasons.append(f"{key}轨道A损失护栏未过")
            elif min(a,b)<-sw.RULING_TOLERANCE or (min(a,b)<-sw.NOISE_BAND and max(a,b)<sw.CLEAR_GAIN):
                verdict="不采纳";reasons.append(f"{key}双表条件未过")
            elif min(a,b)<-sw.NOISE_BAND and verdict!="不采纳":verdict="需裁定"
        dd=metric("full",arm,"滚动5年回撤中位")["paired_delta_median"]
        if dd>sw.DRAWDOWN_GATE:verdict="不采纳";reasons.append("回撤闸门")
        negative=sum(float(groups["full"]["BASE"][s]["滚动5年为负的窗口占比"])==0 and float(groups["full"][arm][s]["滚动5年为负的窗口占比"])>0 for s in sw.DEFAULT_STARTS)
        if negative>len(sw.DEFAULT_STARTS)/2:verdict="不采纳";reasons.append("负收益窗口否决")
        decisions.append({"arm":arm,"track":track,"verdict":verdict,"reasons":reasons,"U":qualifications[arm]})
    (EXP/"decisions.json").write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+"\n")
    text=["# 持续现金占用模型配对回测", "", "全部为历史描述，非未来收益预测。原BASE、只修营运资金数据的WCREP控制、三档现金模型×三档换仓边际，共10候选，14起点、m2。", "",
          "| 候选 | 全样本年化中位 | Δ全样本年化 | Δ去赢家A年化 | Δ去赢家U年化 | Δ滚5全样本 | Δ滚5 A | Δ滚5回撤 | 初步判定 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for d in sorted(decisions,key=lambda d:metric("full",d["arm"],"年化")["paired_delta_median"],reverse=True):
        arm=d["arm"];u=d["U"]["group"]
        cells=[f"{metric('full',arm,'年化')['level_median']*100:.2f}%"]
        for group,key in [("full","年化"),("A","年化"),(u,"年化"),("full","滚动5年年化中位"),("A","滚动5年年化中位"),("full","滚动5年回撤中位")]:
            cells.append(f"{metric(group,arm,key)['paired_delta_median']*100:+.2f}pp")
        text.append(f"| {arm} | "+" | ".join(cells)+f" | {d['verdict']} |")
    text += ["", "Δ均为逐起点配对差的中位，不能由两个水平中位相减复原；回撤Δ为正表示变深。完整标准指标/正号数见 paired_metrics.csv；跨起点尾部、长跑起点和集中度见 report_full_A.txt 与各 report_U*.txt。", "",
             f"BASE全样本年化中位 {metric('full','BASE','年化')['level_median']:.2%}，A表 {metric('A','BASE','年化')['level_median']:.2%}。",
             "", "WCREP按预登记轨道A护栏判定；现金模型按轨道B。原扫描器报告中的通用轨道B标签不替代此处对数据修复的轨道A判定。",
             "", "本轮未替换生产：即使初步收益条件通过，仍需检查代理的经济解释、独立前向证据与工作流规定的采纳前验证。"]
    text += ["", "中心换仓边际0.15下，现金约束相对只修数据的WCREP控制：", "",
             "| 模型 | Δ全样本年化 | Δ A 年化 | Δ全样本滚5 | Δ A 滚5 |", "| --- | ---: | ---: | ---: | ---: |"]
    cash_index={(r['group'],r['arm'],r['metric']):r['paired_delta_vs_wc'] for r in cash_only}
    for arm in ("MC050M15SEP09","MC100M15SEP09","MC150M15SEP09"):
        cells=[f"{cash_index[(g,arm,k)]*100:+.2f}pp" for g,k in [('full','年化'),('A','年化'),('full','滚动5年年化中位'),('A','滚动5年年化中位')]]
        text.append(f"| {arm} | "+" | ".join(cells)+" |")
    (EXP/"readout.md").write_text("\n".join(text)+"\n")
    print("\n".join(text),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--valuation-only",action="store_true");a=p.parse_args()
    valuation_report()
    if not a.valuation_only:backtest_report()

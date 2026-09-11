"""Isolated adapter: production cap execution plus a day-end holdings observer."""
import ast
import __future__
import csv
import inspect
import json
import sys
from common import EXP, ROOT, grid
from policy import CombinedConstraint, ReturnPanel, RiskPolicy
import backtest_valuation_strategy as bt


def main():
    i=sys.argv.index('--risk-arm'); arm=sys.argv[i+1]; del sys.argv[i:i+2]
    spec=next(r for r in grid() if r['arm']==('BASE' if arm=='OFF' else arm))
    tag=sys.argv[sys.argv.index('--label-suffix')+1].lstrip('_')
    out=EXP/'raw'/tag; out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((EXP/'manifest.json').read_text())
    bt.ACTIONS=EXP/manifest['frozen']['data/raw/corporate_actions/a_share_corporate_actions.csv']
    bt.RATES=EXP/manifest['frozen']['data/reference/cost_of_equity_inputs.csv']
    policy=RiskPolicy(spec); constraint=None; panel=None
    original_constraint=bt.EquityBondConstraint
    def factory(*args,**kwargs):
        nonlocal constraint
        constraint=CombinedConstraint(original_constraint(*args,**kwargs),policy)
        return constraint
    # Native BASE deliberately avoids even the risk wrapper; OFF checks zero effect.
    if arm!='BASE': bt.EquityBondConstraint=factory
    log=(out/'risk.csv').open('w',newline='')
    writer=None
    def capture(day,portfolio,marks,prices,actions):
        nonlocal panel,writer
        mv={c:lot.shares*marks.get(c,0.) for c,lot in portfolio.lots.items()}
        total=sum(mv.values()); eq=portfolio.equity(marks)
        if arm=='BASE': return
        if panel is None and spec['kind'] in ('vol','joint'):
            dates=[r['date'] for r in csv.DictReader((ROOT/'data/raw/ohlcv/INDEX_000300.csv').open())]
            panel=ReturnPanel(bt.daily_returns(prices,actions),dates)
        row=dict(date=day,**constraint.last,exposure=total/eq if eq else 0,
            stress20_top3=.2*sum(sorted(mv.values(),reverse=True)[:3])/eq if eq else 0)
        if writer is None:
            writer=csv.DictWriter(log,fieldnames=list(row),lineterminator='\n');writer.writeheader()
        writer.writerow(row)
        policy.observe(day,mv,panel)
    if arm!='BASE':
        tree=ast.parse(inspect.getsource(bt.run)); matches=0
        for node in ast.walk(tree):
            for _,value in ast.iter_fields(node):
                if not isinstance(value,list): continue
                for j,stmt in list(enumerate(value)):
                    if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='weights' for t in stmt.targets):
                        value.insert(j,ast.parse('_risk_observe(day,portfolio,marks,prices,actions)').body[0]);matches+=1
        assert matches==1
        bt.__dict__['_risk_observe']=capture
        exec(compile(ast.fix_missing_locations(tree),'<risk holdings observer>','exec',
                     flags=__future__.annotations.compiler_flag),bt.__dict__)
    summary=bt.summarize
    def summarize(name,result,*args):
        if name.startswith('trend_'):
            with (out/'nav.csv').open('w',newline='') as f:
                w=csv.writer(f,lineterminator='\n')
                w.writerow(('date','net_equity','cash','positions','debt','margin_ratio','top1_weight','top3_weight'))
                w.writerows(result['equity'])
            (out/'result_info.json').write_text(json.dumps(dict(stats=result['stats'],contrib=result['contrib']),ensure_ascii=False)+'\n')
        return summary(name,result,*args)
    bt.summarize=summarize
    try: return bt.main()
    finally: log.close()


if __name__=='__main__': raise SystemExit(main())

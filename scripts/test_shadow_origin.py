"""Continuation must preserve trading, dividend and cooldown state across rules."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backtest_valuation_strategy as bt
import shadow_from_origin as origin
from test_shadow_portfolio import fixture


class OriginTests(unittest.TestCase):
    def setUp(self):
        self.fees = patch.dict(bt.FEES, commission=0., min_fee=0., stamp=0., transfer=0., paid=0., stamp_mode='flat')
        self.fees.start(); self.addCleanup(self.fees.stop)

    def assert_continuation(self, kw):
        full = []; full_final = []; full_states = []
        whole = bt.run(**kw, ledger=full, portfolio_snapshots=full_states, final_portfolio=full_final)
        ds = sorted(kw['states']); cut = ds[1]
        left = dict(kw, until=cut); end=[]; states=[]; ledger=[]
        first = bt.run(**left, ledger=ledger, portfolio_snapshots=states, final_portfolio=end)
        right = dict(kw, since=cut, initial_portfolio=end[0], capital=first['equity'][-1][1],
                     initial_cooldown=dict(buy=states[-1]['buy_counters'],sell=states[-1]['sell_counters']))
        finish=[]
        second=bt.run(**right,ledger=ledger,final_portfolio=finish)
        self.assertEqual(whole['equity'], first['equity']+second['equity'][1:])
        self.assertEqual(full,ledger)
        self.assertEqual(full_final[0].lots,finish[0].lots)
        self.assertEqual(full_final[0].interest_paid,finish[0].interest_paid)
        self.assertEqual(full_final[0].dividend_tax_paid,finish[0].dividend_tax_paid)
        return states

    def test_continuation_preserves_confirmed_cooldown(self):
        ds=('2024-01-05','2024-01-08','2024-01-09')
        kw=fixture(ds)
        kw.update(lot_ratio_cooldown=True,lot_cooldown_start='confirmed')
        kw['states']={d:[('A',100.,200.,.5)] for d in ds}
        kw['mas']={'A':{d:{20:90.,60:80.} for d in ds}}
        states=self.assert_continuation(kw)
        self.assertGreater(states[-1]['buy_counters'].get('A',0),0)

    def test_dividend_tax_batches_and_interest_survive_continuation(self):
        ds=('2024-01-05','2024-01-08','2024-01-09')
        kw=fixture(ds)
        kw['initial_portfolio'].lots['A'].sublots=[['2024-01-01',1000.,0.]]
        kw.update(dividend_tax=True,stop_ma=60,stop_line='min_entry_current',stop_basis='exec')
        kw['actions']={'A':{ds[1]:(1.,0.,0.,0.)}}
        kw['prices']['A'][ds[-1]]=85.
        self.assert_continuation(kw)

    def test_initial_cooldown_requires_seed(self):
        kw=fixture();kw.pop('initial_portfolio')
        with self.assertRaisesRegex(ValueError,'closing portfolio seed'):
            bt.run(**kw,initial_cooldown={'buy':{'A':2},'sell':{}})

    def test_shared_counter_seed_cannot_lose_sell_state(self):
        with self.assertRaisesRegex(ValueError,'equal buy/sell'):
            bt.run(**fixture(),lot_cooldown_shared=True,lot_cooldown_start='plan',
                   initial_cooldown={'buy':{'A':2},'sell':{}})

    def test_rule_effective_date_does_not_relabel_prior_sessions(self):
        base=origin.sh.sweep.BASE
        before=origin.kwargs(base,'2026-09-14'); after=origin.kwargs(base,'2026-09-15')
        self.assertEqual(before['lot_cooldown_start'],'plan')
        self.assertEqual(after['lot_cooldown_start'],'confirmed')
        self.assertEqual(before['execution_consistency'],'legacy')
        self.assertEqual(after['execution_consistency'],'signal')

    def test_append_quotes_cannot_rewrite_old_prices(self):
        old=[dict(date='2026-09-18',close=10.)]
        new=old+[dict(date='2026-09-21',close=11.)]
        self.assertEqual(origin.merge_prices(old,new),new)
        with self.assertRaisesRegex(ValueError,'revised'):
            origin.merge_prices(old,[dict(date='2026-09-18',close=12.)])

    def test_confirmed_fills_exclude_wrong_opening_path(self):
        evidence=dict(baseline_date='2026-08-28',shares_before_0828=5500,
            confirmed_buys={'2026-08-28':4900,'2026-08-31':5100},opening_shares=10400,
            shares_confirmed_on_0903=15500,selected_scenario='missing_300_on_0828')
        with tempfile.TemporaryDirectory() as tmp, patch.object(origin,'BOOK',Path(tmp)):
            path=Path(tmp)/'opening_confirmation.json'
            path.write_text(json.dumps(evidence))
            manifest=dict(baseline_date='2026-08-28',scenarios={'missing_300_on_0828':10400},
                          opening_confirmation_sha256=origin.sh.sha(path.read_bytes()))
            self.assertEqual(origin.opening_confirmation(manifest),evidence)
            manifest['scenarios']={'missing_300_on_0831':10100}
            with self.assertRaisesRegex(ValueError,'do not reconcile'):
                origin.opening_confirmation(manifest)
            manifest['scenarios']={'missing_300_on_0828':10400}
            evidence['confirmed_buys']['2026-08-28']=4600
            path.write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                origin.opening_confirmation(manifest)
            manifest['opening_confirmation_sha256']=origin.sh.sha(path.read_bytes())
            with self.assertRaisesRegex(ValueError,'do not reconcile'):
                origin.opening_confirmation(manifest)

    def test_cannot_select_one_opening_without_confirmation(self):
        with self.assertRaisesRegex(ValueError,'requires confirmation'):
            origin.opening_confirmation(dict(scenarios={'missing_300_on_0828':10400}))
        self.assertIsNone(origin.opening_confirmation(dict(
            scenarios={'missing_300_on_0828':10400,'missing_300_on_0831':10100})))

    def test_execution_day_closing_membership_cannot_force_same_day_exit(self):
        snapshots=[]
        for day in ('2026-08-28','2026-08-31'):
            snapshots.append(dict(date=day,base=origin.sh.sweep.BASE,members=['A'],blocked=[],
                holdings={'A':dict(shares=1000.,cost=100.,stop=90.)},
                account=dict(cash_cny='0',margin_debt_cny='20000'),actions={},all_actions={},equity_bond=None,
                quotes={'A':dict(trade_date=day,close='100',ma20='101',ma60='95',
                    model_intrinsic_value='50',model_pv='2',hold_intrinsic_value='50',hold_pv='2')}))
        manifest=dict(fees=dict(bt.USER_FEES,stamp_mode='flat'))
        before=origin.replay(snapshots,{},manifest,10100)
        snapshots[-1]['members']=[]
        after=origin.replay(snapshots,{},manifest,10100)
        self.assertEqual(before,after)
        self.assertEqual(after[2][-1]['holdings']['A']['shares'],1000.)


if __name__=='__main__':
    unittest.main()

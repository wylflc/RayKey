"""Behavioral checks of the experimental cap, including signal-day timing."""
from datetime import date, timedelta
import json
import unittest
from engine import load_engine

bt=load_engine()
native=load_engine(False)


def simulate(pvs, threshold=.6, module=bt, cap=.6, capital=20000, price=10):
    days=[(date(2024,1,2)+timedelta(days=i)).isoformat() for i in range(len(pvs))]
    states={d:[('A',price,price/pv,pv)] for d,pv in zip(days,pvs)}
    prices={'A':{d:price for d in days}}
    mas={'A':{d:{20:price*.9,60:price*.8} for d in days}}
    ledger=[]
    extra={'position_cap_pv_release':threshold} if module is bt else {}
    result=module.run('trend',.05,states,prices,{},mas,days[0],days[-1],capital,
        trend_tranche=True,trend_ma=(20,60),exec_delay=1,lot_size=100,
        lot_ratio_cooldown=True,position_cap=cap,ledger=ledger,**extra)
    return ledger,result


def amount(ledger):
    return sum(float(r['shares'])*float(r['price']) for r in ledger if r['action']=='买入')


class ResearchCapTests(unittest.TestCase):
    def test_disabled_matches_native(self):
        a,ar=simulate([.5]*22,threshold=0)
        b,br=simulate([.5]*22,module=native)
        self.assertEqual(a,b)
        # Independent modules define distinct dataclass types; compare their data.
        self.assertEqual(json.dumps(ar,default=vars,sort_keys=True),
                         json.dumps(br,default=vars,sort_keys=True))

    def test_threshold_is_strict_and_same_as_no_cap_below(self):
        low,_=simulate([.59]*22); equal,_=simulate([.6]*22); high,_=simulate([.61]*22)
        uncapped,_=simulate([.59]*22,cap=0)
        self.assertEqual(amount(low),amount(uncapped))
        self.assertGreater(amount(low),12000)
        self.assertEqual(amount(equal),12000); self.assertEqual(amount(high),12000)

    def test_release_changes_on_signal_day_not_execution_day(self):
        low,_=simulate([.59]*16+[.61]*6)
        buys=[r for r in low if r['action']=='买入']
        self.assertEqual(amount(low),16000)
        self.assertEqual(buys[-1]['date'],'2024-01-18')
        self.assertFalse(any(r['action']=='卖出' for r in low))

    def test_lot_fallback_respects_active_cap(self):
        high,_=simulate([.6]*4,capital=1000)
        low,result=simulate([.59]*4,capital=1000)
        self.assertEqual(amount(high),0); self.assertEqual(amount(low),1000)
        self.assertGreaterEqual(min(r[2] for r in result['equity']),0)

    def test_invalid_threshold_fails(self):
        for threshold in (-.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): simulate([.5]*3,threshold)


if __name__=='__main__': unittest.main()

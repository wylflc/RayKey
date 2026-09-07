#!/usr/bin/env python3
"""余仓阈值的边界、T+1 真实减持与默认兼容性回归。"""
import math
import unittest
import backtest_valuation_strategy as bt


class ResidualClearTest(unittest.TestCase):
    def test_strict_threshold_after_rounding(self):
        # 15 万一档，10 元一股，卖 15,000 股；余 22,500 股恰等于 1.5 档时不清。
        self.assertEqual(bt.sell_shares(15000, 37400, 10, 100, 22500), 37400)
        self.assertEqual(bt.sell_shares(15000, 37500, 10, 100, 22500), 15000)
        self.assertEqual(bt.sell_shares(15000, 37600, 10, 100, 22500), 15000)

    def test_lot_rounding_and_no_independent_cleanup(self):
        self.assertEqual(bt.sell_shares(15009, 15100, 10, 100), 15000)
        self.assertEqual(bt.sell_shares(15009, 15100, 10, 100, 1500), 15100)
        self.assertEqual(bt.sell_shares(15009, 15050, 10, 100), 15050)
        self.assertEqual(bt.sell_shares(0, 100, 10, 100, 22500), 0)
        self.assertEqual(bt.sell_shares(99, 100, 10, 100, 22500), 0)

    @staticmethod
    def path(clear=0.0, *, mode='lot'):
        # 只在第一天发建仓信号：次日买入，第四天由第三天的涨幅信号减持。
        prices=[10, 10, 22, 22]
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
        states={d:[('A',p,12.5 if i==0 else 9,p/(12.5 if i==0 else 9))]
                for i,(d,p) in enumerate(zip(days,prices))}
        px={'A':dict(zip(days,prices))};mas={'A':{d:{20:9,60:8} for d in days}}
        ledger=[];bt.DELISTED_LAST.clear()
        result=bt.run('trend',.05,states,px,{},mas,days[0],days[-1],100_000,
                      trend_tranche=True,trend_ma=(20,60),exec_delay=1,exec_price='close',
                      stop_ma=60,stop_line='min_entry_current',entry_below_ma60='ma60_stop',
                      gain_sell=1.1,gain_sell_mode='ungated',lot_size=100,lot_ratio_cooldown=True,
                      residual_clear=mode,residual_clear_tranches=clear,ledger=ledger)
        return ledger,result

    def test_t1_gain_trim_expands_existing_order(self):
        normal,_=self.path();cleared,_=self.path(1.5)
        sells=lambda rows:[r for r in rows if r['action']=='卖出']
        self.assertEqual(len(sells(normal)),1)
        self.assertEqual(float(sells(normal)[0]['shares']),200)
        self.assertEqual(float(sells(cleared)[0]['shares']),500)
        self.assertEqual(sells(cleared)[0]['date'],'2024-01-05')
        self.assertEqual(float(sells(cleared)[0]['price']),22)
        self.assertEqual([r for r in normal if r['action']=='买入'],[r for r in cleared if r['action']=='买入'])

    def test_default_and_legacy_mode_stay_replayable(self):
        self.assertEqual(self.path(),self.path(0))
        self.assertEqual(self.path(mode='tranche'),self.path(1))

    @staticmethod
    def outpool_path(price, clear=0.0, mode='lot'):
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
        states={d:[('A',price,price*2,.5)] for d in days}
        px={'A':dict.fromkeys(days,price)}
        mas={'A':{d:{20:price*.9,60:price*.8} for d in days}}
        ledger=[];bt.DELISTED_LAST.clear()
        result=bt.run('trend',.05,states,px,{},mas,days[0],days[-1],100_000,
                      trend_tranche=True,trend_ma=(20,60),exec_delay=1,
                      lot_size=100,lot_ratio_cooldown=True,
                      universe=[(days[0],{'A'}),(days[-1],set())],
                      residual_clear=mode,residual_clear_tranches=clear,ledger=ledger)
        return ledger,result

    def test_outpool_trim_and_high_price_one_lot(self):
        for price,normal_quantity,cleared_quantity in [(10,500,1000),(60,100,200)]:
            normal,_=self.outpool_path(price)
            cleared,_=self.outpool_path(price,1.5)
            sells=lambda rows:[r for r in rows if r['action']=='卖出']
            self.assertEqual(len(sells(normal)),1)
            self.assertEqual(len(sells(cleared)),1)
            self.assertEqual(float(sells(normal)[0]['shares']),normal_quantity)
            self.assertEqual(float(sells(cleared)[0]['shares']),cleared_quantity)
            self.assertEqual(sells(cleared)[0]['date'],'2024-01-05')
            self.assertEqual([r for r in normal if r['action']=='买入'],
                             [r for r in cleared if r['action']=='买入'])

    def test_legacy_high_price_semantics_preserved(self):
        self.assertEqual(self.outpool_path(60),self.outpool_path(60,mode='tranche'))

    def test_invalid_multiplier_rejected(self):
        for value in [-1, math.nan, math.inf]:
            with self.assertRaises(ValueError):self.path(value)


if __name__=='__main__':unittest.main()

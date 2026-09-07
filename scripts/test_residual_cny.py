#!/usr/bin/env python3
"""固定金额余仓清空：边界、实际单笔合并与最低佣金。"""
import math
import unittest
import backtest_valuation_strategy as bt


class ResidualCnyTest(unittest.TestCase):
    def setUp(self):
        self.fees = bt.FEES.copy()
        bt.FEES.update(commission=.0001,min_fee=5,transfer=0,stamp=0,stamp_mode='flat',paid=0)

    def tearDown(self):
        bt.FEES.clear();bt.FEES.update(self.fees)

    def test_fixed_value_strict_boundary_after_rounding(self):
        # 原卖 15,000 股；余仓 49,000 / 50,000 / 51,000 元。
        for held,want in [(19900,19900),(20000,15000),(20100,15000)]:
            self.assertEqual(bt.sell_shares(15009,held,10,100,clear_value=50000),want)
        self.assertEqual(bt.sell_shares(0,100,10,100,clear_value=50000),0)
        self.assertEqual(bt.sell_shares(99,100,10,100,clear_value=50000),0)

    @staticmethod
    def run_path(clear=0,price=10):
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
        states={d:[('A',price,price*2,.5)] for d in days}
        px={'A':dict.fromkeys(days,price)}
        mas={'A':{d:{20:price*.9,60:price*.8} for d in days}}
        ledger=[];bt.DELISTED_LAST.clear()
        result=bt.run('trend',.05,states,px,{},mas,days[0],days[-1],100_000,
                      trend_tranche=True,trend_ma=(20,60),exec_delay=1,
                      lot_size=100,lot_ratio_cooldown=True,
                      universe=[(days[0],{'A'}),(days[-1],set())],
                      residual_clear_cny=clear,ledger=ledger)
        return ledger,result

    def test_expands_one_existing_order_without_a_second_minimum(self):
        normal,_=self.run_path()
        clear,result=self.run_path(50000)
        sell=lambda rows:[r for r in rows if r['action']=='卖出']
        self.assertEqual(len(sell(clear)),1)
        self.assertEqual(float(sell(normal)[0]['shares']),400)
        self.assertEqual(float(sell(clear)[0]['shares']),900)
        self.assertEqual(sell(clear)[0]['date'],'2024-01-05')
        self.assertEqual([r for r in normal if r['action']=='买入'],[r for r in clear if r['action']=='买入'])
        self.assertEqual(result['fees'],15)  # 两张买单、一张合并卖单。

    def test_high_price_one_lot_path(self):
        rows,_=self.run_path(50000,60)
        sells=[r for r in rows if r['action']=='卖出']
        self.assertEqual(len(sells),1)
        self.assertEqual(float(sells[0]['shares']),200)

    def test_commission_breakeven_and_merged_order(self):
        fee=lambda amount:bt._fee_quiet(amount,'2026-09-07','sell')
        self.assertEqual(fee(50000),5)
        self.assertAlmostEqual(fee(150000)+fee(1000)-fee(151000),4.9)
        self.assertEqual(fee(150000)+fee(50000)-fee(200000),0)
        self.assertEqual(bt.FEES['paid'],0)

    def test_invalid_threshold_rejected(self):
        for value in [-1,math.nan,math.inf]:
            with self.assertRaises(ValueError):self.run_path(value)

    def test_final_plan_does_not_leave_offset_remainder(self):
        days=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
        prices=[10,10,22,22]
        states={d:[('A',p,p*2,.5)] for d,p in zip(days,prices)}
        px={'A':dict(zip(days,prices))}
        mas={'A':{d:{20:p*.9,60:p*.8} for d,p in zip(days,prices)}}
        outcomes={}
        for final in [False,True]:
            ledger=[];bt.DELISTED_LAST.clear()
            result=bt.run('trend',.05,states,px,{},mas,days[0],days[-1],100_000,
                          trend_tranche=True,trend_ma=(20,60),exec_delay=1,
                          lot_size=100,lot_ratio_cooldown=True,gain_sell=.5,
                          gain_sell_mode='ungated',net_same_day=True,
                          residual_clear_cny=50000,residual_clear_final=final,ledger=ledger)
            outcomes[final]=(ledger,result)
        normal,result_normal=outcomes[False]
        final,result_final=outcomes[True]
        sells=lambda rows:[r for r in rows if r['action']=='卖出']
        self.assertEqual(float(sells(normal)[0]['shares']),500)
        self.assertEqual(float(sells(final)[0]['shares']),700)
        self.assertEqual(len(sells(final)),1)
        self.assertEqual(result_normal['equity'][-1][3],1)
        self.assertEqual(result_final['equity'][-1][3],0)
        self.assertEqual([r for r in normal if r['action']=='买入'],[r for r in final if r['action']=='买入'])

    def test_final_guard_preserves_zero_sale_and_boundary(self):
        portfolio=bt.Portfolio(cash=0)
        reg={'A':[{'left':10000,'price':10}]}
        self.assertTrue(bt.net_rebuy_leaves_small(reg,portfolio,'A',4900,50000))
        self.assertFalse(bt.net_rebuy_leaves_small(reg,portfolio,'A',5000,50000))
        self.assertFalse(bt.net_rebuy_leaves_small(reg,portfolio,'A',10000,50000))
        self.assertFalse(bt.net_rebuy_leaves_small(reg,portfolio,'A',11000,50000))
        self.assertFalse(bt.net_rebuy_leaves_small(reg,portfolio,'B',100,50000))


if __name__=='__main__':unittest.main()

"""Low signal removes financing; high signal restores the untouched formal baseline."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
import backtest_valuation_strategy as bt


class HighBaseConstraint(bt.EquityBondConstraint):
    def resolve(self,signal_day):
        signal,cap=super().resolve(signal_day)
        return signal, None if cap==self.upper else cap


if __name__=='__main__':
    bt.EquityBondConstraint=HighBaseConstraint
    bt.main()

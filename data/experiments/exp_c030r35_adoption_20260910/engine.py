"""Reuse the frozen signal state machine and portfolio engine with this batch's registry."""
import sys
from common import EXP, PRIOR, grid, load_module
sys.path.insert(0,str(PRIOR))
old=load_module('ebopt_frozen_engine',PRIOR/'engine.py')
old.EXP=EXP
old.grid=grid


if __name__=='__main__':
    raise SystemExit(old.main())

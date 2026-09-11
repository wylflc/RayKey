"""Plot synchronized peak-to-trough paths; account returns include leverage."""
import csv
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import PercentFormatter

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
REF = EXP.parent/'exp_c030r35_land_20260910/nav'
font = FontProperties(family=['DejaVu Sans', 'Droid Sans Fallback'])
plt.rcParams.update({'font.family': ['DejaVu Sans', 'Droid Sans Fallback'], 'axes.unicode_minus': False,
                     'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})


def series(path, column):
    with path.open(encoding='utf-8-sig') as f:
        return {r['date']:float(r[column]) for r in csv.DictReader(f)}


paths = [(series(REF/'BASE20111101.csv','net_equity'),'2011年起跑账户','#b13d45'),
         (series(REF/'BASE20091101.csv','net_equity'),'2009年起跑账户','#d28b36'),
         (series(ROOT/'data/raw/ohlcv/INDEX_000300.csv','close'),'沪深300价格指数','#317988')]
fig, axes = plt.subplots(1,3,figsize=(14,4.7))
periods = [('2024-05-29','2024-09-11','2024：少数重仓股主导亏损'),
           ('2021-09-22','2021-11-16','2021：指数上涨，账户深跌'),
           ('2015-04-27','2016-06-13','2015—2016：系统性下跌')]
for ax,(start,end,title) in zip(axes,periods):
    for values,label,color in paths:
        days = sorted(d for d in values if start<=d<=end)
        ys = [values[d]/values[start]-1 for d in days]
        ax.plot([date.fromisoformat(d) for d in days],ys,label=label,color=color,lw=1.8)
        offset = (7 if label.startswith('2011') else -10) if start.startswith('2015') and not label.startswith('沪深') else -3
        ax.annotate(f'{ys[-1]:+.1%}',(date.fromisoformat(end),ys[-1]),
                    xytext=(4,offset),textcoords='offset points',color=color,fontsize=9)
    ax.set_title(title,loc='left',pad=13,fontproperties=font,fontsize=12)
    ax.axhline(0,color='#999999',lw=.7)
    ax.grid(axis='y',alpha=.17)
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    locator=mdates.AutoDateLocator(minticks=3,maxticks=4)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set_ylim(-.52,.20)
    ax.margins(x=.14)
axes[0].set_ylabel('相对同一峰日的累计收益',fontproperties=font)
fig.legend(*axes[0].get_legend_handles_labels(),loc='upper center',ncol=3,
           bbox_to_anchor=(.5,.97),frameon=False,prop=font)
fig.text(.05,.025,'当前 C030R35 基准；账户净收益含融资；指数为价格收益。区间事后用于归因，不是交易信号。',fontproperties=font,color='#555555',fontsize=10)
fig.subplots_adjust(left=.065,right=.975,bottom=.16,top=.79,wspace=.27)
fig.savefig(EXP/'drawdown_comparison.png',dpi=170,facecolor='white')
plt.close(fig)

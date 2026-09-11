"""Paired return/drawdown trade-off; no selection or fitting."""
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parent/'raw/mpl-cache'))
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from common import EXP, read

plt.rcParams.update({'font.family':['DejaVu Sans','Droid Sans Fallback'],
    'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False,'font.size':10})
rows=[r for r in read(EXP/'decisions.csv') if r['bp']=='0']
fig,axes=plt.subplots(1,2,figsize=(11,5.3))
for ax,group,title in zip(axes,('full','A'),('全样本','剔除基准前五赢家A')):
    for r in rows:
        name=r['arm'];x=float(r[f'cagr_{group}'])*100;y=-float(r[f'mdd_{group}'])*100
        color=('#38816e' if name.startswith('P') else '#c77b32' if name.startswith('V') else '#6c7f90')
        if name=='P24V30':color='#865d9d'
        ax.scatter(x,y,c=color,s=38,zorder=3)
        offsets={'full':{'P24V30':(-57,-20),'V30':(7,-6),'V30F080':(-55,-16)},
                 'A':{'V25':(-26,-16),'P24V30':(-62,-24)}}
        offset=offsets.get(group,{}).get(name,(4,4))
        ax.annotate(name,(x,y),xytext=offset,textcoords='offset points',fontsize=8,color=color,
                    arrowprops=dict(arrowstyle='-',color=color,lw=.6) if offset!=(4,4) else None)
    ax.scatter(0,0,c='#333333',marker='x',s=40);ax.annotate('BASE',(0,0),xytext=(4,6),textcoords='offset points')
    ax.axvline(0,color='#999999',lw=.7);ax.axhline(0,color='#999999',lw=.7)
    ax.grid(alpha=.15);ax.margins(.2,.15)
    ax.set_title(title,loc='left',fontsize=13,pad=12)
    ax.set_xlabel('年化收益配对差（百分点）')
axes[0].set_ylabel('最大回撤改善（百分点，越高越浅）')
fig.text(.07,.04,'每点为14起点配对差中位；P=压力预算，V=波动预算，F=固定仓位上限。历史结果，不是收益预测。',color='#555555',fontsize=9)
fig.subplots_adjust(left=.08,right=.975,bottom=.20,top=.90,wspace=.24)
fig.savefig(EXP/'risk_return_tradeoff.png',dpi=170,facecolor='white')
plt.close(fig)

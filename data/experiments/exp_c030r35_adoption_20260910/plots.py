"""Export the fixed grid and robustness comparisons for review."""
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/raykey_c030r35_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from common import EXP, read


def export(fig,name):
    fig.savefig(EXP/f'{name}.png',dpi=170)
    path=EXP/f'{name}.svg';fig.savefig(path)
    path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')
    plt.close(fig)


def main():
    rows=read(EXP/'decisions.csv');by={r['arm']:r for r in rows}
    label=lambda c,r:'C030R35' if c==30 and r==350 else f'N{c:03}R{r}'
    fig,axes=plt.subplots(1,4,figsize=(14,4),layout='constrained')
    keys=('full_cagr_delta_pp','A_cagr_delta_pp','full_mdd_delta_pp','A_mdd_delta_pp')
    for ax,key,title in zip(axes,keys,('Full: CAGR change','Excluding A: CAGR change','Full: MDD change','Excluding A: MDD change')):
        data=np.array([[float(by[label(c,r)][key]) for r in (300,325,350,375,400)] for c in (20,25,30,35,40)])
        limit=max(abs(data.min()),abs(data.max()),.2)
        ax.imshow(data,cmap='RdBu_r' if 'mdd' in key else 'RdBu',vmin=-limit,vmax=limit)
        for i,c in enumerate((20,25,30,35,40)):
            for j,r in enumerate((300,325,350,375,400)):
                row=by[label(c,r)];mark='*' if row['verdict'].startswith('可采纳') else ''
                ax.text(j,i,f'{data[i,j]:+.1f}{mark}',ha='center',va='center',fontsize=9,
                        color='white' if abs(data[i,j])>limit*.58 else '#222')
        ax.add_patch(plt.Rectangle((1.5,1.5),1,1,fill=False,edgecolor='#e6ad20',linewidth=2.5))
        ax.set_xticks(range(5),('3','3.25','3.5','3.75','4'));ax.set_yticks(range(5),('20%','25%','30%','35%','40%'))
        ax.set_xlabel('Recovery spread (pp)');ax.set_title(title+' (pp)',fontsize=10)
    axes[0].set_ylabel('Restricted stock exposure cap')
    fig.suptitle('Fixed BASE comparisons; * passes section 2; gold = selected candidate. Negative MDD is shallower.',fontsize=11)
    export(fig,'parameter_neighbors')
    doses=read(EXP/'winner_doses.csv');costs=[r for r in read(EXP/'slippage.csv') if r['group']=='full']
    fig,axes=plt.subplots(2,3,figsize=(12,6.2),layout='constrained')
    for row,metric in enumerate(('cagr','mdd')):
        ax=axes[row,0];x=[int(r['K']) for r in doses]
        ax.plot(x,[float(r[metric+'_delta_pp']) for r in doses],marker='o',label='Matched K exclusions')
        ax.set_xticks(x);ax.set_xlabel('Number of top BASE winners removed')
        ax=axes[row,1];ms=list(range(10,21))
        for g,color,labeltext in (('full','#2166ac','Full'),('A','#a04e09','Excluding A')):
            ax.plot([m/100 for m in ms],[float(by['C030R35' if m==15 else f'CM{m}'][g+'_'+metric+'_delta_pp']) for m in ms],
                    marker='o',color=color,label=labeltext)
        ax.axvline(.15,color='#777',linestyle=':');ax.set_xlabel('Swap margin (reference: fixed BASE 0.15)')
        ax=axes[row,2]
        for g,color,labeltext in (('full','#2166ac','Full'),('A','#a04e09','Excluding A')):
            series=[r for r in read(EXP/'slippage.csv') if r['group']==g]
            ax.plot([int(r['slippage_bp']) for r in series],[float(r['candidate_'+metric+'_delta_pp']) for r in series],
                    marker='o',color=color,label=labeltext)
        ax.set_xlabel('Slippage per side (bp; same-cost reference)');ax.set_xticks((0,10,20,30))
        for ax in axes[row]:
            ax.axhline(0,color='#777',linewidth=.8);ax.grid(alpha=.18)
            if row==0:ax.axhspan(-.15,.15,color='#888',alpha=.12)
            else:ax.axhline(-5,color='#777',linestyle=':',linewidth=.8)
    axes[0,0].set_ylabel('CAGR paired change (pp)');axes[1,0].set_ylabel('MDD paired change (pp; negative is better)')
    axes[0,1].legend(frameon=False);fig.suptitle('C030R35: winner, execution-parameter and cost sensitivity',fontsize=12)
    export(fig,'robustness')
    print('PLOTS COMPLETE')


if __name__=='__main__':main()

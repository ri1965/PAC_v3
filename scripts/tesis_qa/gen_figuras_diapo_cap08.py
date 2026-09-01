import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams

NAVY='#0F2E4E'; ORANGE='#EB8734'; GREY='#5F6770'; INK='#1E252D'
rcParams.update({'font.family':'Carlito','font.size':11,'text.color':INK,
                 'axes.labelcolor':INK,'xtick.color':INK,'ytick.color':INK,
                 'axes.edgecolor':'#C9D2DA','figure.facecolor':'white','axes.facecolor':'white'})

MIN=[2,5,10,15]
auc=[0.838,0.821,0.783,0.763]
ppv=[0.096,0.203,0.298,0.354]
ap =[0.203,0.326,0.396,0.449]
prev=[0.0374,0.0804,0.1388,0.1889]
FS=(6.55,3.35); DPI=300

def base(ax):
    ax.axvspan(4.3,5.7,color=ORANGE,alpha=.13,zorder=0)
    ax.annotate('H = 5 min',(5,.995),ha='center',va='top',fontsize=11,
                color='#B4611B',fontweight='bold')
    ax.axvline(1.5,color=GREY,ls='--',lw=1.1,alpha=.8)
    ax.annotate('ramp-up ≈ 90 s',(1.72,.60),fontsize=9.5,color=GREY,ha='left',va='center')
    ax.set_xlabel('Anticipación (minutos antes del evento)',fontsize=11.5)
    ax.set_xticks(MIN); ax.set_xticklabels([f'{m} min' for m in MIN],fontsize=11)
    ax.set_xlim(1.15,16.4); ax.set_ylim(0,1.02)
    ax.set_yticks([0,.2,.4,.6,.8,1.0])
    ax.set_yticklabels(['0','0,2','0,4','0,6','0,8','1,0']); ax.tick_params(labelsize=10.5)
    ax.grid(axis='y',alpha=.28,lw=.8); ax.set_axisbelow(True)
    for sp in ('top','right'): ax.spines[sp].set_visible(False)

# ---------- V1: AUC vs PPV ----------
fig,ax=plt.subplots(figsize=FS,dpi=DPI); base(ax)
ax.plot(MIN,auc,'o-',color=NAVY,lw=3,ms=9,zorder=5)
ax.plot(MIN,ppv,'s-',color=ORANGE,lw=3,ms=9,zorder=5)
ax.annotate('Discriminación (AUC)',(2,auc[0]),xytext=(0,13),textcoords='offset points',
            color=NAVY,fontsize=11.5,fontweight='bold')
ax.annotate('Precisión de la alarma (PPV)',(15,ppv[-1]),xytext=(0,13),textcoords='offset points',
            color='#B4611B',fontsize=11.5,fontweight='bold',ha='right')
for x,v in zip(MIN,auc): ax.annotate(f'{v:.3f}'.replace('.',','),(x,v),xytext=(0,-17),
                textcoords='offset points',ha='center',fontsize=10,color=NAVY)
for x,v in zip(MIN,ppv): ax.annotate(f'{v*100:.1f} %'.replace('.',','),(x,v),xytext=(0,-17),
                textcoords='offset points',ha='center',fontsize=10,color='#B4611B')
fig.tight_layout(pad=.6); fig.savefig('slide_fig_V1_auc_vs_ppv.png',dpi=DPI); plt.close(fig)

# ---------- V2: AUC + AP + prevalencia ----------
fig,ax=plt.subplots(figsize=FS,dpi=DPI); base(ax)
ax.plot(MIN,auc,'o-',color=NAVY,lw=3,ms=9,zorder=5,label='Discriminación (AUC)')
ax.fill_between(MIN,prev,ap,color=ORANGE,alpha=.13,zorder=1)
ax.plot(MIN,ap,'s--',color=ORANGE,lw=2.6,ms=8,zorder=5,label='Precisión media (AP)')
ax.plot(MIN,prev,'^:',color=GREY,lw=1.6,ms=7,zorder=4,label='Prevalencia (basal del AP)')
for x,a,p in zip(MIN,ap,prev):
    ax.annotate(f'{a/p:.1f}×'.replace('.',','),(x,(a+p)/2),ha='center',va='center',
                fontsize=10,color='#B4611B',fontweight='bold',zorder=6)
ax.legend(fontsize=10,loc='center right',frameon=False)
fig.tight_layout(pad=.6); fig.savefig('slide_fig_V2_auc_ap_prev.png',dpi=DPI); plt.close(fig)
print('ok')

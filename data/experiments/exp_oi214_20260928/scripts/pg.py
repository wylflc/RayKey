"""pg.py TXTNAME PATTERN [context] -> print matches with page number"""
import re, sys
OUT='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214/txt/'
name,pat=sys.argv[1],re.compile(sys.argv[2]); ctx=int(sys.argv[3]) if len(sys.argv)>3 else 1
lines=open(OUT+name.replace('.PDF','').replace('.txt','')+'.txt',encoding='utf-8').read().split('\n')
page=0
pages=[]
for l in lines:
    m=re.match(r'=== PAGE (\d+) ===',l)
    if m: page=int(m.group(1))
    pages.append(page)
for i,l in enumerate(lines):
    if pat.search(l):
        print(f'p{pages[i]} L{i}: '+' | '.join(x.strip() for x in lines[i:i+1+ctx]))

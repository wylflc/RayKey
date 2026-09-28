import os, sys, warnings, logging
logging.disable(logging.CRITICAL)
warnings.filterwarnings('ignore')
from pypdf import PdfReader
OUT='/gpfs/scratch1/nodespecific/tcn441/zwang.27284302/claude-66633/-gpfs-scratch1-shared-zwang-mm-quant-RayKey/be4702a1-b00c-45e2-9cec-3beb6af4945d/scratchpad/oi214'
files=sys.argv[1:] or sorted(os.listdir(os.path.join(OUT,'pdfs')))
for f in files:
    f=os.path.basename(f)
    src=os.path.join(OUT,'pdfs',f); dst=os.path.join(OUT,'txt',f.rsplit('.',1)[0]+'.txt')
    if os.path.exists(dst): continue
    try:
        r=PdfReader(src)
        parts=[]
        for i,p in enumerate(r.pages):
            try: t=p.extract_text() or ''
            except Exception as e: t='[extract error %s]'%e
            parts.append('\n=== PAGE %d ===\n'%(i+1)+t)
        txt=''.join(parts)
        open(dst,'w',encoding='utf-8').write(txt)
        print(f, len(r.pages), len(txt.replace(' ','').replace('\n','')))
    except Exception as e:
        print(f,'ERROR',e)

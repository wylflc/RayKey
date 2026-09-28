"""Extract page-tagged text from PDFs with pypdf: <pdf> -> <pdf>.txt with '=== PAGE n ===' markers."""
import sys
from pathlib import Path
from pypdf import PdfReader

for p in sys.argv[1:]:
    out = Path(p).with_suffix('.txt')
    if out.exists() and out.stat().st_size > 0:
        continue
    r = PdfReader(p)
    with out.open('w', encoding='utf-8') as fh:
        for i, page in enumerate(r.pages, 1):
            try:
                t = page.extract_text() or ''
            except Exception as e:  # noqa: BLE001
                t = f'<<extract error {e}>>'
            fh.write(f'\n=== PAGE {i} ===\n{t}\n')
    print(p, len(r.pages))

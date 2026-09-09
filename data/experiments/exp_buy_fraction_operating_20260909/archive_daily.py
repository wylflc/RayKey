"""Store daily audit evidence in deterministic gzip files; keep CSVs as ignored local outputs."""
import gzip
from pathlib import Path
import shutil

EXP = Path(__file__).resolve().parent

if __name__ == '__main__':
    for source in EXP.glob('daily_selection_*.csv'):
        with source.open('rb') as src, source.with_suffix('.csv.gz').open('wb') as raw:
            with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as dest:
                shutil.copyfileobj(src, dest)

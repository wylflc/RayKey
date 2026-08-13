"""补齐池内股票的近端前复权日线（本地库止于 2026-08-07，需要到今日收盘）。

只用公开行情接口，不涉及任何凭据。前复权口径与 MA 计算一致（序列末端即今日实际价）。
"""
import csv, json, sys, urllib.request, collections
from concurrent.futures import ThreadPoolExecutor

ROOT = "/Users/yaleiwang/WorkSpace/AgentLab/RayKey"
OUT = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 90


def sym(code):
    return ("sh" if code[0]=="6" else ("bj" if code[0] in "489" or code[:2] in ("43","83","87","92") else "sz")) + code


def one(code):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param={sym(code)},day,,,{N},qfq")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        d = j["data"][sym(code)]
        rows = d.get("qfqday") or d.get("day") or []
        return code, [(x[0], float(x[2])) for x in rows if len(x) >= 3]
    except Exception as e:
        return code, []


codes = [r["security_code"] for r in
         csv.DictReader(open(f"{ROOT}/data/processed/a_share_core_valuation_pool.csv", encoding="utf-8"))]
got = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for c, rows in ex.map(one, codes):
        got[c] = rows

ok = [c for c in codes if len(got[c]) >= 60]
print(f"池内 {len(codes)} 只｜取到 ≥60 根日线 {len(ok)} 只｜不足或失败 {len(codes)-len(ok)} 只")
bad = [c for c in codes if len(got[c]) < 60]
if bad:
    print("  不足的：" + "｜".join(f"{c}({len(got[c])})" for c in bad[:20]))
last = collections.Counter(rows[-1][0] for rows in got.values() if rows)
print("  末根日期分布：" + "｜".join(f"{k} {v}" for k, v in last.most_common(4)))
with open(OUT, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["security_code", "date", "close"])
    for c in codes:
        for d, p in got[c]:
            w.writerow([c, d, f"{p:.4f}"])
print(f"已写 {OUT}")

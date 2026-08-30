"""三方对照：Sonnet 轮 / 知情复判轮(Opus) / 双盲轮(Opus)。"""
import json, os, collections, statistics

SP = "/private/tmp/claude-501/-Users-yaleiwang-WorkSpace-AgentLab-RayKey/7e66e4f4-dcf4-4587-8d6f-1fcb7a269702/scratchpad"
BATCHES = ["CA1","CA2","CB1","CB2","CB3","CB4","DA1","DB1","DB2"]

def load(fmt):
    out = {}
    for b in BATCHES:
        f = fmt % b
        if not os.path.exists(f):
            continue
        for line in open(f, encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                out[str(d["security_code"]).zfill(6)] = d
    return out

S = load(f"{SP}/oi036/out_%s.jsonl")       # Sonnet
I = load(f"{SP}/oi036/out2_%s.jsonl")      # informed Opus
B = load(f"{SP}/blind_out/%s.jsonl")       # blind Opus
missing = [b for b in BATCHES if not os.path.exists(f"{SP}/blind_out/{b}.jsonl")]
print(f"Sonnet {len(S)} / 知情 {len(I)} / 双盲 {len(B)}   未回批次: {missing or '无'}")
codes = sorted(set(S) & set(I) & set(B))
if not codes:
    raise SystemExit("双盲轮尚无可比数据")
print(f"三方可比 {len(codes)} 家\n")

def cls(d, c): return d[c]["attention_class"]
def sc(d, c):
    try: return int(d[c].get("reference_score") or 0)
    except (TypeError, ValueError): return 0

print("== 类别 ==")
tri = collections.Counter((cls(S,c), cls(I,c), cls(B,c)) for c in codes)
for k, v in tri.most_common():
    print(f"   Sonnet {k[0]} / 知情 {k[1]} / 双盲 {k[2]} : {v}")
disagree = [c for c in codes if len({cls(S,c), cls(I,c), cls(B,c)}) > 1]
print(f"   三方类别不一致: {len(disagree)} 家 {[(c, B[c]['security_name']) for c in disagree][:10]}\n")

print("== 参考分 ==")
for name, (x, y) in (("双盲 vs Sonnet", (S, B)), ("双盲 vs 知情", (I, B)), ("知情 vs Sonnet", (S, I))):
    d = [sc(y,c) - sc(x,c) for c in codes]
    same = sum(1 for v in d if v == 0)
    print(f"   {name:<16s} 中位 {statistics.median(d):+.0f}  均值 {statistics.mean(d):+.1f}  "
          f"|Δ|≥10 {sum(1 for v in d if abs(v)>=10):>3}  完全相同 {same:>3}  "
          f"平均绝对差 {statistics.mean(abs(v) for v in d):.1f}")

print("\n== 双盲轮与知情轮分歧最大的 15 家 ==")
gap = sorted(codes, key=lambda c: -abs(sc(B,c) - sc(I,c)))[:15]
for c in gap:
    print(f"   {c} {B[c]['security_name']:<10s} Sonnet {sc(S,c):>3} → 知情 {sc(I,c):>3} → 双盲 {sc(B,c):>3}"
          f"   ({sc(B,c)-sc(I,c):+d} vs 知情)")

print("\n== 排队层建议一致性 ==")
q = collections.Counter()
for c in codes:
    q[(I[c].get("queue_tier_suggest",""), B[c].get("queue_tier_suggest",""))] += 1
agree = sum(v for k, v in q.items() if k[0] == k[1])
print(f"   知情/双盲一致 {agree}/{len(codes)} ({agree/len(codes)*100:.0f}%)")
for k, v in q.most_common(6):
    if k[0] != k[1]: print(f"     知情 {k[0]} vs 双盲 {k[1]}: {v}")

print("\n== 判语与置信 ==")
for name, d in (("Sonnet", S), ("知情 Opus", I), ("双盲 Opus", B)):
    ns = [len(d[c].get("moat_note") or "") for c in codes]
    lo = sum(1 for c in codes if d[c].get("confidence") == "low")
    print(f"   {name:<10s} 判语中位 {statistics.median(ns):>4.0f} 字   low 置信 {lo:>3}   "
          f"rule 与 Sonnet 同前缀 {sum(1 for c in codes if (d[c].get('rule') or '')[:3] == (S[c].get('rule') or '')[:3]):>3}")

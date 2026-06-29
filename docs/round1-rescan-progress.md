# A-Share Round-1 Full Rescan — Progress & Handoff

Round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`) over the full A-share universe under the ADR-0006 standard. Model judgment, batched, resumable. This note is a snapshot plus handoff; the **live source of truth is the data files**, not this snapshot.

## Source of truth (live)

- **Standard:** `docs/000_Ashare_workflow.md` §5.4 — 5.4.1 总体原则 / 5.4.2 三类定义 / 5.4.3 garbage 条件 / 5.4.4 输出字段 / 5.4.5 行业校准锚（规则 1-9）/ 5.4.6 执行流程; and `docs/adr/0006-round-1-three-class-triage-standard.md`.
- **Worked calibration examples:** `docs/peer-group-calibration/a-share-baijiu.md` §1.10, `a-share-display-devices.md` §1.5, `a-share-decoration-construction.md` §1.5.
- **Worklist:** `data/interim/a_share_full_rescan_queue.csv` (priority-ordered, full universe).
- **Output (this round):** `data/processed/a_share_attention_triage.csv` (§5.4.4 fields).
- **Audit:** `data/processed/a_share_workflow_decision_log.csv` (`workflow_stage = attention_triage`).

## Snapshot (as of 2026-06-29)

| Class | Done |
| --- | ---: |
| worth_attention | 53 |
| boundary_pending | 150 |
| garbage | 16 (governance_fraud 2 / structural_industry 14) |
| **Total triaged** | **219 / 5653** |

Remaining: `1_worth_attention` (prior worth_attention) **1058** · `2_ex_l5_boundary` **421** · `3_unreviewed` **3955**.

Batches done: 3 industry-calibration batches (baijiu 21, panel 8, decoration 15) + 7 priority-1 batches (175). Cadence 25/batch.

### Current worth_attention pool (53)

- **品牌消费:** 贵州茅台·五粮液·山西汾酒·泸州老窖·洋河股份(白酒) · 东阿阿胶·云南白药·华润三九(中药/OTC) · 美的集团·格力电器·苏泊尔(家电/炊具) · 双汇发展(肉制品)
- **垄断/稀缺资源:** 藏格矿业·盐湖股份(盐湖钾锂) · 锡业股份(全球锡)
- **军工高壁垒电子:** 振华科技·航天电器·中航光电(器件/连接器) · 紫光国微(军工FPGA)
- **AI/半导体/高端电子:** 沃尔核材(高速铜连接) · 顺络电子(高端电感) · 通富微电(先进封装) · 福晶科技(光学晶体) · 光迅科技(光器件/光芯片) · 科大讯飞(AI语音/政教AI)
- **软件/硬件生态:** 大华股份(安防AIoT) · 石基信息(酒店信息系统) · 奔图科技(国产打印生态)
- **科技/装备龙头:** 中兴通讯·紫光股份(新华三) · 大族激光 · 三花智控(全球热管理) · 汉钟精机(压缩机/真空泵) · 华明装备(分接开关) · 水晶光电(精密光学) · 科华数据(AIDC电源/UPS) · 奥普光电(军工光电)
- **资本周期龙头(规则6):** 京东方A·TCL科技(面板) · 中联重科·徐工机械·潍柴动力·中国重汽(机械/重卡)
- **金融:** 宁波银行
- **医药/生物:** 长春高新(金赛) · 华兰生物(浆站) · 上海莱士(血液制品) · 恩华药业(CNS/麻醉精神药) · 鱼跃医疗(家用医疗器械) · 隆平高科(种业/转基因)
- **农牧服务:** 海大集团(饲料/养殖服务平台)
- **化工寡头:** 新和成(维生素)
- **平台网络:** 分众传媒(电梯广告点位网络)

## How to resume (for Codex)

Follow `docs/000_Ashare_workflow.md` §5.4.6. Per batch: take the next 25 un-triaged companies from the queue by priority order, judge each **independently** under §5.4 + the §5.4.5 anchors (light triage — business model + durable hard-to-replicate moat + obvious negatives; insufficient evidence + no clear negative → `boundary_pending`), append to the triage CSV, append one batch row to the decision log, and commit with a one-sentence message.

Recompute live progress / get the next batch:

```python
import csv, collections
tri=list(csv.DictReader(open("data/processed/a_share_attention_triage.csv",encoding="utf-8-sig")))
done={r["security_code"].zfill(6) for r in tri}
print(collections.Counter(r["attention_class"] for r in tri), "done", len(done))
q=list(csv.DictReader(open("data/interim/a_share_full_rescan_queue.csv",encoding="utf-8-sig")))
nxt=[r for r in q if r["security_code"].zfill(6) not in done][:25]  # priority-ordered
```

## Handoff notes

1. `worth_attention` is **model judgment, not a threshold script** (ADR-0004/0006).
2. Priority order: re-judge prior worth_attention first, then the 421 ex-L5 (temporarily reclassified to boundary), then the unreviewed.
3. `garbage` rows that carry `需核验` in `evidence_basis` rest on documented fraud/governance history — confirm against filings before freezing.
4. After the whole universe is triaged, run **L1–L5 tiering (§5.7/§5.8) on the worth_attention set only** (stage 1, step 2).
5. Established calibration anchors (§5.4.5): brand-moat must be proven through a downcycle (baijiu); capex-cyclical with irreversible structural consolidation → worth_attention (panel, rule 6); structural_industry garbage applies even to the relative leader (decoration, rule 8); infrastructure monopoly with regulated returns → boundary (rule 9).

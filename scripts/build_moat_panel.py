#!/usr/bin/env python3
"""装配回测宇宙面板 v6（§12.71：对齐 §5.4 全口径的逐年判定）。

落实 §12.51.4 方向③「明确选择规则并使之可复现」：面板不再是一次性手工装配，
而是 基座(v5) + 判定覆盖(verdicts_pit_moat_v6.csv) 的确定性产物。

规则
----
1. **基座 = v5 面板**：未被 v6 判定触及的代码，逐行原样保留（重叠 81 只与维持出场的历史成员）。
2. **判定覆盖**（`verdicts_pit_moat_v6.csv`，列 code,name,worth_from,worth_to,rule,reason；
   reason 内可含英文逗号，解析时 `','.join(row[5:])`）：
   - `worth_from=0` → 该代码整体除名（v5 有也删）；
   - 区间行 → **替换**该代码在 v5 的全部区间；同一代码可多行（如盐湖 2004-2015 与 2021-）。
3. **区间 → 生效窗**：进场证据年 Y → `effective_from = (Y+1)-04-30`（年报可得约定，与 v5 同构）；
   出场年 E → `effective_to = (E+1)-04-30`；`worth_to=9999` → 开放（空串）。
   每个区间一行（回测按区间覆盖读取，与 v5 的逐年多行语义等价）。
4. **银行子册**：银行行判定不经 verdicts（§12.71.2）。v6b = v5 全部银行行原样（含 X3 退出/重入）；
   v6a = 仅规则 11 判例两家（招商银行 600036、宁波银行 002142）。
   银行识别 = 名含「银行/农商」或显式补充名单（张家港行）。

用法::

    python3 scripts/build_moat_panel.py            # 产出 v6a + v6b 并打印对账
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / "data/processed/pit_attention"
V5 = PIT / "panel_moat_bank_v5.csv"
VERDICTS = PIT / "verdicts_pit_moat_v6.csv"
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
TODAY = "2026-08-16"

BANK_EXTRA = {"002839"}  # 张家港行：名字不含「银行」，显式补充
RULE11_BANKS = {"600036", "002142"}


def is_bank(code: str, name: str) -> bool:
    return "银行" in name or "农商" in name or code in BANK_EXTRA


def main() -> int:
    v5_rows: dict[str, list[dict]] = defaultdict(list)
    fields: list[str] = []
    with V5.open(encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        fields = list(rd.fieldnames or [])
        for r in rd:
            v5_rows[r["security_code"].zfill(6)].append(r)

    drops: set[str] = set()
    intervals: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    names: dict[str, str] = {}
    with VERDICTS.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd)
        for row in rd:
            code = row[0].zfill(6)
            names[code] = row[1]
            wf, wt = row[2], row[3]
            if wf == "0":
                drops.add(code)
            else:
                intervals[code].append((int(wf), int(wt), row[1]))
    overlap = drops & set(intervals)
    if overlap:
        raise SystemExit(f"判定冲突：既除名又给区间 {sorted(overlap)}")

    def interval_rows(code: str, ivs: list[tuple[int, int, str]]) -> list[dict]:
        out = []
        for wf, wt, name in sorted(ivs):
            row = {k: "" for k in fields}
            row.update({
                "effective_from": f"{wf + 1}-04-30",
                "effective_to": "" if wt == 9999 else f"{wt + 1}-04-30",
                "screen_year": str(wf + 1),
                "security_code": code,
                "security_name": name,
            })
            out.append(row)
        return out

    banks: dict[str, list[dict]] = {}
    nonbank_base: dict[str, list[dict]] = {}
    for code, rows in v5_rows.items():
        name = rows[0]["security_name"]
        (banks if is_bank(code, name) else nonbank_base)[code] = rows

    final_nonbank: dict[str, list[dict]] = {}
    for code, rows in nonbank_base.items():
        if code in drops:
            continue
        final_nonbank[code] = interval_rows(code, intervals[code]) if code in intervals else rows
    for code, ivs in intervals.items():
        if code not in final_nonbank and code not in banks:
            final_nonbank[code] = interval_rows(code, ivs)

    def write(path: Path, bank_codes: set[str]) -> tuple[int, set[str]]:
        rows_out: list[dict] = []
        for code in sorted(final_nonbank):
            rows_out.extend(final_nonbank[code])
        for code in sorted(bank_codes):
            rows_out.extend(banks[code])
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows_out)
        active = {r["security_code"].zfill(6) for r in rows_out
                  if r["effective_from"] <= TODAY <= (r["effective_to"] or "9999-12-31")}
        return len(rows_out), active

    n_b, act_b = write(PIT / "panel_moat_bank_v6b.csv", set(banks))
    n_a, act_a = write(PIT / "panel_moat_bank_v6a.csv", set(banks) & RULE11_BANKS)

    pool = {}
    with POOL.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("market_type") == "A_SHARE":
                pool[r["security_code"].zfill(6)] = r["security_name"]

    all_names = {c: rows[0]["security_name"] for c, rows in v5_rows.items()}
    all_names.update(names)
    miss = sorted(pool.keys() - act_b)
    extra = sorted(act_b - pool.keys())
    extra_bank = [c for c in extra if c in banks]
    extra_flag = [c for c in extra if c not in banks]
    print(f"v6b：{n_b} 行｜代码 {len(final_nonbank) + len(banks)}｜今日在场 {len(act_b)}")
    print(f"v6a：{n_a} 行｜今日在场 {len(act_a)}")
    print(f"对账 vs 实盘池 {len(pool)}：池内缺席 {len(miss)}｜面板多出 非银 {len(extra_flag)} + 银行 {len(extra_bank)}")
    if miss:
        print("  池内缺席（应为空，否则 Q1 有漏判）：" + "、".join(pool[c] for c in miss))
    if extra_flag:
        print("  多出的非银（应全部=实盘池候选旗标）：" + "、".join(all_names.get(c, c) for c in extra_flag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

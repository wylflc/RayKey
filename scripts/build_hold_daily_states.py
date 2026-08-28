#!/usr/bin/env python3
"""持仓侧逐日状态（§6.7 第 3 步）：逐 (代码, 日期) 取候选侧与 B2 两份采纳逐日状态中 `intrinsic_value` 较高的那一行。

§9.3.1 的减持线、换仓来源、簇内升级与 T+1 换仓确认按持仓侧 P/V 判（回测 `--hold-states`），
候选侧（买入线、候选排序）仍读 `a_share_daily_states_adopted.csv`。

用法：
    python3 scripts/build_hold_daily_states.py \
        --base data/processed/a_share_daily_states_adopted.csv \
        --b2   data/processed/a_share_daily_states_b2.csv \
        --out  data/processed/a_share_daily_states_hold.csv

两份输入都按代码升序分块、块内按日期升序（建带器与银行覆盖脚本的写出顺序）；本脚本流式合并，
内存只驻留一只票的行（§ 机器资源约束：逐日级数据不得整份驻留）。顺序不满足或表头不同即硬失败。
只在一份里出现的 (代码, 日期) 行原样写出；两份都有时 V 大者胜、相等取候选侧。
输出列 = 输入列 + `hold_source`（base／b2）。结尾打印各类计数（§13 第 3 条）。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "data/processed/a_share_daily_states_adopted.csv"
DEFAULT_B2 = ROOT / "data/processed/a_share_daily_states_b2.csv"
DEFAULT_OUT = ROOT / "data/processed/a_share_daily_states_hold.csv"


class BlockReader:
    """按 `security_code` 连续块读取；块间代码须严格递增（一只票只能出现一个块）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = path.open(newline="", encoding="utf-8")
        self._reader = csv.reader(self._fh)
        self.header = next(self._reader, None)
        if not self.header:
            sys.exit(f"空文件：{path}")
        self.i_code = self.header.index("security_code")
        self._pending: list[str] | None = None
        self._last_code = ""
        self.rows = 0

    def next_block(self) -> tuple[str, list[list[str]]] | None:
        first = self._pending if self._pending is not None else next(self._reader, None)
        self._pending = None
        if first is None:
            return None
        code = first[self.i_code]
        if code <= self._last_code:
            sys.exit(f"{self.path.name}：代码块顺序非严格递增（{self._last_code} → {code}），不能流式合并")
        self._last_code = code
        block = [first]
        for row in self._reader:
            if row[self.i_code] != code:
                self._pending = row
                break
            block.append(row)
        self.rows += len(block)
        return code, block


def _iv(row: list[str], i_iv: int) -> float:
    try:
        return float(row[i_iv])
    except (TypeError, ValueError):
        return float("-inf")


def main() -> int:
    ap = argparse.ArgumentParser(description="持仓侧逐日状态 = 逐 (代码, 日期) 取两口径较高 V")
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE, help="候选侧采纳逐日状态")
    ap.add_argument("--b2", type=Path, default=DEFAULT_B2, help="B2（--ttm-trust on）采纳逐日状态")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    for p in (a.base, a.b2):
        if not p.exists():
            sys.exit(f"缺少输入：{p}（§6.7 第 3 步先生成两份采纳逐日状态）")
    A, B = BlockReader(a.base), BlockReader(a.b2)
    if A.header != B.header:
        sys.exit("两份逐日状态表头不同，不能合并")
    i_date, i_iv, i_close = A.header.index("date"), A.header.index("intrinsic_value"), A.header.index("close")

    n = {"base_only_rows": 0, "b2_only_rows": 0, "b2_wins": 0, "base_wins_or_tie": 0,
         "close_mismatch": 0, "codes_base_only": 0, "codes_b2_only": 0, "codes_both": 0}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(A.header + ["hold_source"])
        ba, bb = A.next_block(), B.next_block()
        while ba is not None or bb is not None:
            if bb is None or (ba is not None and ba[0] < bb[0]):
                for r in ba[1]:
                    w.writerow(r + ["base"])
                n["base_only_rows"] += len(ba[1]); n["codes_base_only"] += 1
                ba = A.next_block()
                continue
            if ba is None or bb[0] < ba[0]:
                for r in bb[1]:
                    w.writerow(r + ["b2"])
                n["b2_only_rows"] += len(bb[1]); n["codes_b2_only"] += 1
                bb = B.next_block()
                continue
            # 同一只票：按日期配对
            n["codes_both"] += 1
            b_by_date = {r[i_date]: r for r in bb[1]}
            seen: set[str] = set()
            merged: list[tuple[list[str], str]] = []
            for r in ba[1]:
                d = r[i_date]
                seen.add(d)
                rb = b_by_date.get(d)
                if rb is None:
                    merged.append((r, "base")); n["base_only_rows"] += 1
                    continue
                if rb[i_close] != r[i_close]:
                    n["close_mismatch"] += 1
                if _iv(rb, i_iv) > _iv(r, i_iv):
                    merged.append((rb, "b2")); n["b2_wins"] += 1
                else:
                    merged.append((r, "base")); n["base_wins_or_tie"] += 1
            extra = [(r, "b2") for r in bb[1] if r[i_date] not in seen]
            if extra:
                merged.extend(extra); n["b2_only_rows"] += len(extra)
                merged.sort(key=lambda t: t[0][i_date])
            for r, src in merged:
                w.writerow(r + [src])
            ba, bb = A.next_block(), B.next_block()
    tmp.replace(a.out)
    total = sum(n[k] for k in ("base_only_rows", "b2_only_rows", "b2_wins", "base_wins_or_tie"))
    print(f"持仓侧逐日状态 {total:,} 行 → {a.out}")
    print(f"  两侧都有的行：B2 更高 {n['b2_wins']:,}｜候选侧更高或相等 {n['base_wins_or_tie']:,}"
          f"｜只在候选侧 {n['base_only_rows']:,}｜只在 B2 {n['b2_only_rows']:,}")
    print(f"  票数：两侧都有 {n['codes_both']:,}｜只在候选侧 {n['codes_base_only']:,}｜只在 B2 {n['codes_b2_only']:,}"
          f"｜同日收盘不一致 {n['close_mismatch']:,} 行")
    if n["close_mismatch"]:
        print("  ⚠ 同一 (代码, 日期) 两侧收盘不同：两份状态不是同一批行情／除权输入，先查 §6.7 第 1-2 步再用", file=sys.stderr)
        return 1
    if total == 0:
        print("  ⚠ 输出 0 行", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""把面板里「入选早于证据可得日」的成员首段推迟到合法日，产出 v5 面板。

**查出的问题**：`verdicts_pit_moat_v2.csv` 的 `worth_from` 与
`verdicts_pit_moat_v3_restored.csv` 的 `evidence_year` **两种口径混用**——
- 一部分记录填的是「证据可得年」（药明康德 `worth_from=2019`，理由明写「2018年报可得日已成立」）；
- 一部分填的是「证据的最后财年」（贵州茅台 `evidence_year=2003`，理由引 2001-2003 读数，
  而 FY2003 年报要到 2004-04-30 才披露）。

后者被面板直接映射成 `{年}-04-30` 生效，于是**提前 12 个月在册**。
实测 170 只护城河成员里 15 只如此（14 只提前 1 年、三一重工提前 4 年）。

**修法**：以「理由文本里引用的最后年份 + 1」的年报季（04-30）为合法可入日，
把该股**首段**的 `effective_from` 推迟到该日；首段若因此整段落空则丢弃，后续档不动。
**只推迟、不提前**——本脚本不会让任何股票比原面板更早在册。

用法：
    python3 scripts/experimental/fix_panel_entry_lookahead.py \
        --panel data/processed/pit_attention/panel_moat_bank_v4.csv \
        --out   data/processed/pit_attention/panel_moat_bank_v5.csv
"""
import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIT = ROOT / "data/processed/pit_attention"
YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-2]\d)(?!\d)")


def legit_dates() -> dict[str, str]:
    """{代码: 合法可入日}——理由里引用的最后年份 +1 的年报披露季末。"""
    out: dict[str, str] = {}
    for name, key in (("verdicts_pit_moat_v2.csv", "worth_from"),
                      ("verdicts_pit_moat_v3_restored.csv", "evidence_year")):
        with (PIT / name).open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = r["security_code"].zfill(6)
                if r.get(key) in ("", "0", None) or code in out:
                    continue
                years = [int(m) for m in YEAR.findall(r.get("reason", ""))]
                if years:
                    out[code] = f"{max(years) + 1}-04-30"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", type=Path, default=PIT / "panel_moat_bank_v4.csv")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    legit = legit_dates()
    rows = list(csv.DictReader(a.panel.open(encoding="utf-8-sig")))
    first: dict[str, str] = {}
    for r in rows:
        c = r["security_code"].zfill(6)
        if c not in first or r["effective_from"] < first[c]:
            first[c] = r["effective_from"]

    moved, dropped, touched = 0, 0, set()
    out_rows = []
    for r in rows:
        c = r["security_code"].zfill(6)
        need = legit.get(c)
        # 只处理「该股原本的首次在册日早于合法日」的那些股票，且只推迟落在该窗口内的档
        if need and first[c] < need and r["effective_from"] < need:
            touched.add(c)
            end = (r.get("effective_to") or "").strip() or "9999-12-31"
            if end <= need:
                dropped += 1                     # 整段都在合法日之前 → 丢弃
                continue
            r = dict(r, effective_from=need)     # 段跨过合法日 → 起点推迟
            moved += 1
        out_rows.append(r)

    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    codes_in = len({r["security_code"].zfill(6) for r in out_rows})
    print(f"涉及 {len(touched)} 只｜整段丢弃 {dropped} 行｜起点推迟 {moved} 行"
          f"｜{len(rows):,} → {len(out_rows):,} 行、{len(first)} → {codes_in} 只 → {a.out}")


if __name__ == "__main__":
    main()

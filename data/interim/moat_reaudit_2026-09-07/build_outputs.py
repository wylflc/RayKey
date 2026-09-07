"""Render manually adjudicated review notes; never changes production pool decisions."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(name, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


notes = json.loads((HERE / "review_notes.json").read_text())
old_path = ROOT / "data/interim/moat_audit_2026-09-07/moat_audit_merged.csv"
old = {r["security_code"]: r for r in read_csv(old_path)}
archived = read_csv(ROOT / "data/archive/quality_tiers_migrated_2026-09-07.csv")
removed_codes = {r["security_code"] for r in archived}
triage_path = ROOT / "data/processed/a_share_attention_triage.csv"
triage = {r["security_code"]: r for r in read_csv(triage_path)}
retained = {c for c, r in triage.items() if r["attention_class"] == "worth_attention"}
sources = {r["source_id"]: r for r in read_csv(HERE / "sources.csv")}
decisions = read_csv(ROOT / "data/processed/a_share_workflow_decision_log.csv")
migration_ids = {}
for r in decisions:
    if r["security_code"] in removed_codes and r["as_of"] == "2026-09-07" and "boundary_pending" in r["decision_result"]:
        migration_ids[r["security_code"]] = r["decision_id"]

assert len(old) == 214 and len(removed_codes) == 37 and len(retained) == 177
assert removed_codes.isdisjoint(retained) and removed_codes | retained == set(old)
assert {r[0] for r in notes["removed"]} == removed_codes
assert len(notes["removed"]) == 37
assert all(triage[c]["attention_class"] == "boundary_pending" for c in removed_codes)
assert len(migration_ids) == 37


def expand(row):
    code, outcome, confidence, reason, trigger, ids = row
    assert all(s in sources for s in ids)
    return {
        "security_code": code,
        "security_name": triage[code]["security_name"],
        "current_attention_class": triage[code]["attention_class"],
        "review_outcome": outcome,
        "confidence": confidence,
        "review_reason": reason,
        "next_hard_evidence": trigger,
        "external_check_scope": "targeted_source_check" if ids else "prior_record_logic_only",
        "new_source_ids": ";".join(ids),
        "new_source_urls": ";".join(sources[s]["url"] for s in ids),
        "prior_verdict": old[code]["verdict"],
        "prior_reason_not_reverified": old[code]["reason"],
        "prior_sources_not_all_reopened": old[code]["sources"],
        "related_migration_decision_id": migration_ids.get(code, ""),
        "production_action": "none_recommendation_only",
    }


removed_rows = [expand(r) for r in notes["removed"]]
focus = {r[0]: r for r in notes["retained_focus"]}
assert set(focus) <= retained
retained_rows = []
for code in sorted(retained):
    if code in focus:
        retained_rows.append(expand(focus[code]))
    else:
        retained_rows.append(expand([
            code,
            "档案层面未发现新增移出依据",
            "not_rerated",
            "已检查原载体、财务摘要及移出规则的一致性；未逐项重新外部尽调。原事实和来源单列，不标记为本轮已验证。",
            "原载体被竞争、客户替换或经营证据证伪时复核",
            [],
        ]))
write_csv("removed_reviews.csv", removed_rows)
write_csv("retained_screen.csv", retained_rows)
summary = {
    "as_of": notes["as_of"],
    "scope": notes["purpose"],
    "previous_audit_rows": len(old),
    "actual_removed": len(removed_rows),
    "current_pool": len(retained_rows),
    "removed_outcomes": dict(Counter(r["review_outcome"] for r in removed_rows)),
    "retained_focus_count": len(focus),
    "new_sources_count": len(sources),
    "removed_with_targeted_external_check": sum(bool(r["new_source_ids"]) for r in removed_rows),
    "retained_with_targeted_external_check": sum(bool(r["new_source_ids"]) for r in retained_rows),
    "external_scope_warning": "Targeted claim checks, not a full fresh diligence of every company. S29 is an auxiliary lead and does not establish current drug approval status.",
    "source_snapshot_sha256": {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [old_path, triage_path, ROOT / "data/processed/a_share_core_valuation_pool.csv"]
    },
    "validation": "214 unique = 37 removed + 177 retained; 37 prior migration IDs linked; source references resolved; no production mutation",
}
(HERE / "coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "source_snapshot_sha256"}, ensure_ascii=False, indent=2))

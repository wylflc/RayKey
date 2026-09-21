"""Daily input provenance and all-or-fail publication; workflow §8/§9.1."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def stamp(path, as_of=None, inputs=()):
    """A successful writer proves even an empty CSV belongs to the requested day."""
    path = Path(path)
    value = dict(as_of=as_of or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
                 generated_at_utc=datetime.now(timezone.utc).isoformat(),
                 sha256=digest(path), inputs={str(Path(p).resolve()): digest(p) for p in inputs})
    atomic_json(path.with_suffix(path.suffix + '.meta.json'), value)


def verify_stamp(path, as_of):
    path = Path(path)
    meta = json.loads(path.with_suffix(path.suffix + '.meta.json').read_text())
    if meta['as_of'] != as_of or meta['sha256'] != digest(path):
        raise ValueError(f'文件日期或摘要不符：{path}')
    for p, expected in meta.get('inputs', {}).items():
        if digest(p) != expected:
            raise ValueError(f'上游输入已改变，须重建 {path}：{p}')
    return meta


def read_required(path, columns, allow_empty=False):
    path = Path(path)
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not set(columns) <= set(reader.fieldnames or ()):
            raise ValueError(f'缺必要列 {set(columns) - set(reader.fieldnames or ())}：{path}')
        rows = list(reader)
    if not rows and not allow_empty:
        raise ValueError(f'必需输入为空：{path}')
    seen = set()
    for row in rows:
        code = row.get('security_code')
        if code is not None:
            if not code.isdigit() or len(code) != 6 or code in seen:
                raise ValueError(f'代码为空、无效或重复：{path} {code}')
            seen.add(code)
    return rows


def validate_inputs(args):
    import screen_daily_volume_price_signals as s
    required = {
        args.input: (('security_code',), False),
        args.review_queue: (('security_code', 'buy_blocked', 'as_of'), True),
        args.tiers: (('security_code', 'quality_tier', 'tactical_thesis'), False),
        args.holdings: (('security_code', 'current_shares', 'cost_basis', 'entry_stop_price'), True),
        args.triage: (('security_code', 'attention_class'), False),
        args.model_bands: (('security_code', 'intrinsic_value', 'available_at'), False),
        args.hold_bands: (('security_code', 'intrinsic_value', 'available_at'), False),
    }
    rows = {p: read_required(p, *spec) for p, spec in required.items()}
    if args.symbols:
        raise ValueError('执行模式须扫描完整输入池；按代码预览不发布交易计划')
    if not math.isfinite(args.nav) or args.nav <= 0 or args.funds is None or not math.isfinite(args.funds):
        raise ValueError('执行模式需要当日有效 --nav 与 --funds')
    for row in rows[args.holdings]:
        shares = float(row['current_shares'])
        if not math.isfinite(shares) or shares < 0:
            raise ValueError('持仓股数无效')
        for key in ('cost_basis', 'entry_stop_price'):
            if row[key] and (not math.isfinite(float(row[key])) or float(row[key]) <= 0):
                raise ValueError(f'持仓 {key} 无效')
    for row in rows[args.review_queue]:
        if row['as_of'] != s.evidence_iso_for_signal(args.as_of):
            raise ValueError('复核队列不是信号日快照')
    verify_stamp(args.review_queue, args.as_of)
    triage = rows[args.triage]
    if any(r['attention_class'] not in {'worth_attention', 'boundary_pending', 'garbage', 'documented_not_attention'} for r in triage):
        raise ValueError('三类表含未知状态')
    members = {r['security_code'] for r in triage if r['attention_class'] == 'worth_attention'}
    tiers = {r['security_code']: r for r in rows[args.tiers]}
    pool_codes = {r['security_code'] for r in rows[args.input]}
    if any(c not in tiers or tiers[c]['quality_tier'] not in {'L1', 'L2', 'L3', 'L4'} for c in pool_codes & members):
        raise ValueError('名单内候选缺有效分层')
    proof = json.loads(args.evidence_proof.read_text())
    if proof.get('as_of') != args.as_of or proof.get('status') != 'complete':
        raise ValueError('缺同日证据阶段完成证明')
    for path, expected in proof['inputs'].items():
        if digest(path) != expected:
            raise ValueError(f'证据阶段后输入已改变：{path}')
    if not pool_codes <= set(proof.get('covered_codes', [])):
        raise ValueError('新增候选未被证据阶段覆盖，须重新同步证据')
    from backtest_valuation_strategy import ACTIONS, load_actions
    from apply_holdings_corporate_action import DEFAULT_LEDGER, load_ledger, ledger_index
    applied = ledger_index(load_ledger(DEFAULT_LEDGER))
    acts = load_actions()
    for h in rows[args.holdings]:
        if float(h['current_shares']) <= 0:
            continue
        code = h['security_code']
        if code not in proof.get('covered_codes', []):
            raise ValueError(f'持仓未被证据阶段覆盖：{code}')
        # The daily proof covers the gap since the prior successful scan.
        for day in acts.get(code, {}):
            if proof['since'] < day <= args.as_of and (code, day) not in applied:
                raise ValueError(f'公司行动尚未回写持仓：{code} {day}，先按 §11.4 处理')
    paths = set(required) | {args.evidence_proof, args.review_queue.with_suffix('.csv.meta.json'), ACTIONS}
    paths.update(Path(p) for p in proof['inputs'])
    if DEFAULT_LEDGER.exists():
        paths.add(DEFAULT_LEDGER)
    if args.cash is None or args.debt is None:
        s.account_cash_debt(args.as_of, args.cash, args.debt)
        paths.add(s.SEC93_ACCOUNT_SNAPSHOT)
    else:
        s.account_cash_debt(args.as_of, args.cash, args.debt)
    return {str(p.resolve()): digest(p) for p in paths}


class Publication:
    """Manifest is the commit record. Recover an interrupted run before reading state."""
    def __init__(self, status, as_of, outputs):
        self.status, self.as_of = Path(status), as_of
        self.outputs = [Path(p).resolve() for p in outputs]
        if len(set(self.outputs)) != len(self.outputs) or self.status.resolve() in self.outputs:
            raise ValueError('发布路径不能重复')
        self.committed = False
        self.installing = False

    def __enter__(self):
        self.status.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.status.with_suffix('.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = json.loads(self.status.read_text()) if self.status.exists() else {}
        if previous.get('status') == 'running' and previous.get('phase') == 'installing':
            self.restore(previous['backups'])
        self.directory = Path(tempfile.mkdtemp(prefix='.daily_publish_', dir=self.status.parent))
        self.backups = {}
        for i, path in enumerate(self.outputs):
            backup = self.directory / f'backup_{i}'
            if path.exists():
                shutil.copyfile(path, backup)
            self.backups[str(path)] = str(backup) if backup.exists() else None
        atomic_json(self.status, dict(status='running', phase='prepared', as_of=self.as_of, backups=self.backups))
        return self

    @staticmethod
    def restore(backups):
        for path, backup in backups.items():
            if backup is None:
                Path(path).unlink(missing_ok=True)
            else:
                shutil.copyfile(backup, path)

    def stage(self, path):
        target = self.directory / ('stage_' + str(self.outputs.index(Path(path).resolve())))
        if Path(path).exists() and not target.exists():
            shutil.copyfile(path, target)
        return target

    def publish(self, staged, inputs, before_commit=lambda: None):
        for path, expected in inputs.items():
            if digest(path) != expected:
                raise ValueError(f'运行期间输入变化，须重跑：{path}')
        for path, backup in self.backups.items():
            current = digest(path) if Path(path).exists() else None
            original = digest(backup) if backup else None
            if current != original:
                raise ValueError(f'运行期间输出被其他任务修改：{path}')
        atomic_json(self.status, dict(status='running', phase='installing', as_of=self.as_of, backups=self.backups))
        self.installing = True
        for target, source in staged.items():
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        before_commit()
        atomic_json(self.status, dict(status='complete', as_of=self.as_of, inputs=inputs,
                                     outputs={str(p): digest(p) for p in self.outputs if p.exists()}))
        self.committed = True

    def __exit__(self, kind, error, traceback):
        try:
            if not self.committed:
                if self.installing:
                    self.restore(self.backups)
                atomic_json(self.status, dict(status='failed', as_of=self.as_of, reason=str(error or '未提交')))
            shutil.rmtree(self.directory)
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()


def verify_publication(status, as_of):
    value = json.loads(Path(status).read_text())
    if value.get('status') != 'complete' or value.get('as_of') != as_of:
        raise ValueError('本信号日没有成功发布的执行计划')
    for path, expected in {**value.get('inputs', {}), **value['outputs']}.items():
        if digest(path) != expected:
            raise ValueError(f'发布后产物已改变：{path}')
    return value


def finish_evidence(as_of, since):
    """Called only after all evidence collectors succeeded; queue may be rebuilt later."""
    if since >= as_of:
        raise ValueError('证据起点须早于信号日')
    paths = [ROOT / p for p in ('data/interim/a_share_report_disclosures.csv',
                                'data/interim/a_share_earnings_forecasts.csv',
                                'data/raw/corporate_actions/a_share_corporate_actions.csv')]
    for p in list(paths):
        verify_stamp(p, as_of)
        paths.append(p.with_suffix(p.suffix + '.meta.json'))
    paths.append(ROOT / 'data/reference/a_share_action_component_exclusions.csv')
    for name in ('announcements', 'corporate_actions', 'market_context'):
        path = ROOT / f'data/interim/daily_{name}_{as_of}.json'
        value = json.loads(path.read_text())
        if value['signal_date'] != as_of:
            raise ValueError(f'证据日期不符：{path}')
        paths.append(path)
        if name == 'announcements':
            if value['query_start'] > since or value['queried_all_market_rows'] < value['reported_total_hits']:
                raise ValueError('公告证据区间或分页不完整')
            covered = value['locally_filtered_codes']
    atomic_json(ROOT / f'data/interim/daily_evidence_{as_of}.json',
                dict(status='complete', as_of=as_of, since=since, covered_codes=covered,
                     inputs={str(p.resolve()): digest(p) for p in paths}))


def verify_strategy_columns(as_of, snapshot=None):
    """§9.1 第 5 步／§10.3：信号日账户快照行存在，且到信号日为止的策略列已登记并与重算一致。"""
    import strategy_return_tracker as tracker
    path = Path(snapshot) if snapshot else tracker.SNAPSHOT
    _, rows = tracker.load(path)
    if not any(row.get('as_of') == as_of for row in rows):
        raise ValueError(f'账户快照缺少 {as_of} 行（§10.3）')
    problems = tracker.check_rows(rows, upto=as_of, require_filled=True)
    if problems:
        raise ValueError('§10.3 策略列未登记或与重算不一致：' + '；'.join(problems[:5]))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('evidence', 'verify'))
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--since')
    parser.add_argument('--publication', type=Path, default=ROOT / 'data/processed/daily_execution_publication.json')
    args = parser.parse_args()
    if args.action == 'verify':
        verify_publication(args.publication, args.as_of)
        verify_strategy_columns(args.as_of)
        print('执行批次日期、产物摘要与 §10.3 策略列均通过')
    else:
        if not args.since:
            parser.error('evidence requires --since (previous successful scan date)')
        finish_evidence(args.as_of, args.since)
        print('同日证据阶段完成')


if __name__ == '__main__':
    main()

"""統一顯示既有 Pulse writer 與持久研究工作；HTTP 讀取不啟動任何工作。"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import job_queue
from http_boundary import BodyReadError, read_json_body

UPDATE_TYPES = ('pulse', 'options', 'research')
_service = None
_ID = re.compile(r'^[pr]-[a-f0-9]{32}$')
_EXPIRY = re.compile(r'^(?:\d{8}|\d{4}-\d{2}-\d{2})$')


class UpdateCoordinator:
    def __init__(self, pulse, queue=None):
        self.pulse = pulse
        self.queue = queue or job_queue.DurableJobQueue(pulse.db_path)
        self.queue.register('options', self._options, priority=20, timeout=180)
        self.queue.register('research', self._research, priority=60, timeout=600)

    def _options(self, context, params):
        import decision_context
        import options_exposure
        context.stage('讀取已提交市場基準')
        reference = decision_context.latest_market_reference()
        if not reference:
            raise ValueError('尚未建立市場快照，請先更新市場')
        context.stage('更新官方選擇權資料')
        value = options_exposure.refresh(spot=reference['price'], spot_as_of=reference.get('asOf'),
                                         expiry=params.get('expiry'), force=params.get('force', True),
                                         commit_guard=context.check)
        context.check()
        if (not value.get('ok') or value.get('status') == 'stale' or
                'SOURCE_REFRESH_FAILED' in (value.get('quality') or {}).get('warnings', [])):
            raise ValueError('選擇權來源更新失敗，保留先前市場快照')
        context.stage('交由既有市場工作發布')
        # 不呼叫 update_options_structure：正式快照只能由原 Pulse writer 發布。
        queued = self._submit_market_after_source(context, 'options')
        return {'marketJobId': 'p-' + queued['job']['jobId'], 'marketCoalesced': queued['coalesced'],
                'sourceAsOf': (value.get('observed') or {}).get('tradeDate'),
                'note': '來源已更新；正式市場快照請查看關聯工作'}

    def _research(self, context, params):
        import overnight_intraday
        context.stage('更新日夜盤研究資料')
        value = overnight_intraday.get_snapshot(market=params.get('market', 'all'),
                                                force=params.get('force', True), commit_guard=context.check)
        context.check()
        if (not value.get('ok') or (value.get('cache') or {}).get('stale') or
                'REFRESH_FAILED_LAST_VALID_PRESERVED' in (value.get('quality') or {}).get('warnings', [])):
            raise ValueError('日夜盤研究來源更新失敗，保留前次可用結果')
        context.stage('交由既有市場工作發布')
        queued = self._submit_market_after_source(context, 'research')
        return {'marketJobId': 'p-' + queued['job']['jobId'], 'marketCoalesced': queued['coalesced'],
                'sourceAsOf': value.get('asOf') or value.get('generatedAt'),
                'note': '來源已更新；正式市場快照請查看關聯工作'}

    def _submit_market_after_source(self, context, source):
        # 來源完成前已在執行的市場工作可能凍結舊輸入，不能冒充包含新來源。
        completed = datetime.now(timezone.utc)
        while True:
            context.check()
            active = self.pulse.status()['job']
            if active and active['status'] == 'running' and datetime.fromisoformat(active['startedAt']) < completed:
                context.stage('等待既有市場工作結束，再發布新來源')
                time.sleep(0.1)
                continue
            context.check()
            queued = self.pulse.submit(reason=source + ':' + context.job['jobId'])
            selected = queued['job']
            if (selected['status'] != 'running' or datetime.fromisoformat(selected['startedAt']) >= completed):
                return queued

    @staticmethod
    def _params(kind, params):
        if kind not in UPDATE_TYPES or not isinstance(params, dict):
            raise ValueError('不支援的更新類型或參數')
        allowed = {'pulse': set(), 'options': {'expiry', 'force'}, 'research': {'market', 'force'}}[kind]
        if set(params) - allowed:
            raise ValueError('更新要求含有未支援欄位')
        if 'force' in params and not isinstance(params['force'], bool):
            raise ValueError('強制更新選項必須是布林值')
        if params.get('expiry') is not None and (not isinstance(params['expiry'], str) or not _EXPIRY.fullmatch(params['expiry'])):
            raise ValueError('選擇權到期日格式不正確')
        if params.get('expiry'):
            try:
                datetime.strptime(params['expiry'].replace('-', ''), '%Y%m%d')
            except ValueError as exc:
                raise ValueError('選擇權到期日不是有效日期') from exc
        if 'market' in params and (not isinstance(params['market'], str) or params['market'].upper() not in ('ALL', 'TW', 'US')):
            raise ValueError('研究市場必須是 all、TW 或 US')
        if kind == 'pulse':
            return {}
        return ({'force': params.get('force', True), **({'expiry': params['expiry'].replace('-', '')} if params.get('expiry') else {})}
                if kind == 'options' else {'market': 'all' if params.get('market', 'all').upper() == 'ALL' else params['market'].upper(),
                                           'force': params.get('force', True)})

    @staticmethod
    def _research_view(job):
        return dict(job, jobId='r-' + job['jobId'],
                    parentJobId='r-' + job['parentJobId'] if job.get('parentJobId') else None,
                    rootJobId='r-' + job['rootJobId'], source='research')

    @staticmethod
    def _pulse_view(job, jobs):
        by_id = {j['jobId']: j for j in jobs}
        current, attempt, seen = job, 1, {job['jobId']}
        parent = str(job.get('reason') or '').removeprefix('retry:') if str(job.get('reason') or '').startswith('retry:') else None
        while str(current.get('reason') or '').startswith('retry:'):
            next_id = current['reason'][6:]
            if next_id in seen or next_id not in by_id:
                break
            seen.add(next_id)
            current, attempt = by_id[next_id], attempt + 1
        return dict(job, jobId='p-' + job['jobId'], type='pulse', params={}, source='pulse',
                    parentJobId='p-' + parent if parent else None, rootJobId='p-' + current['jobId'], attempt=attempt,
                    lineageComplete=not str(current.get('reason') or '').startswith('retry:'),
                    stage={'queued': '等待市場工作者', 'running': '建立並提交市場快照', 'succeeded': '正式快照已提交',
                           'failed': '更新失敗', 'interrupted': '服務中斷'}.get(job['status'], '狀態未提供'),
                    canRetry=job['status'] in ('failed', 'interrupted'))

    def status(self):
        pulse, research = self.pulse.status(), self.queue.status()
        jobs = [self._pulse_view(j, pulse['jobs']) for j in pulse['jobs']]
        jobs.extend(self._research_view(j) for j in research['jobs'])
        jobs.sort(key=lambda j: j['queuedAt'] or '', reverse=True)
        return {'ok': True, 'jobs': jobs, 'researchTotalJobs': research.get('totalJobs', len(research['jobs'])), 'workers': {
            'pulse': {'running': pulse['worker'], 'error': pulse.get('workerError')},
            'research': {'running': research['worker'], 'error': research.get('workerError')}},
            'capacity': {'pulse': 1, 'research': research['capacity']},
            'note': '市場工作沿用原發布者及其既有最近100筆保留規則；研究沿革全數保留，可匯出。即時清單僅顯示近期工作。逾時來源返回前不釋放工作槽。'}

    def archive(self):
        pulse = self.pulse.status()['jobs']
        return {'ok': True, 'exportedAt': datetime.now(timezone.utc).isoformat(),
                'research': [self._research_view(job) for job in self.queue.archive()],
                'pulse': [self._pulse_view(job, pulse) for job in pulse],
                'scope': '研究工作全部歷史；市場工作依既有保留範圍匯出。'}

    def submit(self, kind, params=None):
        params = self._params(kind, {} if params is None else params)
        if kind == 'pulse':
            result = self.pulse.submit(reason='manual')
            return dict(result, ok=True, job=self._pulse_view(result['job'], self.pulse.status()['jobs']))
        result = self.queue.submit_registered(kind, params)
        return dict(result, job=self._research_view(result['job']))

    def retry(self, job_id):
        if not isinstance(job_id, str) or not _ID.fullmatch(job_id):
            raise ValueError('更新工作編號格式不正確')
        if job_id.startswith('p-'):
            job = self.pulse.status(job_id[2:])['job']
            if not job or job['status'] not in ('failed', 'interrupted'):
                raise ValueError('市場工作不存在、尚未結束或不允許重試')
            result = self.pulse.submit(reason='retry:' + job_id[2:])
            return dict(result, ok=True, job=self._pulse_view(result['job'], self.pulse.status()['jobs']))
        job = self.queue.get(job_id[2:])
        if not job or job['type'] not in ('options', 'research'):
            raise ValueError('只允許重試已知研究更新工作')
        result = self.queue.retry(job_id[2:])
        return dict(result, job=self._research_view(result['job']))


def configure_updates(pulse, *, queue=None, start=True):
    global _service
    service = UpdateCoordinator(pulse, queue)
    if start:
        service.queue.start()
        job_queue.use_durable_queue(service.queue)
    _service = service
    return service


def coordinator():
    if _service is None:
        raise RuntimeError('更新工作服務尚未初始化')
    return _service


class UpdateRoutesMixin:
    def _update_capabilities(self):
        role = str(self.headers.get('X-ST-Gateway-Role', '')).lower()
        owner = role in ('', 'owner')
        return {'canRead': True, 'canSubmit': owner, 'canRetry': owner,
                'types': list(UPDATE_TYPES) if owner else []}

    def _handle_updates_get(self):
        try:
            if urlsplit(self.path).path == '/updates/archive':
                self._ok(json.dumps(coordinator().archive(), ensure_ascii=False).encode())
                return
            result = coordinator().status()
            result['capabilities'] = self._update_capabilities()
            self._ok(json.dumps(result, ensure_ascii=False).encode())
        except Exception:
            self._err('更新工作狀態無法讀取', 503)

    def _handle_updates_post(self):
        if not self._update_capabilities()['canSubmit']:
            self._err('唯讀模式不能提交或重試更新', 403)
            return
        try:
            body = read_json_body(self, max_bytes=2048)
            if not isinstance(body, dict):
                raise ValueError('更新要求必須是 JSON 物件')
            path = urlsplit(self.path).path
            if path == '/updates':
                if set(body) - {'type', 'params'}:
                    raise ValueError('更新要求含有未支援欄位')
                result = coordinator().submit(body.get('type'), body.get('params', {}))
            elif path == '/updates/retry':
                if set(body) != {'jobId'}:
                    raise ValueError('重試只接受原工作編號')
                result = coordinator().retry(body['jobId'])
            else:
                self._err('找不到更新工作入口', 404)
                return
            self._ok(json.dumps(result, ensure_ascii=False).encode(), status=202)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
        except ValueError as exc:
            self._err(str(exc), 400)
        except job_queue.QueueFull as exc:
            self._err(str(exc), 429)
        except Exception:
            self._err('更新工作尚未接受，請稍後重試', 503)

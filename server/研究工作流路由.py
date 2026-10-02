"""研究 HTTP 邊界：嚴格參數、唯讀快取，未知資料不觸發外部更新。"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

from 研究工作流 import workspace, build_subject, capture_subject_sources, subject_symbol, ResearchDataError


def query(path, allowed):
    raw = urlsplit(path).query
    if re.search(r'%(?![0-9a-fA-F]{2})', raw):
        raise ValueError('查詢編碼不正確')
    values = parse_qs(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=10, errors='strict')
    if set(values) - set(allowed) or any(len(v) != 1 or not v[0] for v in values.values()):
        raise ValueError('查詢包含未知、重複或空白參數')
    return {key: value[0] for key, value in values.items()}


def integer(value, *, low, high):
    if not re.fullmatch(r'0|[1-9][0-9]*', str(value)) or not low <= int(value) <= high:
        raise ValueError('查詢數值超出範圍或格式不正確')
    return int(value)


class ResearchWorkflowRoutesMixin:
    def _research_result(self, result):
        body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self._ok(body)

    def _handle_research_subject(self):
        from pathlib import Path
        from types import SimpleNamespace
        try:
            values = query(self.path, {'symbol'})
            if 'symbol' not in values:
                raise ValueError('標的研究需要一個 symbol 代號')
            symbol = subject_symbol(values['symbol'])
        except (ValueError, UnicodeError) as exc:
            self._err(str(exc), 400)
            return
        try:
            import datastore
            import etf_paths
            environments = (getattr(cls.__dict__.get('do_GET'), '__globals__', {}) for cls in type(self).__mro__)
            environment = next((item for item in environments if '_openapi_ds' in item), {})
            public_keys = ('_openapi_ds', '_openapi_meta', '_mops_rev_cache', '_cache', '_TW_SECTORS', 'CHIP_HISTORY_PATH')
            runtime = SimpleNamespace(**{key: environment[key] for key in public_keys if key in environment})
            database = datastore.DB_PATH
            self._research_result(build_subject(symbol, database, sources=capture_subject_sources(runtime, symbol),
                chip_directory=getattr(runtime, 'CHIP_HISTORY_PATH', Path(database).parent / 'chip_history'),
                etf_directory=etf_paths.resolve_history_dir(create=False),
                catalog_path=Path(database).parent / 'etf_catalog.json'))
        except Exception:
            self._err('已保存標的資料讀取失敗；原資料保留，未啟動來源更新', 503)

    def _handle_research_validation(self):
        try:
            values = query(self.path, {'replay', 'offset', 'limit'})
            identifier = values.get('replay')
            if identifier:
                if len(values) != 1 or not re.fullmatch(r'[a-f0-9]{64}', identifier):
                    raise ValueError('觀測識別格式不正確，重播不可與分頁參數混用')
                offset, limit = 0, 30
            else:
                offset = integer(values.get('offset', '0'), low=0, high=10000000)
                limit = integer(values.get('limit', '30'), low=1, high=100)
        except (ValueError, UnicodeError) as exc:
            self._err(str(exc), 400)
            return
        try:
            import early_warning
            result = (early_warning.replay_observation(identifier, early_warning.DB_PATH) if identifier else
                      early_warning.observation_page(n=limit, path=early_warning.DB_PATH, offset=offset))
            if result.get('ok') is False:
                status = {'not_found': 404, 'invalid_request': 400, 'unavailable': 503}.get(result.get('status'), 409)
                self._err(result.get('reason') or result.get('availabilityReason') or '原始觀測無法核對；原資料保留', status)
                return
            self._research_result(result)
        except Exception:
            self._err('研究驗證讀取失敗；原始觀測保留，未啟動回填', 503)

    def _handle_research_portfolio(self):
        try:
            query(self.path, set())
        except (ValueError, UnicodeError) as exc:
            self._err(str(exc), 400)
            return
        try:
            import datastore
            from 突破組合研究 import build_saved_portfolio
            self._research_result(build_saved_portfolio(datastore.DB_PATH))
        except Exception:
            self._err('組合研究讀取失敗；原始資料保留，未啟動來源更新', 503)

    def _handle_research_workflow(self):
        try:
            values = query(self.path, {'current', 'previous', 'before', 'limit'})
            before = integer(values['before'], low=1, high=9223372036854775807) if 'before' in values else None
            limit = integer(values.get('limit', '30'), low=1, high=100)
            for name in ('current', 'previous'):
                if name in values and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', values[name]):
                    raise ValueError('快照編號格式不正確')
        except (ValueError, UnicodeError) as exc:
            self._err(str(exc), 400)
            return
        try:
            import decision_context
            self._research_result(workspace(getattr(decision_context, '_active_db_path', None) or decision_context.DB_PATH,
                current_id=values.get('current', ''), previous_id=values.get('previous', ''), before=before, limit=limit))
        except ResearchDataError:
            self._err('已保存快照內容無法核對；原資料保留，請檢查本機資料', 503)
        except LookupError as exc:
            self._err(str(exc), 404)
        except ValueError as exc:
            self._err(str(exc), 400)
        except Exception:
            self._err('研究快照讀取失敗；原有資料保留，請稍後重試', 503)

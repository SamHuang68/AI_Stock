"""研究工作流 HTTP 邊界；所有市場讀取皆唯讀。"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from 研究工作流 import workspace, observation_page, build_subject, capture_subject_sources, subject_symbol


class ResearchWorkflowRoutesMixin:
    def _handle_research_subject(self):
        from pathlib import Path
        from types import SimpleNamespace
        import datastore
        import etf_paths
        values = parse_qs(urlsplit(self.path).query)
        try:
            if set(values) - {'symbol'} or len(values.get('symbol') or []) != 1:
                raise ValueError('標的研究只接受一個 symbol 代號')
            symbol = subject_symbol(values['symbol'][0])
            # 直接沿 Handler 真正的函式全域尋找公開快取。sys.modules 可能被
            # 重載、別名匯入或測試替換；名稱相同不代表建立此 Handler 的環境。
            # MRO 也涵蓋只覆寫 do_GET 後呼叫 super 的稽核 Handler。
            environments = (getattr(cls.__dict__.get('do_GET'), '__globals__', {})
                            for cls in type(self).__mro__)
            environment = next((item for item in environments if '_openapi_ds' in item), {})
            public_keys = ('_openapi_ds', '_mops_rev_cache', '_cache', '_TW_SECTORS', 'CHIP_HISTORY_PATH')
            runtime = SimpleNamespace(**{key: environment[key] for key in public_keys if key in environment})
            sources = capture_subject_sources(runtime, symbol)
            database = datastore.DB_PATH
            result = build_subject(symbol, database, sources=sources,
                chip_directory=getattr(runtime, 'CHIP_HISTORY_PATH', Path(database).parent / 'chip_history'),
                etf_directory=etf_paths.resolve_history_dir(create=False),
                catalog_path=Path(database).parent / 'etf_catalog.json')
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        except Exception:
            self._err('已保存標的資料讀取失敗；未啟動來源更新', 503)
            return
        self._ok(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def _handle_research_validation(self):
        import early_warning
        import re
        values = parse_qs(urlsplit(self.path).query)
        try:
            identifier = (values.get('replay') or [''])[0]
            if identifier:
                if not re.fullmatch(r'[a-f0-9]{64}', identifier):
                    raise ValueError('觀測識別格式不正確')
                result = early_warning.replay_observation(identifier)
                if not result.get('ok'):
                    self._err(result.get('reason') or '原始規則輸出無法重播核對', 409)
                    return
            else:
                before = int(values['before'][0]) if values.get('before') else None
                result = observation_page(early_warning.DB_PATH, before=before)
                result['validation'] = early_warning.performance(1).get('researchValidation')
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        except Exception:
            self._err('研究驗證讀取失敗，原始觀測保留', 503)
            return
        self._ok(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def _handle_research_portfolio(self):
        import datastore
        from 突破組合研究 import build_saved_portfolio
        try:
            result = build_saved_portfolio(datastore.DB_PATH)
        except Exception:
            self._err('組合研究資料不足或讀取失敗，原始資料保留', 503)
            return
        self._ok(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def _handle_research_workflow(self):
        import decision_context
        values = parse_qs(urlsplit(self.path).query)
        try:
            before = int(values['before'][0]) if values.get('before') else None
            result = workspace(getattr(decision_context, '_active_db_path', None) or decision_context.DB_PATH,
                current_id=(values.get('current') or [''])[0],
                previous_id=(values.get('previous') or [''])[0], before=before,
                limit=int((values.get('limit') or ['30'])[0]))
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        except LookupError as exc:
            self._err(str(exc), 404)
            return
        except Exception:
            self._err('研究快照讀取失敗；原有資料保留，請稍後重試', 503)
            return
        self._ok(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8'))

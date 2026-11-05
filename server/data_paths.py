"""資料根解析器（單一資料根階段 2：只做路徑解析，行為與既有版本逐字相同）。

目前只有 legacy 一種模式：資料放在 ``<程式目錄>/data``、日誌放在 ``<程式目錄>/logs``，
與各模組以往自己用 ``os.path.join(_BASE, 'data', …)`` 組出來的路徑完全一致。

這個模組刻意保持為純函式：只看呼叫端傳入的 ``code_root`` 與環境變數，不讀任何檔案
（不讀發布收據、不探測旁檔、不建立目錄），所以不可能因為安裝目錄的型態或收據大小讓
原本正常的 legacy 安裝無法啟動。

外置資料根（身分檔、切換收據、寫入租約、發布與啟動器綁定）尚未啟用。若環境裡出現
``ST_DATA_ROOT``／``ST_RUNTIME_ROLE``／``ST_DATA_BINDING``，一律拒絕（fail closed），
絕不靜默改回 legacy 去開啟另一份資料。那些能力隨階段 3／4 加入。

環境變數覆寫（``override_env``）維持各模組原有的語意：呼叫端明確傳入的值優先，其次是
環境變數，最後才是預設路徑；覆寫值原樣回傳，不展開、不轉成絕對路徑。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# 這些名稱保留給外置資料根；階段 2 看到就拒絕。
BINDING_ENV = ('ST_DATA_ROOT', 'ST_RUNTIME_ROLE', 'ST_DATA_BINDING')
# 既有的「單一路徑覆寫」環境變數；解析時一併擷取，避免各模組各自讀 os.environ。
OVERRIDE_ENV = ('ST_UPDATE_JOBS_DB', 'ST_REPORTS_DIR', 'ST_AI_TRACE_PATH', 'LLM_GATE_PATH', 'ST_ETF_HISTORY_DIR')


class BindingError(RuntimeError):
    """設定不完整、互相衝突或目前版本不支援，不能安全地決定資料位置。"""


@dataclass(frozen=True)
class DataBinding:
    mode: str
    code_root: Path
    data_root: Path
    environment: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)


def _relative(value) -> Path:
    text = str(value).replace('\\', '/')
    if (':' in text or '\x00' in text or text.startswith('/')
            or any(part in ('.', '..') for part in text.split('/'))):
        raise BindingError('資料相對路徑不可為絕對路徑、含上層目錄或特殊字元')
    return Path(text)


def resolve_binding(*, code_root, environ: Mapping[str, str] | None = None) -> DataBinding:
    env = os.environ if environ is None else environ
    configured = [name for name in BINDING_ENV if str(env.get(name, '')).strip()]
    if configured:
        raise BindingError(
            '偵測到外置資料根設定（' + '、'.join(configured) + '），但此版本只支援 legacy 資料位置；'
            '為避免靜默開啟另一份資料，拒絕解析。')
    if not isinstance(code_root, (str, os.PathLike)) or not str(code_root).strip():
        raise BindingError('程式目錄不可為空')
    # 原樣沿用呼叫端的 code_root（不 abspath、不 resolve）：原本各模組就是直接 os.path.join，
    # 相對路徑、8.3 短檔名、連結都維持原樣，路徑才會與既有行為逐字相同。
    root = Path(code_root)
    captured = {name: env[name] for name in OVERRIDE_ENV if name in env}
    return DataBinding('legacy', root, root / 'data', captured)


def binding_for(*, code_root, environ: Mapping[str, str] | None = None) -> DataBinding:
    return resolve_binding(code_root=code_root, environ=environ)


def data_root(*, code_root, environ: Mapping[str, str] | None = None) -> Path:
    return binding_for(code_root=code_root, environ=environ).data_root


def _select(default: Path, binding: DataBinding, override, override_env) -> Path:
    explicit = override
    if override_env:
        if override_env not in OVERRIDE_ENV:
            raise BindingError(f'未登錄的路徑覆寫環境變數：{override_env}')
        if explicit is None:
            explicit = binding.environment.get(override_env)
    # 空字串視同沒設定（與原本 ``os.environ.get(…) or 預設`` 相同）。
    return Path(explicit) if explicit else default


def data_path(relative='', *, code_root, override=None, override_env=None,
              environ: Mapping[str, str] | None = None) -> Path:
    """正式資料路徑：``<資料根>/<relative>``，可被 ``override`` 或 ``override_env`` 覆寫。"""
    binding = binding_for(code_root=code_root, environ=environ)
    return _select(binding.data_root / _relative(relative), binding, override, override_env)


def log_path(relative='', *, code_root, override=None, override_env=None,
             environ: Mapping[str, str] | None = None) -> Path:
    """日誌路徑：legacy 為 ``<程式目錄>/logs/<relative>``，可被 ``override`` 或 ``override_env`` 覆寫。"""
    binding = binding_for(code_root=code_root, environ=environ)
    return _select(binding.code_root / 'logs' / _relative(relative), binding, override, override_env)

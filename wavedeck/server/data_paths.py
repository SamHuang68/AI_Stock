"""WaveDeck 的資料根解析入口（單一資料根階段 2b：只做路徑解析，行為與既有版本逐字相同）。

目前只有 legacy 一種模式：資料放在 ``<WaveDeck 程式目錄>/data``，與 ``state.DATA``、``server.py`` 以往自己用
``ROOT / "data"`` 組出來的路徑完全一致。這個模組是純函式：只看呼叫端傳入的 ``code_root`` 與環境變數，
不讀任何檔案、不建立目錄。

為什麼不直接沿用主站的 ``server/data_paths.py``，而是在這裡放一份精簡入口：

* WaveDeck 的 ``server`` 套件與主站的 ``server/`` 同名，同一個程序裡只會載入其中一個，不能互相匯入。
* ``版本身分.py`` 啟動時會逐檔核對 ``wavedeck/server/*.py`` 與發布收據的雜湊；決定資料落點的程式如果放在
  ``wavedeck/`` 之外，就不在收據涵蓋範圍內。
* 兩邊的行為由 ``tests/test_wavedeck_data_paths_parity.py`` 鎖定一致（同樣的環境變數名稱、同樣的拒絕條件），
  所以不會各自演變。這裡只實作 WaveDeck 用得到的部分（沒有 ``log_path``，也沒有路徑覆寫環境變數）。

外置資料根尚未啟用。若環境裡出現 ``ST_DATA_ROOT``／``ST_RUNTIME_ROLE``／``ST_DATA_BINDING``，一律拒絕
（fail closed），絕不靜默改回 legacy 去開啟另一份資料。

刻意還沒有改接的 WaveDeck 位置（登記在 ``tests/raw_data_paths_baseline.json`` 或此處，各有歸屬）：

* ``版本身分.py`` 的發布收據 ``data/程式版本.json``：該模組刻意只用標準庫、可單獨以檔案路徑載入並有測試鎖住；
  收據屬於發布身分，隨階段 4（發布與啟動器）處理。
* ``broker.py`` 的 ``txt_dir``（預設 ``data/master``，相對於程式目錄，也可設成絕對路徑）：這是使用者設定值，
  也是與外部下單程式交換委託檔的通道，不是內部執行期資料；搬到哪裡會改變外部程式讀到的內容，需另行決定。
* ``start_wavedeck.ps1``、``wait_ready.ps1``、``CHECK_WAVEDECK.ps1`` 等腳本讀取的 ``data\\wavedeck.port``：階段 4。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

# 這些名稱保留給外置資料根；階段 2 看到就拒絕（與主站 server/data_paths.py 相同）。
BINDING_ENV = ('ST_DATA_ROOT', 'ST_RUNTIME_ROLE', 'ST_DATA_BINDING')


class BindingError(RuntimeError):
    """設定不完整、互相衝突或目前版本不支援，不能安全地決定資料位置。"""


def _relative(value) -> Path:
    text = str(value).replace('\\', '/')
    if (':' in text or '\x00' in text or text.startswith('/')
            or any(part in ('.', '..') for part in text.split('/'))):
        raise BindingError('資料相對路徑不可為絕對路徑、含上層目錄或特殊字元')
    return Path(text)


def data_root(*, code_root, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = [name for name in BINDING_ENV if str(env.get(name, '')).strip()]
    if configured:
        raise BindingError(
            '偵測到外置資料根設定（' + '、'.join(configured) + '），但此版本只支援 legacy 資料位置；'
            '為避免靜默開啟另一份資料，拒絕解析。')
    if not isinstance(code_root, (str, os.PathLike)) or not str(code_root).strip():
        raise BindingError('程式目錄不可為空')
    # 原樣沿用呼叫端的 code_root（不 abspath、不 resolve），路徑才會與既有的 ``ROOT / "data"`` 逐字相同。
    return Path(code_root) / 'data'


def data_path(relative='', *, code_root, environ: Mapping[str, str] | None = None) -> Path:
    """正式資料路徑：``<資料根>/<relative>``。"""
    return data_root(code_root=code_root, environ=environ) / _relative(relative)

"""專案入口；使用可安裝至全域 tools/codex 的同一份驗證核心。"""
from pathlib import Path
import runpy

_core = Path(__file__).resolve().parents[1] / 'tools/codex/變更驗證.py'
if __name__ == '__main__':
    runpy.run_path(str(_core), run_name='__main__')
else:
    globals().update({key: value for key, value in runpy.run_path(str(_core)).items() if not key.startswith('__')})

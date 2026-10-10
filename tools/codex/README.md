# Codex 全域驗證範圍與成本防呆

本入口適用所有專案，Stock Terminal 只是其中一個接入者。每份計畫執行一個案例；局部驗證須有變更、契約、案例與輸入對應；完整驗證同時需要必要性與 Sam 的明確授權。只檢查明列輸入，不自動掃描專案。

版本控管來源為專案內 tools/codex/verification_gate.py，全域安裝位置為 C:/Users/Sam/AI-Workspace/tools/codex/verification_gate.py。局部測試通過後複製安裝並核對位元組；工作樹修改不等於已安裝。

```powershell
& '<Python 絕對路徑>' -B 'C:/Users/Sam/AI-Workspace/tools/codex/verification_gate.py' '<計畫 JSON 絕對路徑>'
```

局部計畫如下，尖括號須換成當次真實值：

```json
{
  "scope": "targeted",
  "verification_id": "指定功能案例",
  "reason": "本次修改影響的行為與待驗證結果",
  "artifact": "<確切候選 SHA 或產物識別>",
  "cwd": "<專案絕對路徑>",
  "command": ["<Python 絕對路徑>", "-B", "-m", "unittest", "tests.test_example"],
  "inputs": ["<受測來源絕對路徑>", "<案例絕對路徑>", "<相關設定與鎖檔絕對路徑>"],
  "impact": {
    "changed_files": ["<修改檔案絕對路徑>"],
    "contracts": ["受影響的公開行為契約"],
    "cases": [{
      "id": "指定案例",
      "changed_files": ["<修改檔案絕對路徑>"],
      "command": ["<Python 絕對路徑>", "-B", "-m", "unittest", "tests.test_example"],
      "inputs": ["<受測來源絕對路徑>", "<案例絕對路徑>", "<相關設定與鎖檔絕對路徑>"]
    }]
  },
  "environment": "<作業系統、Python／Node、相依套件與影響結果的環境變數識別>",
  "reuse_policy": "success",
  "mode": "static",
  "expected_seconds": 10,
  "timeout_seconds": 30,
  "evidence_dir": "C:/Users/Sam/AI-Workspace/docs/<專案>/verification-ledger"
}
```

command 必須 exact 對應 impact.cases 中唯一案例。每個案例的 inputs 須納入計畫 inputs；案例 changed_files 必須是非空的 impact.changed_files 子集合，存在的變更檔案必須全部納入該案例 inputs，不能用無關案例與文字理由冒充驗證。直接執行的 runner、unittest 命令指定的實際模組及 pytest 檔案節點也必須納入匹配案例 inputs。unittest 由 cwd 逐段定位最長存在的模組 .py 檔；無法定位時拒絕，請改用明確模組或檔案。

刪除檔案不能作為存在的輸入，必須在案例另列 deleted_files，例如 `[{"path":"<已刪除檔案絕對路徑>","consumer":"<受影響呼叫者絕對路徑>","reason":"刪除影響此呼叫者的具體理由"}]`。path 必須屬於該案例 changed_files 且確實不存在，consumer 必須存在並納入該案例 inputs。主控仍須核對傳遞依賴、設定、鎖檔及 runner 的直接呼叫，不能只填測試而漏掉受測來源。

舊局部計畫沒有 impact 時明確 DENY，須遷移以上欄位。verification_id 為穩定驗證項目，不隨提交 SHA 改名。每個項目沿用相同 evidence_dir，不得換命令、改名或換目錄規避重用。

已知全套入口不能標局部：unittest discover、未指定案例的 pytest、無明確 selector 的 npm test，以及直接 stage、部署、巢狀 gate、shell 或內嵌 Python wrapper。已知 wrapper 請展開直接案例 command，各自建立計畫。npm test -- <案例 selector> 僅檢查 selector 是否存在，主控仍須讀取 package script 確認實際傳遞 selector 且沒有額外全套命令。本工具無法理解任意程式、任意 shell，也不是作業系統層攔截器，不能證明授權文字為真。

完整驗證設 scope: full，加入非空 full_necessity，說明局部案例為何不足及必要範圍；再加入 full_consent 物件，其 explicit 為 true、user_quote 保存 Sam 同意這個範圍的原文、source 保存來源。重用前也檢查這些欄位。一般發布授權與 CI=true 不能代替完整驗證授權；舊完整計畫亦須補必要性。

成功快取依實際輸入內容、案例、命令、工作目錄、環境、執行檔與入口版本識別；另外自動記錄入口實際 Python 版本、實作、執行位置及作業系統／機器架構，避免只靠自由文字冒充同一環境。environment 仍須補充相依套件及影響結果的環境變數；入口無法自動推斷任意 runner 的全部外部狀態。artifact 只作來源紀錄。只有無關提交 SHA 改變時，回傳 REUSE 並附本次候選及原驗證候選。輸入、測試、環境或入口有變更則形成新識別。前次失敗或希望重跑已通過案例時，提供 rerun 物件，包含非空 reason 與新證據檔絕對路徑 evidence；同一證據內容禁止重複使用。

需要當次觀測的程序身分、部署安全條件與線上端點檢查，設 reuse_policy: never 或 mode: live；即使之前成功也重新執行，此設定不繞過失敗後的新證據要求。發布者仍須完整執行約定的安全門檻，不可把即時檢查錯標為靜態。

每次執行保存 started.json、stdout／stderr 與 result.json。只有退出碼為 0 且輸入、執行檔及入口沒有漂移才成功。觀察逾時回傳 124，保留程序及 active 紀錄，拒絕同識別再次啟動。先核對原程序與終態，不可只刪 active 或調大逾時重跑。

局部流程測試命令，由主控統一安排：

```powershell
& '<Python 絕對路徑>' -B -m unittest tests.test_驗證防呆
```

測試使用暫存目錄及秒級假 runner，包含兩個非 Stock Terminal 專案的隔離，不讀寫全域、不部署、不連網。main(plan_path, workspace_root=...) 第二參數可由程式指定證據根目錄，命令列仍使用固定 AI-Workspace 根目錄。

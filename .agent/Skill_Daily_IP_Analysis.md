# Skill: Daily IP & EDA Competitor Analysis
**Trigger (觸發條件):** 每天早上 08:30 自動觸發，或手動輸入 "Run Daily Analysis" 觸發。

**Task Flow (執行流程):**
1. **環境檢查**：透過終端機確認 Ollama 正在背景運行，並且目標模型（如 `gemma2:9b`）已加載。
2. **批次執行**：不要等待人工輸入。請自動對以下兩個核心標的執行 `pro_stock_analyzer.py` 的邏輯：
   - 標的 A：`SNPS` (市場代碼 2) - 追蹤自家 EDA/IP 估值變化。
   - 標的 B：`3529.TWO` (市場代碼 1) - 追蹤 NVM/OTP 最大競爭對手 eMemory 的市場與籌碼動態。
   *(註：若原程式需要手動 input，請 Agent 自行撰寫一個自動傳遞參數的 batch 腳本或修改原程式以支援 Command Line Arguments)*
3. **報告產出**：將這兩份由 Python 與本地 AI 混合生成的 Markdown 報告，合併為一份名為 `Daily_Report_YYYYMMDD.md` 的檔案。
4. **結果通知**：將合併後的 Markdown 檔案儲存至 `C:\AI_Stock\Reports\` 目錄下，並在終端機顯示「✅ 每日 NVM/EDA 競業分析報告已生成」。
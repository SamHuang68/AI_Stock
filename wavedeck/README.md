# WaveDeck · 浪潮執行台

**Stock Terminal 的微觀執行艦橋**——接收 TradingView／ST 訊號、AI 判斷、風控閘門、部位校準與下單橋接。

> 宏觀看盤 → [Stock Terminal](../README.md)  
> 微觀執行 → **WaveDeck**

資訊架構對齊附圖艦橋：部位四欄／AI 判斷／燈號牆／不留倉／Kill Switch／系統控制列。

![WaveDeck Console](docs/images/console-demo.webp)

---

## 為什麼叫 WaveDeck？

- **Wave**：延續 Wave AI 訊號／浪潮語意  
- **Deck**：艦橋／操作台——一眼掌握判斷、風控與執行  
- 中文名：**浪潮執行台**

---

## 30 秒啟動

需求：Python 3.10+（**純標準庫，不用 pip**）、現代瀏覽器。

```bash
cd wavedeck
python3 server/server.py
# Windows: py -3 server\server.py
```

開啟：

```
http://127.0.0.1:18433/
```

Windows 亦可雙擊 `START_WAVEDECK.cmd`。

### 艦橋上先按這顆

**「模擬 TV 事件」** → 跑一輪 `TIMED_MARKET_REVIEW` → 看 AI 判斷卡、閘門、稽核更新。

---

## 你會看到什麼

| 區塊 | 說明 |
|------|------|
| 頂列健康 | 系統／券商／同步／緊急停止 |
| 部位四欄 | AI 建議 · TXT 目標 · 策略 · 帳戶實倉 |
| 進場風格 | 35／50／65 滑桿（可被 ST 覆寫） |
| AI 判斷 | 主動作＋信心、偏多偏空、失效價、閘門 |
| 燈號牆 | Webhook／決策引擎／ST 橋接／風控… |
| 控制列 | 啟停、模擬事件、Kill Switch |

架構細節 → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 與 Stock Terminal 銜接

| 方向 | 端點 |
|------|------|
| ST → WaveDeck | `POST http://127.0.0.1:18433/bridge/st` |
| TV／訊號 | `POST http://127.0.0.1:18433/webhook` |
| 狀態 | `GET  http://127.0.0.1:18433/api/state` |

ST 覆寫範例：

```bash
curl -s -X POST http://127.0.0.1:18433/bridge/st \
  -H 'Content-Type: application/json' \
  -d '{"style":65,"delever":false,"note":"宏觀偏多，風格轉積極"}'
```

預設 **paper** 模式；實盤需明確切換（v1.5 接下單大師 TXT adapter）。

---

## 對 Gemini 初版的關鍵修正

1. **Local-first，而非雲端絕對禁止**（可選 Ollama／OpenAI）  
2. **v1 = stdlib + SQLite**，不強迫 Redis／Docker  
3. **AI 建議必須過執行閘門**  
4. **正式狀態機 + ST JSON 協定**  
5. UI 對齊附圖資訊架構，品牌獨立（金／青、艦橋密度）

---

## 目錄

```
wavedeck/
  server/     # API、狀態機、風控、決策、稽核
  web/        # 艦橋 Console
  docs/       # 架構設計書
  data/       # 本機狀態／稽核（密鑰勿提交）
```

## 授權

與 Stock Terminal 相同（MIT 精神）；本目錄為連動子專案，可獨立啟動。

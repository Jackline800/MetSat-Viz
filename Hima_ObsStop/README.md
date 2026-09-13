# 向日葵衛星事件總覽

整合日本氣象廳四份來源：

| 衛星 | 觀測休止履歷 | 事件日誌 |
| --- | --- | --- |
| H8 | [觀測休止](https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H8.html) | [品質低下／處理方式變更](https://www.data.jma.go.jp/mscweb/ja/oper/event_H8.html) |
| H9 | [觀測休止](https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H9.html) | [品質低下／處理方式變更](https://www.data.jma.go.jp/mscweb/ja/oper/event_H9.html) |

## 更新與開啟

Python 3.9 以上，在本資料夾執行：

```powershell
python -m pip install -r requirements.txt
python update_data_stable.py
```

`data.js` 預設輸出到程式所在資料夾。四份來源全部解析成功後才原子替換檔案；任一連線失敗、缺少資料或事件日誌結構不符時，保留既有資料。

開啟 `index.html` 即可瀏覽。靜態網站需一起更新 `index.html`、`dashboard.js`、`data.js`；CSS 與 SVG 圖表由頁面本身提供。Python 更新程式另需同資料夾的 `observation_time.py`、`event_translation.py`、`event_log.py`、`event_catalog.py`、`event_log_translations.json`。

離線重現解析時，資料夾內需有 `H9_pause.html`、`H8_pause.html`、`H9_event.html`、`H8_event.html` 四份原始 HTML。休止履歷也接受舊檔名 `H9.html`、`H8.html`，事件日誌仍為必要來源。

```powershell
python update_data_stable.py --source-dir saved_sources --output data.js
```

## 網頁閱讀方式

- 以衛星、年度、關鍵字、分類及休止原因篩選，可切換時間軸／表格；月份與事件可各自展開。
- 四張摘要卡以所選衛星、年度統計；下方分類、原因與搜尋只影響紀錄清單及趨勢。圖表各類獨立刻度，避免每日維護數量掩蓋較少發生的品質異常。
- 「觀測休止」含軌道控制、校正、衛星及系統維護；「品質與配發異常」含缺漏、雜訊、延遲與其他品質問題；「處理方式變更」依正式生效日期歸類；「公告」含任務交接與預期影響。
- 詳情保留繁中說明、原始日文、來源日期時間、頻道／區域／服務、各服務獨立時段及相關附件。刪除線舊日期列為修訂前資訊，不另計事件。
- 全頁時間為 UTC。「觀測時次 −10 分鐘」僅換算觀測休止履歷的觀測時次（含跨日）；事件日誌、配發時間、公告、生效時間與僅列小時的時間保留原值。多來源事件主列採事件日誌時間，履歷時次的換算可在來源詳情查看。

## 計數與整合規則

| 欄位 | 意義 |
| --- | --- |
| `category` | `pause`、`quality`、`change`、`notice`；品質日誌中的預期影響保留 `quality` 來源分類，網頁依 `record_type=notice` 顯示於公告。 |
| `event_count` | 休止：每日固定休止依實際日期計次，連續休止計 1 次。品質：每份整合後的異常紀錄計 1 則。變更與公告計 0。 |
| `observation_count` | 休止履歷可確定的觀測時次數，含首末時次；品質／配發異常及事件日誌為 `null`，不從時長推定實際欠配數。 |
| `covered_slot_count` | 品質異常在休止履歷中所列時段涵蓋的 10 分鐘時次，與實際缺漏筆數不同。 |
| `change_count` / `notice_count` | 變更次數／公告則數，與休止分開計算。 |
| `start_utc` / `end_utc` / `intervals` | 完整 UTC 起迄。分離時次使用多個 interval；不得將中間時段視為持續異常。 |
| `time_role` | 區別觀測、事件、配發、公告或生效時間，控制能否使用時次換算。 |
| `temporal_pattern` / `status` | 標示間歇性、僅列起點、預期影響等，不因缺少終點推定仍在持續。 |
| `service_intervals` | 內文明列的服務時間優先；未另列時標示沿用事件標題，保留其依據。 |
| `sources` / `related_events` | 完整來源記載，以及未能確認為同一事件的重疊紀錄。 |

只有衛星相同、起迄時間完全相同、影響類型與原因相容，且匹配唯一時，才合併履歷與事件日誌。例行維護不因同時發生就與品質異常合併。時間或範圍不符、約略時間、多組分離時次均保留分列；重疊紀錄互相連結。因此品質卡顯示「紀錄數」，不宣稱是唯一障礙總數。

P 碼保留原文，不用來反推時刻。來源的 P 碼與時刻偶有不一致。統計年月一律依來源起始年月；跨日完整時間仍在紀錄內顯示。

例如 H8 2020-03-23 19:30 UTC（P118）至 03-24 02:50 UTC（P018），時段涵蓋 45 個時次；日誌另記 HimawariCast、HimawariCloud、アデス於 03-23 20:30 UTC 恢復配發。網頁同時保留兩項記載，不將 45 個時次宣稱為所有產品的欠配數。

繁中翻譯使用完整句型及 `event_log_translations.json` 的來源對照。未知新描述保留原文，`translation_status` 標記全部／部分未翻譯；更新時會提示，網頁也會顯示標記。維護對照表時應保留可能性、間歇性、服務範圍及原始時刻。

## 離線驗證

```powershell
python update_data_stable.py --self-test
node test_frontend.cjs
```

Python 測試涵蓋履歷表格、跨日、每日重複時段、排除日、日誌不完整標籤、修訂日期、各服務時段、公告及保留既有輸出的失敗流程。日誌測試使用 `fixtures` 內的 JMA 2026-09-11 原始快照。

前端測試使用目前 `data.js` 與實際 `dashboard.js`，檢查分類、計數、篩選、圖表、來源時間、兩種檢視、翻譯及 HTML 轉義。

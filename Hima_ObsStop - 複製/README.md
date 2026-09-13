# 向日葵觀測休止資料更新

資料來源為日本氣象廳 [H9](https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H9.html) 與 [H8](https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H8.html) 的觀測休止履歷。

在本資料夾執行：

```powershell
python -m pip install -r requirements.txt
python update_data_stable.py
```

`data.js` 預設寫到程式所在資料夾。任一衛星連線失敗或未解析出資料時，停止更新，保留既有檔案。下載好的原始頁面可分別存為 `H9.html`、`H8.html`，再以 `--source-dir <資料夾>` 重現解析；`--output <檔案>` 可指定輸出位置。

## 計數與顯示

- `event_count`：連續障礙計一次；每日固定休止依實際日期計次。換星等營運公告 `record_type=notice` 計零次。
- `observation_count`：依 UTC 起迄時間，以每 10 分鐘一個時次計算，含首末時次；代表受影響時次，包含部分影像缺漏或品質異常，不等於全部產品都欠配。只有小時或尚無終點時填 `null`，網頁顯示「未確定」。
- `start_utc`、`end_utc`：完整 UTC 日期時間；P 碼保留原文，不用來反推時間或計數。歷史公告的 P 碼與時刻偶有不一致。
- `affected_dates_iso`：涵蓋跨日、跨月及跨年的實際日期。統計依事件起始年月歸類。既有 `affected_dates` 僅保留起始年月內的日數。
- `event_jp`、`memo` 保留日文；`event_tw`、`memo_tw` 以完整句型翻譯。未知描述保留來源文字，方便補充翻譯規則。

網頁保留原有臺灣模式的 UTC 減 10 分鐘設定，連續時段兩端一起換算並處理日期進退；營運公告及僅列小時的記錄保留原始時間。

解析會合併被換行拆開的時段與 P 碼、讀取放在事件欄的時間、保留多行影像說明，並排除刪除線舊值與已取消紀錄。11 月「1～31 日」這類來源日期誤植，計次僅涵蓋當月實際存在的日期，原文仍保留。

## 離線驗證

```powershell
python update_data_stable.py --self-test
node test_frontend.cjs
```

Python 測試涵蓋跨日時段、換星公告、換行、排除日、合併儲存格及既有 2026/06 P089 補完。前端測試使用目前 `data.js`，驗證完整起迄時間、45 筆欠配時次、統計、篩選、日期換算與公告翻譯。

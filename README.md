# 🛰️ MetSat-Viz (氣象衛星遙測視覺化)

*透過直觀、互動式的網頁介面，呈現全球氣象衛星的分佈現況與技術演進。*

---

## 🌐 網頁展示
(建議使用 Ctrl + 點擊，或滑鼠右鍵另開分頁)

### 1. 🌍 全球氣象衛星軌道分佈圖 (SAT_PRO)
視覺化呈現同步軌道 (GEO) 與繞極軌道 (LEO) 配置。
👉 [點此觀看系統](https://sat-info.com/SAT_PRO/index.html)

### 2. 📊 日韓氣象衛星世代演進 (HimaCOMS)
時間軸互動分析，含 Himawari 與 COMS/GK 系列演進。
👉 [點此觀看時間軸](https://sat-info.com/HimaCOMS/index.html)

### 3. 📋 向日葵 8 / 9 號觀測休止履歷監測系統 (Hima_ObsStop)
整合雙衛星觀測中斷紀錄，支援自動化每週爬蟲、臺灣地區觀測時差校正（扣除10分鐘延遲）與西元/民國雙曆法連動篩選。
👉 [點此觀看監測面板](https://sat-info.com/Hima_ObsStop/index.html)

---

## 🛠️ 架構說明

- **SAT_PRO/**：衛星軌道分佈主程式與衛星影像資料庫。
- **HimaCOMS/**：世代演進時間軸主程式與各系列酬載技術參數。
- **Hima_ObsStop/**：觀測休止監測系統。包含自動化更新爬蟲程式 (`update_data.py`)、動態資料庫 (`data.js`) 以及互動式前端監測面板 (`index.html`)。

---

*維護者：葉子嫈 | 專長：衛星遙測、大氣科學、海洋生地化*
*Jackline 115/05/27*

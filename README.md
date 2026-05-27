<div style="font-family: sans-serif;">

# <span style="font-size: 32px;">🛰️ MetSat-Viz (氣象衛星遙測視覺化)</span>

<span style="font-size: 18px; color: #555;">本專案庫旨在透過直觀、互動式的網頁介面，呈現全球氣象衛星的分佈現況與技術演進。</span>

---

## 🌐 <span style="font-size: 24px;">線上作品展示</span>

<div style="margin-left: 20px;">

### 1. 🌍 全球氣象衛星軌道分佈圖 (SAT_PRO)
<span style="font-size: 16px;">視覺化呈現同步軌道 (GEO) 與繞極軌道 (LEO) 配置。</span><br>
<span style="font-size: 16px; font-weight: bold;"><a href="https://jackline800.github.io/MetSat-Viz/SAT_PRO/index.html">👉 點此觀看系統 (另開分頁)</a></span>

### 2. 📊 日韓氣象衛星世代演進 (HimaCOMS)
<span style="font-size: 16px;">時間軸互動分析，含 Himawari 與 COMS/GK 系列演進。</span><br>
<span style="font-size: 16px; font-weight: bold;"><a href="https://jackline800.github.io/MetSat-Viz/HimaCOMS/index.html">👉 點此觀看時間軸 (另開分頁)</a></span>

### 3. 📋 向日葵 8 / 9 號觀測休止履歷監測系統 (Hima_ObsStop)
<span style="font-size: 16px;">整合雙衛星觀測中斷紀錄，支援自動化每週爬蟲、臺灣地區觀測時差校正（扣除10分鐘延遲）與西元/民國雙曆法連動篩選。</span><br>
<span style="font-size: 16px; font-weight: bold;"><a href="https://jackline800.github.io/MetSat-Viz/Hima_ObsStop/index.html">👉 點此觀看監測面板 (另開分頁)</a></span>

</div>

---

## 🛠️ <span style="font-size: 24px;">專案架構說明</span>

<ul style="font-size: 16px; line-height: 1.8;">
  <li><strong>SAT_PRO/</strong>：衛星軌道分佈主程式與衛星影像資料庫。</li>
  <li><strong>HimaCOMS/</strong>：世代演進時間軸主程式與各系列酬載技術參數。</li>
  <li><strong>Hima_ObsStop/</strong>：觀測休止監測系統。包含自動化更新爬蟲程式 (<code>update_data.py</code>)、動態資料庫 (<code>data.js</code>) 以及互動式前端監測面板 (<code>index.html</code>)。</li>
</ul>

<br>

<span style="font-size: 14px; color: #888;">維護者：葉子嫈 | 專長：衛星遙測、大氣科學與數值分析</span>
<br>
<span style="font-size: 14px; color: #888;">Jackline 115/05/27</span>

</div>

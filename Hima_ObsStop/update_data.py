import json
import re
import calendar
from datetime import datetime
import requests
from bs4 import BeautifulSoup

URLS = {
    "H9": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H9.html",
    "H8": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H8.html"
}
OUTPUT_JS = "data.js"

TERM_MAP = {
    '東西軌道制御': '東西軌道控制',
    '南北軌道制御': '南北軌道控制',
    '放射計太陽校正': '輻射計太陽校正',
    '衛星メンテナンス': '衛星例行維護',
    '衛星保守作業': '衛星檢修作業',
    'ひまわり': '向日葵',
    'に代わり': '代替',
    'で観測を行います': '執行觀測',
    'から': '起',
    '観測運用を開始します': '開始觀測運用'
}

def parse_year_string(year_str):
    match_reiwa = re.search(r'令和(\d+)年', year_str)
    if match_reiwa:
        reiwa_yr = int(match_reiwa.group(1))
        ad_yr = reiwa_yr + 2018
        roc_yr = ad_yr - 1911
        return ad_yr, roc_yr, f"令和{reiwa_yr}年"
    match_ad = re.search(r'(20\d{2})年', year_str)
    if match_ad:
        ad_yr = int(match_ad.group(1))
        roc_yr = ad_yr - 1911
        reiwa_yr = ad_yr - 2018
        return ad_yr, roc_yr, f"令和{reiwa_yr}年" if reiwa_yr > 0 else ""
    return 2026, 115, "令和8年"

def scrape_satellite_data(sat_code, url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        print(f"成功連線向日葵 {sat_code} 號網頁，開始解析...")
    except Exception as e:
        print(f"連線 {sat_code} 失敗: {e}")
        return []

    records = []
    current_year_txt = "令和8年"
    current_month_num = 1
    
    main_content = soup.find('div', id='main') or soup.find('main') or soup.body
    
    for elem in main_content.find_all(['h2', 'h3', 'h4', 'table']):
        text = elem.text.strip()
        if not text: continue
            
        if elem.name in ['h2', 'h3', 'h4']:
            year_match = re.search(r'(令和\d+年|20\d{2}年)', text)
            if year_match:
                current_year_txt = year_match.group(1)
            month_match = re.search(r'(\d+)月', text)
            if month_match:
                current_month_num = int(month_match.group(1))
            continue
                
        if elem.name == 'table':
            rows = elem.find_all('tr')
            if not rows: continue
                
            ad_yr, roc_yr, reiwa_yr_clean = parse_year_string(current_year_txt)
            
            # 建立一個陣列來記憶上一行的欄位，破解 JMA 的 rowspan 地雷
            prev_row_cols = ["", "", "", "", "", ""]
            
            for row in rows[1:]:
                tds = row.find_all(['td', 'th'])
                # 使用 separator=' ' 把 <br> 轉換為空白，防止文字黏在一起
                cols_text = [td.get_text(separator=' ').strip().replace('\n', ' ') for td in tds]
                cols_text = [re.sub(r'\s+', ' ', t) for t in cols_text]
                
                if not cols_text: continue
                
                # --- 核心修復：動態繼承合併儲存格 ---
                date_raw, time_raw, fd, reg, event_jp, memo = "", "", "", "", "", ""
                
                # 判斷第一欄是不是日期 (有日、月、每日等字眼)
                is_date_cell = '日' in cols_text[0] or '月' in cols_text[0]
                
                if is_date_cell:
                    date_raw = cols_text[0]
                    time_raw = cols_text[1] if len(cols_text) > 1 else ""
                    fd = cols_text[2] if len(cols_text) > 2 else ""
                    reg = cols_text[3] if len(cols_text) > 3 else ""
                    event_jp = cols_text[4] if len(cols_text) > 4 else prev_row_cols[4]
                    memo = cols_text[5] if len(cols_text) > 5 else prev_row_cols[5]
                else:
                    # 代表日期欄被合併了，從記憶中調用上一行的日期
                    date_raw = prev_row_cols[0]
                    time_raw = cols_text[0]
                    fd = cols_text[1] if len(cols_text) > 1 else ""
                    reg = cols_text[2] if len(cols_text) > 2 else ""
                    event_jp = cols_text[3] if len(cols_text) > 3 else prev_row_cols[4]
                    memo = cols_text[4] if len(cols_text) > 4 else prev_row_cols[5]
                
                # 更新記憶
                prev_row_cols = [date_raw, time_raw, fd, reg, event_jp, memo]
                
                # 防呆過濾表頭
                if not time_raw or '期日' in date_raw or '休止' in time_raw:
                    continue
                
                # 更新月份
                row_month_match = re.search(r'(\d+)月', date_raw)
                if row_month_match:
                    current_month_num = int(row_month_match.group(1))
                
                try:
                    _, days_in_month = calendar.monthrange(ad_yr, current_month_num)
                except:
                    days_in_month = 30
                    
                # ==========================================
                # 除外日期精準捕捉邏輯
                # ==========================================
                exclude_dates = []
                combined_text = date_raw + " " + memo
                
                for kw in ["を除く", "を除き", "除去", "除外"]:
                    if kw in combined_text:
                        chunk = combined_text.split(kw)[0]
                        if "（" in chunk and "）" not in chunk:
                            chunk = chunk.split("（")[-1]
                        elif "(" in chunk and ")" not in chunk:
                            chunk = chunk.split("(")[-1]
                        else:
                            # 用空白或波浪號切割，精準鎖定在排除字眼緊鄰的前一個數字
                            parts = re.split(r'[～~\s]', chunk)
                            parts = [p for p in parts if p.strip()]
                            if parts: chunk = parts[-1]
                        exclude_dates.extend([int(d) for d in re.findall(r'(\d+)日', chunk)])
                
                exclude_dates = list(set(exclude_dates))

                # 淨化日期字串，防止除外的數字干擾區間判斷
                clean_date_raw = date_raw
                for kw in ["を除く", "を除き", "除去", "除外"]:
                    if kw in clean_date_raw:
                        clean_date_raw = re.sub(r'[（(][^)）]*' + kw + r'[^)）]*[)）]', '', clean_date_raw)
                        clean_date_raw = re.sub(r'[\s]*(?:\d+日[、，,]*)+[\s]*' + kw, '', clean_date_raw)
                        clean_date_raw = clean_date_raw.replace(kw, '')

                # 判斷區間與計算受影響的天數
                affected_dates = []
                if "毎日" in clean_date_raw:
                    date_type = "每日"
                    affected_dates = [d for d in range(1, days_in_month + 1) if d not in exclude_dates]
                elif "～" in clean_date_raw or "~" in clean_date_raw:
                    date_type = "期間"
                    parts = re.split(r'[～~]', clean_date_raw)
                    start_nums = re.findall(r'(\d+)', parts[0])
                    end_nums = re.findall(r'(\d+)', parts[1])
                    
                    start_d = int(start_nums[-1]) if start_nums else 1
                    end_d = int(end_nums[-1]) if end_nums else days_in_month
                    
                    if start_d <= end_d:
                        affected_dates = [d for d in range(start_d, end_d + 1) if d not in exclude_dates]
                    else:
                        affected_dates = [d for d in range(start_d, days_in_month + 1) if d not in exclude_dates]
                else:
                    date_type = "單日"
                    day_matches = re.findall(r'(\d+)日', clean_date_raw)
                    affected_dates = [int(d) for d in day_matches if int(d) not in exclude_dates]
                
                event_count = len(affected_dates) if len(affected_dates) > 0 else 1
                
                # 翻譯事件
                event_tw = event_jp
                for jp, tw in TERM_MAP.items():
                    event_tw = event_tw.replace(jp, tw)
                
                p_match = re.search(r'\(（?(P\d+)）?\)', time_raw)
                p_code = p_match.group(1) if p_match else ""
                
                records.append({
                    "satellite": sat_code,
                    "ad_year": ad_yr,
                    "roc_year": roc_yr,
                    "reiwa_year": reiwa_yr_clean,
                    "month": current_month_num,
                    "date_raw": date_raw,
                    "date_type": date_type,
                    "exclude_dates": exclude_dates, 
                    "event_count": event_count,
                    "time_raw": time_raw,
                    "p_code": p_code,
                    "fd": fd,
                    "reg": reg,
                    "event_jp": event_jp,
                    "event_tw": event_tw,
                    "memo": memo
                })
    return records

def main():
    all_satellite_data = []
    for sat_code, url in URLS.items():
        sat_data = scrape_satellite_data(sat_code, url)
        all_satellite_data.extend(sat_data)
        print(f"-> 向日葵 {sat_code} 號解析完成，共 {len(sat_data)} 筆紀錄。")
        
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write(f"const ALL_SAT_DATA = {json.dumps(all_satellite_data, ensure_ascii=False, indent=2)};\n")
        f.write(f"const LAST_UPDATED = '{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}';\n")
    print(f"\n【大功告成】已成功寫入 {OUTPUT_JS}！")

if __name__ == "__main__":
    main()
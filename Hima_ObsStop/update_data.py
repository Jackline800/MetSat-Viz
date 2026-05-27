import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# 定義向日葵8號與9號的網頁網址
URLS = {
    "H9": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H9.html",
    "H8": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H8.html"
}
OUTPUT_JS = "data.js"

# 專業術語繁體化對照表
TERM_MAP = {
    '東西軌道制御': '東西軌道控制',
    '南北軌道制御': '南北軌道控制',
    '放射計太陽校正': '輻射計太陽校正',
    '衛星メンテナンス': '衛星例行維護',  # 每日定時維護
    '衛星保守作業': '衛星檢修作業',       # 修正日文直翻感
    'ひまわり': '向日葵',
    'に代わり': '代替',
    'で観測を行います': '執行觀測',
    'から': '起',
    '観測運用を開始します': '開始觀測運用'
}

def parse_year_string(year_str):
    """解析年份文字，彈性支援『令和X年』與『西元20XX年』"""
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
    """抓取單一衛星網頁並解析結構化資料"""
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
    current_month_txt = "5月"
    
    main_content = soup.find('div', id='main') or soup.find('main') or soup.body
    
    for elem in main_content.find_all(['h2', 'h3', 'h4', 'table']):
        text = elem.text.strip()
        if not text:
            continue
            
        if elem.name in ['h2', 'h3']:
            year_match = re.search(r'(令和\d+年|20\d{2}年)', text)
            if year_match:
                current_year_txt = year_match.group(1)
                continue
                
        if elem.name == 'h4' or (elem.name == 'h3' and '月' in text and '年' not in text):
            month_match = re.search(r'(\d+)月', text)
            if month_match:
                current_month_txt = text.replace('　', '').strip()
                continue
                
        if elem.name == 'table':
            rows = elem.find_all('tr')
            if not rows:
                continue
                
            th_texts = [th.text.strip() for th in rows[0].find_all(['th', 'td'])]
            if '期日' not in th_texts and '観測休止' not in th_texts:
                continue
                
            ad_yr, roc_yr, reiwa_yr_clean = parse_year_string(current_year_txt)
            month_match = re.search(r'(\d+)月', current_month_txt)
            month_num = int(month_match.group(1)) if month_match else 1
            
            for row in rows[1:]:
                cols = [td.text.strip().replace('\n', ' ') for td in row.find_all('td')]
                if len(cols) < 5:
                    continue
                
                date_raw = cols[0]
                time_raw = cols[1]
                fd = cols[2]
                reg = cols[3]
                event_jp = cols[4]
                memo = cols[5] if len(cols) > 5 else ""
                
                date_type = "期間" if "～" in date_raw else "單日"
                
                event_tw = event_jp
                for jp, tw in TERM_MAP.items():
                    event_tw = event_tw.replace(jp, tw)
                
                p_match = re.search(r'\(（?(P\d+)）?\)', time_raw)
                p_code = p_match.group(1) if p_match else ""
                
                records.append({
                    "satellite": sat_code,  # 標記是 H8 還是 H9
                    "ad_year": ad_yr,
                    "roc_year": roc_yr,
                    "reiwa_year": reiwa_yr_clean,
                    "month": month_num,
                    "date_raw": date_raw,
                    "date_type": date_type,
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
    
    # 依序抓取 H9 與 H8
    for sat_code, url in URLS.items():
        sat_data = scrape_satellite_data(sat_code, url)
        all_satellite_data.extend(sat_data)
        print(f"-> 向日葵 {sat_code} 號解析完成，共 {len(sat_data)} 筆紀錄。")
        
    # 寫入單一資料庫檔案
    with open(OUTPUT_JS, 'w', encoding='utf-8') as f:
        f.write(f"const ALL_SAT_DATA = {json.dumps(all_satellite_data, ensure_ascii=False, indent=2)};\n")
        f.write(f"const LAST_UPDATED = '{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}';\n")
    print(f"\n【大功告成】雙衛星總計 {len(all_satellite_data)} 筆歷史紀錄，已成功寫入 {OUTPUT_JS}！")

if __name__ == "__main__":
    main()

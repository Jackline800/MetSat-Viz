import docx
import pandas as pd

# 讀取原始 word 檔案
doc = docx.Document('H9観測休止履歴.docx')
all_rows = []

# 日文專有名詞繁體化對照表
translate_dict = {
    '期日': '日期', '観測休止': '觀測休止時間(UTC)', '運用・障害': '運用與維護項目', '原因': '原因備註',
    '東西軌道制御': '東西軌道控制', '南北軌道制御': '南北軌道控制',
    '放射計太陽校正': '放射計太陽校正', '衛星メンテナンス': '衛星例行維護', '衛星保守作業': '衛星保守作業'
}

# 遍歷所有表格並串接資料
for table in doc.tables:
    headers = [cell.text.strip() for cell in table.rows[0].cells]
    if '期日' in headers or '観測休止' in headers:
        for row in table.rows[1:]:
            row_data = [cell.text.strip().replace('\n', ' ') for cell in row.cells]
            # 去除因儲存格合併產生的重複欄位
            clean_row = []
            for item in row_data:
                if not clean_row or item != clean_row[-1]:
                    clean_row.append(item)
            
            # 確保標準欄位長度 (日期, 時間, FD, Reg, 項目, 備註)
            if len(clean_row) >= 5:
                all_rows.append(clean_row[:6])

# 轉換為 DataFrame 並翻譯
df = pd.DataFrame(all_rows, columns=['日期', '觀測休止時間(UTC)', '全球觀測(F.D.)', '區域觀測(Reg)', '項目', '備註'][:len(all_rows[0])])
df['項目'] = df['項目'].replace(translate_dict, regex=True)

# 儲存為您專屬的完整版 CSV
df.to_csv('Himawari9_All_History.csv', index=False, encoding='utf-8-sig')
print(f"成功！已將全年度共 {len(df)} 筆完整數據匯出為 Himawari9_All_History.csv")

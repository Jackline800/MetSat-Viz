import json
import re
import calendar
import argparse
import os
from pathlib import Path
from datetime import datetime
from html import unescape

import requests
from bs4 import BeautifulSoup
from event_translation import EVENT_TRANSLATIONS, translate_event, translate_memo
from observation_time import add_time_metadata, date_instances, extract_event_time, time_entries

URLS = {
    "H9": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H9.html",
    "H8": "https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_H8.html",
}
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_JS = SCRIPT_DIR / "data.js"

TERM_MAP = EVENT_TRANSLATIONS

EXCLUDE_PATTERN = r"(?:を)?(?:除く|除き|除外|除去)"


def normalize_text(text):
    if text is None:
        return ""
    return (
        str(text)
        .replace("\u3000", " ")
        .replace("\xa0", " ")
        .replace("〜", "～")
        .replace("－", "-")
        .replace("―", "-")
        .replace("–", "-")
        .strip()
    )


def compact_spaces(text):
    return re.sub(r"[ \t]+", " ", normalize_text(text)).strip()


def parse_year_string(year_str):
    year_str = normalize_text(year_str).replace("元年", "1年")

    # 令和：令和1年 = 西元2019年
    match_reiwa = re.search(r"令和(\d+)年", year_str)
    if match_reiwa:
        era_yr = int(match_reiwa.group(1))
        ad_yr = era_yr + 2018
        return ad_yr, ad_yr - 1911, f"令和{era_yr}年"

    # 平成：平成1年 = 西元1989年
    match_heisei = re.search(r"平成(\d+)年", year_str)
    if match_heisei:
        era_yr = int(match_heisei.group(1))
        ad_yr = era_yr + 1988
        return ad_yr, ad_yr - 1911, f"平成{era_yr}年"

    match_ad = re.search(r"((?:19|20)\d{2})年", year_str)
    if match_ad:
        ad_yr = int(match_ad.group(1))
        if ad_yr >= 2019:
            era_yr = ad_yr - 2018
            era_txt = f"令和{era_yr}年"
        elif ad_yr >= 1989:
            era_yr = ad_yr - 1988
            era_txt = f"平成{era_yr}年"
        else:
            era_txt = ""
        return ad_yr, ad_yr - 1911, era_txt

    return 2026, 115, "令和8年"


def cell_text(cell):
    # Only visual breaks split entries. Inline links/spans must not create
    # extra events, and superseded/cancelled struck-out text is not active.
    copy = BeautifulSoup(str(cell), "html.parser")
    for deleted in copy.find_all(["s", "del", "strike"]):
        deleted.decompose()
    for br in copy.find_all("br"):
        br.replace_with("\n")
    text = copy.get_text()
    lines = [compact_spaces(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    return "\n".join(lines)


def split_lines(text):
    lines = [compact_spaces(x) for x in normalize_text(text).splitlines()]
    return [x for x in lines if x]


def table_to_grid(table):
    """Return table text grid while expanding rowspan/colspan."""
    grid = []
    spans = {}

    for r, tr in enumerate(table.find_all("tr")):
        row = []
        c = 0

        def fill_spans():
            nonlocal c
            while (r, c) in spans:
                text, rows_left = spans.pop((r, c))
                row.append(text)
                if rows_left > 1:
                    spans[(r + 1, c)] = (text, rows_left - 1)
                c += 1

        fill_spans()
        for cell in tr.find_all(["th", "td"], recursive=False):
            fill_spans()
            text = cell_text(cell)
            rowspan = int(cell.get("rowspan", 1) or 1)
            colspan = int(cell.get("colspan", 1) or 1)
            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    spans[(r + 1, c)] = (text, rowspan - 1)
                c += 1
        fill_spans()
        if any(row):
            grid.append(row)
    return grid


def header_index(headers, candidates, default=None):
    joined = [h.replace("\n", " ") for h in headers]
    for i, h in enumerate(joined):
        for cand in candidates:
            if cand in h:
                return i
    return default


def _extract_day_list(day_text):
    day_text = normalize_text(day_text)
    day_text = re.sub(
        r"\d{1,2}月\s*\d{1,2}日?\s*[～~-]\s*(?:\d{1,2}月)?\s*\d{1,2}日?",
        " ",
        day_text,
    )
    day_text = re.sub(r"\d{1,2}月", " ", day_text)
    nums = [int(n) for n in re.findall(r"\d{1,2}", day_text)]
    return {n for n in nums if 1 <= n <= 31}


def extract_exclude_dates(*texts):
    days = set()
    for src in texts:
        src = normalize_text(src)
        if not src or not re.search(EXCLUDE_PATTERN, src):
            continue

        for m in re.finditer(r"[（(]([^）)]*?" + EXCLUDE_PATTERN + r"[^）)]*)[）)]", src):
            before_kw = re.split(EXCLUDE_PATTERN, m.group(1), maxsplit=1)[0]
            days.update(_extract_day_list(before_kw))

        for m in re.finditer(EXCLUDE_PATTERN, src):
            before = src[: m.start()]
            parts = re.split(r"[\s。;；（）()]+", before)
            for part in reversed(parts):
                if re.search(r"\d", part):
                    days.update(_extract_day_list(part))
                    break
    return days


def infer_month_from_text(text, fallback_month):
    match = re.search(r"(\d{1,2})月", normalize_text(text))
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            return month
    return fallback_month


def strip_exclusion_phrases(text):
    """Return the base date expression with Japanese exclusion clauses removed.

    Examples:
      6月1日～21日 1日を除く      -> 6月1日～21日
      6月1日～21日（1日を除く）   -> 6月1日～21日
      6月1日～30日 1、15、29日を除く -> 6月1日～30日
    """
    text = normalize_text(text)
    text = re.sub(r"[（(][^）)]*?" + EXCLUDE_PATTERN + r"[^）)]*[）)]", " ", text)

    # Remove standalone trailing clauses such as "1日を除く" or
    # "1、15、29日を除く" while preserving the period before the clause.
    while True:
        match = re.search(EXCLUDE_PATTERN, text)
        if not match:
            break
        before = text[: match.start()]
        after = text[match.end() :]
        clause_start = max(before.rfind(sep) for sep in [" ", "\n", "\t", "。", ";", "；", "（", "("])
        if clause_start >= 0:
            text = text[:clause_start] + " " + after
        else:
            # Exclusion-only text, e.g. "1日を除く". There is no base date.
            text = after
    return compact_spaces(text)


def extract_affected_days(date_text, days_in_month):
    text = normalize_text(date_text)
    base = strip_exclusion_phrases(text)

    if "毎日" in base:
        return "每日", list(range(1, days_in_month + 1))

    range_match = re.search(
        r"(?:\d{1,2}月)?\s*(\d{1,2})日?\s*[～~-]\s*(?:\d{1,2}月)?\s*(\d{1,2})日?",
        base,
    )
    if range_match:
        start_d = int(range_match.group(1))
        end_d = int(range_match.group(2))
        if start_d <= end_d:
            return "期間", list(range(start_d, min(end_d, days_in_month) + 1))
        return "期間", list(range(start_d, days_in_month + 1))

    days = [int(d) for d in re.findall(r"(\d{1,2})日", base)]
    return "單日", [d for d in days if 1 <= d <= days_in_month]


def is_exclusion_only(text):
    text = normalize_text(text)
    return bool(re.search(EXCLUDE_PATTERN, text)) and not re.search(r"[～~-]|毎日", text)


def is_base_date_part(text):
    text = normalize_text(text)
    return bool(re.search(r"毎日|[～~-]|\d{1,2}月\d{1,2}日|\d{1,2}日", text)) and not is_exclusion_only(text)


def make_date_entries(date_text):
    """Split a multiline date cell into visual date entries.

    Example:
      6月1日～14日\n6月1日～14日\n1日を除く
    becomes:
      ["6月1日～14日", "6月1日～14日 1日を除く"]
    """
    parts = split_lines(date_text)
    if not parts:
        return []
    entries = []
    for part in parts:
        if is_exclusion_only(part) and entries:
            entries[-1] = f"{entries[-1]} {part}"
        elif is_base_date_part(part):
            entries.append(part)
        elif entries:
            entries[-1] = f"{entries[-1]} {part}"
        else:
            entries.append(part)
    return entries


def pick_part(parts, i, n, default=""):
    if not parts:
        return default
    if len(parts) == n:
        return parts[i]
    if len(parts) == 1:
        return parts[0]
    if i < len(parts):
        return parts[i]
    return parts[-1]


def expand_visual_row(row, idx_date, idx_time, idx_fd, idx_reg, idx_event, idx_memo):
    def get(idx):
        return row[idx] if idx is not None and idx < len(row) else ""

    date_entries = make_date_entries(get(idx_date))
    time_parts = time_entries(get(idx_time))
    fd_parts = split_lines(get(idx_fd))
    reg_parts = split_lines(get(idx_reg))
    event_parts = split_lines(get(idx_event))
    memo_parts = split_lines(get(idx_memo))

    # Use time/date visual lines as the main record count. Reuse event/F.D./Reg
    # when JMA uses a single merged value for multiple maintenance rows.
    n = max(len(time_parts), len(date_entries), 1)
    if n == 1:
        # An event/cause may be a sentence or several affected image types.
        event_parts = [get(idx_event)]
        memo_parts = [get(idx_memo)]

    expanded = []
    for i in range(n):
        expanded.append(
            {
                "date_raw": pick_part(date_entries, i, n),
                "time_raw": pick_part(time_parts, i, n),
                "fd": pick_part(fd_parts, i, n),
                "reg": pick_part(reg_parts, i, n),
                "event_jp": pick_part(event_parts, i, n),
                "memo": pick_part(memo_parts, i, n),
            }
        )
    return expanded



MAINTENANCE_TEXT_PATTERN = re.compile(
    r"(?P<date>(?:\d{1,2}月\s*)?\d{1,2}日?\s*[～~-]\s*(?:\d{1,2}月\s*)?\d{1,2}日?)"
    r"\s*(?P<exclude>(?:(?:\d{1,2}\s*[、,，・]\s*)*\d{1,2}日?\s*)" + EXCLUDE_PATTERN + r")?"
    r"\s*(?P<time>\d{2}:\d{2}\s*UTC\s*[\(（]\s*(?P<pcode>P\d+)\s*[\)）])"
    r"\s*(?P<fd>[XO])\s*(?P<reg>[XO])\s*衛星メンテナンス"
)


def recover_maintenance_rows_from_table_text(
    table_text,
    sat_code,
    ad_yr,
    roc_yr,
    era_year_clean,
    fallback_month,
):
    """Recover maintenance rows that are visible in JMA but lack a valid <tr>.

    Some JMA tables contain orphaned <td> elements. Browsers still display
    those cells, while BeautifulSoup's tr-based traversal can omit the row.
    Scanning the flattened table text preserves the exact date range and
    exclusion days without inventing data.
    """
    flat = compact_spaces(table_text)
    recovered = []

    for match in MAINTENANCE_TEXT_PATTERN.finditer(flat):
        date_part = compact_spaces(match.group("date"))
        exclude_part = compact_spaces(match.group("exclude") or "")
        date_raw = compact_spaces(f"{date_part} {exclude_part}")
        time_raw = compact_spaces(match.group("time"))
        p_code = match.group("pcode")

        month_num = infer_month_from_text(date_raw, fallback_month)
        _, days_in_month = calendar.monthrange(ad_yr, month_num)
        exclude_dates = extract_exclude_dates(date_raw)
        date_type, affected_dates = extract_affected_days(date_raw, days_in_month)
        if exclude_dates:
            affected_dates = [d for d in affected_dates if d not in exclude_dates]

        recovered.append(
            {
                "satellite": sat_code,
                "ad_year": ad_yr,
                "roc_year": roc_yr,
                "reiwa_year": era_year_clean,
                "era_year": era_year_clean,
                "month": month_num,
                "date_raw": date_raw,
                "date_calc_raw": date_raw,
                "date_type": date_type,
                "event_count": len(affected_dates) if affected_dates else 1,
                "affected_dates": affected_dates,
                "excluded_dates": sorted(exclude_dates),
                "time_raw": time_raw,
                "p_code": p_code,
                "fd": match.group("fd"),
                "reg": match.group("reg"),
                "event_jp": "衛星メンテナンス",
                "event_tw": TERM_MAP["衛星メンテナンス"],
                "memo": "parser補完：依JMA表格原始文字復原",
            }
        )

    return recovered


YEAR_MONTH_SECTION_PATTERN = re.compile(
    r"(?:(?P<era>令和|平成)(?P<era_year>\d+|元)年|(?P<ad_year>(?:19|20)\d{2})年)\s*(?P<month>\d{1,2})月"
)


def source_html_to_text(source_html):
    """Extract text directly from the original HTML source.

    This deliberately does not rely on the parsed table tree. The JMA page
    contains malformed/orphaned table cells in some months. A browser repairs
    those cells for display, but BeautifulSoup's ``tr`` traversal can lose
    them or move them outside the corresponding ``table`` element.
    """
    source_html = re.sub(
        r"<!--.*?-->|<script\b.*?</script>|<style\b.*?</style>|<(?:s|del|strike)\b[^>]*>.*?</(?:s|del|strike)>",
        " ",
        source_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source_html = re.sub(r"<br\s*/?>", " ", source_html, flags=re.IGNORECASE)
    source_html = re.sub(r"<[^>]+>", " ", source_html)
    return re.sub(r"\s+", " ", normalize_text(unescape(source_html))).strip()


def recover_maintenance_rows_from_page_source(source_html, sat_code):
    """Recover maintenance rows from year/month sections in raw page source.

    The table-local fallback is insufficient when an orphaned ``td`` is moved
    outside its table by the HTML parser. Scanning the original page source
    retains the visible P089 row and still assigns the correct year/month from
    the nearest preceding Japanese year-month heading.
    """
    page_text = source_html_to_text(source_html)
    headings = list(YEAR_MONTH_SECTION_PATTERN.finditer(page_text))
    recovered = []

    for i, heading in enumerate(headings):
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(page_text)
        section_text = page_text[start:end]

        month_num = int(heading.group("month"))
        if heading.group("era"):
            year_text = f'{heading.group("era")}{heading.group("era_year")}年'
        else:
            year_text = f'{heading.group("ad_year")}年'
        ad_yr, roc_yr, era_year_clean = parse_year_string(year_text)

        recovered.extend(
            recover_maintenance_rows_from_table_text(
                section_text,
                sat_code,
                ad_yr,
                roc_yr,
                era_year_clean,
                month_num,
            )
        )

    return recovered


def scrape_satellite_data(sat_code, url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    # Do not replace both satellites' history with a partial/HTTP-error result.
    res = requests.get(url, headers=headers, timeout=30)
    res.raise_for_status()
    res.encoding = "utf-8"
    print(f"成功連線向日葵 {sat_code} 號網頁，開始解析...")
    return parse_satellite_html(sat_code, res.text)


def finalize_record(record):
    date_text = record.get("date_calc_raw") or record["date_raw"]
    dates = date_instances(strip_exclusion_phrases(date_text), record["ad_year"], record["month"])
    dates = [date for date in dates if date.day not in record["excluded_dates"]]
    record["event_count"] = len(dates)
    record["affected_dates"] = [date.day for date in dates
                                if date.year == record["ad_year"] and date.month == record["month"]]
    record["event_tw"] = translate_event(record["event_jp"])
    record["memo_tw"] = translate_memo(record.get("memo", ""))
    return add_time_metadata(record, dates)


def parse_satellite_html(sat_code, source_html):
    """Parse offline source identically to a fetched JMA history page."""
    # JMA also uses the invalid closing tag </br> as a visual line break.
    source_html = re.sub(r"</br\s*>", "<br>", source_html, flags=re.IGNORECASE)
    soup = BeautifulSoup(source_html, "html.parser")
    records = []
    current_year_txt = None
    current_month_txt = None
    main_content = soup.find("div", id="main") or soup.find("main") or soup.body or soup

    for elem in main_content.find_all(["h2", "h3", "h4", "table"]):
        text = compact_spaces(elem.get_text(" ", strip=True))
        if not text:
            continue
        # Most historical year/month labels are text INSIDE <table>, not h2.
        # Read only the prefix before its first row, never dates in notices.
        if elem.name == "table":
            prefix = str(elem).split("<tr", 1)[0]
            heading_text = source_html_to_text(prefix)
        else:
            heading_text = text
        year_match = re.search(r"(令和(?:\d+|元)年|平成(?:\d+|元)年|(?:19|20)\d{2}年)", heading_text)
        if year_match:
            current_year_txt = year_match.group(1)
        month_match = re.search(r"(\d{1,2})月", heading_text)
        if month_match:
            current_month_txt = month_match.group(1) + "月"
        if elem.name != "table":
            continue

        grid = table_to_grid(elem)
        if not grid:
            continue
        headers = grid[0]
        if not any("期日" in h for h in headers) or not any("観測休止" in h for h in headers):
            continue
        if not current_year_txt or not current_month_txt:
            raise ValueError(f"{sat_code}: observation table has no year/month heading")
        idx_date = header_index(headers, ["期日"], 0)
        idx_time = header_index(headers, ["観測休止"], 1)
        idx_fd = header_index(headers, ["F.D", "F.D."], 2)
        idx_reg = header_index(headers, ["Reg", "REG"], 3)
        idx_event = header_index(headers, ["運用", "障害"], 4)
        idx_memo = header_index(headers, ["原因"])
        ad_yr, roc_yr, era_year_clean = parse_year_string(current_year_txt)
        table_month_num = infer_month_from_text(current_month_txt, 1)
        last_period_date_raw = ""

        for row in grid[1:]:
            if len(row) <= max(idx_date, idx_time, idx_fd, idx_reg, idx_event):
                continue
            if len(set(row)) == 1:
                # A colspan notice is one announcement, not six event fields.
                notice = row[0]
                notice_date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", notice)
                if not notice_date:
                    continue
                notice_year = int(notice_date[1])
                notice_time, _ = extract_event_time(notice[notice_date.start():])
                if not notice_time:
                    continue
                _, notice_roc, notice_era = parse_year_string(f"{notice_year}年")
                records.append({
                    "satellite": sat_code, "ad_year": notice_year,
                    "roc_year": notice_roc, "reiwa_year": notice_era, "era_year": notice_era,
                    "month": int(notice_date[2]), "date_raw": notice_date.group(),
                    "date_calc_raw": notice_date.group(), "date_type": "營運公告",
                    "record_type": "notice", "excluded_dates": [], "time_raw": notice_time,
                    "p_code": "", "fd": "", "reg": "", "event_jp": notice, "memo": "",
                })
                history = re.search(r"ひまわり([89])号観測休止履歴はこちら", notice)
                if history:
                    records[-1]["related_url"] = URLS[f"H{history[1]}"]
                continue

            # Recover times and complete image descriptions embedded in the
            # event column; do this before deciding whether the row is empty.
            embedded_time, event_label = extract_event_time(row[idx_event])
            if embedded_time and event_label:
                if not row[idx_time]:
                    row[idx_time] = embedded_time
                row[idx_event] = event_label

            for rec in expand_visual_row(row, idx_date, idx_time, idx_fd, idx_reg, idx_event, idx_memo):
                date_raw, time_raw = rec["date_raw"], rec["time_raw"]
                if not date_raw or not time_raw or not rec["event_jp"]:
                    continue
                if "中止" in rec["memo"]:
                    continue
                date_calc_raw = date_raw
                if is_exclusion_only(date_raw) and last_period_date_raw:
                    date_calc_raw = f"{last_period_date_raw} {date_raw}"
                else:
                    base_type, base_days = extract_affected_days(date_raw, 31)
                    if base_type in ["期間", "每日"] and base_days:
                        last_period_date_raw = strip_exclusion_phrases(date_raw)
                month_num = infer_month_from_text(date_calc_raw, table_month_num)
                _, days_in_month = calendar.monthrange(ad_yr, month_num)
                date_type, _ = extract_affected_days(date_calc_raw, days_in_month)
                records.append({
                    "satellite": sat_code, "ad_year": ad_yr, "roc_year": roc_yr,
                    "reiwa_year": era_year_clean, "era_year": era_year_clean, "month": month_num,
                    "date_raw": date_raw, "date_calc_raw": date_calc_raw, "date_type": date_type,
                    "excluded_dates": sorted(extract_exclude_dates(date_calc_raw, rec["memo"])),
                    "time_raw": time_raw, "p_code": "", "fd": rec["fd"], "reg": rec["reg"],
                    "event_jp": rec["event_jp"], "memo": rec["memo"],
                })

    # Raw-source recovery preserves maintenance cells that have no valid tr.
    records.extend(recover_maintenance_rows_from_page_source(source_html, sat_code))
    return dedupe_records([finalize_record(record) for record in records])



def _normalized_dedup_text(value):
    """去除空白差異，避免同一筆 JMA 紀錄被視為兩筆。"""
    return re.sub(r"\s+", "", normalize_text(value or ""))


def _dedup_key(r):
    return (
        r.get("satellite"),
        r.get("ad_year"),
        r.get("month"),
        _normalized_dedup_text(
            r.get("date_calc_raw") or r.get("date_raw")
        ),
        _normalized_dedup_text(r.get("time_raw")),
        r.get("p_code") or "",
        r.get("event_jp") or r.get("event_tw") or "",
    )


def _record_quality(r):
    """同一事件有多種解析結果時，保留日期解析較完整的一筆。"""
    affected = r.get("affected_dates")
    affected_count = len(affected) if isinstance(affected, list) else 0

    try:
        event_count = int(r.get("event_count") or 0)
    except (TypeError, ValueError):
        event_count = 0

    excluded = r.get("excluded_dates")
    excluded_count = len(excluded) if isinstance(excluded, list) else 0

    # affected_dates 與 event_count 相符，代表日期區間解析完整。
    count_consistent = int(
        affected_count > 0 and affected_count == event_count
    )

    return (
        count_consistent,
        affected_count,
        event_count,
        excluded_count,
    )


def dedupe_records(records):
    """合併語意相同的紀錄，並保留解析品質較高的一筆。"""
    out = []
    positions = {}

    for record in records:
        key = _dedup_key(record)

        if key not in positions:
            positions[key] = len(out)
            out.append(record)
            continue

        index = positions[key]

        if _record_quality(record) > _record_quality(out[index]):
            out[index] = record

    return out



def repair_maintenance_pairs(records):
    """Validate maintenance pairs without fabricating excluded dates.

    Exact recovery is handled by recover_maintenance_rows_from_table_text().
    The previous implementation guessed that the first day was excluded; that
    is incorrect for source rows such as "1、29日を除く" or "4日を除く".
    """
    groups = {}
    for r in records:
        if r.get("event_jp") == "衛星メンテナンス":
            groups.setdefault((r.get("satellite"), r.get("ad_year"), r.get("month")), []).append(r)

    missing = []
    for key, rows in groups.items():
        has_p017 = any(r.get("p_code") == "P017" or "P017" in r.get("time_raw", "") for r in rows)
        has_p089 = any(r.get("p_code") == "P089" or "P089" in r.get("time_raw", "") for r in rows)
        if has_p017 and not has_p089:
            missing.append(key)

    for sat, yr, mon in missing:
        print(f"[WARN] {sat} {yr}/{int(mon):02d} has P017 but no P089; source text should be checked.")
    return 0


def print_check(records):
    rows = [r for r in records if r.get("satellite") == "H9" and r.get("ad_year") == 2026 and r.get("month") == 6]
    print("\n[CHECK] H9 2026/06")
    for r in rows:
        print(f"{r.get('date_raw')} | {r.get('time_raw')} | {r.get('event_tw')} | count={r.get('event_count')} | exclude={r.get('excluded_dates', [])}")


def write_data_js(records, output_js):
    output_path = Path(output_js).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"const ALL_SAT_DATA = {json.dumps(records, ensure_ascii=False, indent=2)};\n")
        f.write(f"const LAST_UPDATED = '{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}';\n")
    os.replace(temp_path, output_path)
    return output_path


def validate_regression_records(records):
    """Prevent silently writing a data.js that drops the known JMA P089 row."""
    targets = [
        r for r in records
        if r.get("satellite") == "H9"
        and r.get("ad_year") == 2026
        and r.get("month") == 6
        and r.get("p_code") == "P089"
        and r.get("event_jp") == "衛星メンテナンス"
    ]

    if not targets:
        raise RuntimeError(
            "解析失敗：H9 2026/06 的 14:50 UTC(P089) "
            "衛星維護紀錄仍不存在，已停止覆寫 data.js。"
        )

    expected_excluded = [1, 29]

    valid_targets = [
        row for row in targets
        if row.get("excluded_dates") == expected_excluded
        and int(row.get("event_count") or 0) == 28
    ]

    if not valid_targets:
        details = "; ".join(
            f"date={row.get('date_raw')}, "
            f"excluded={row.get('excluded_dates')}, "
            f"count={row.get('event_count')}"
            for row in targets
        )

        raise RuntimeError(
            "解析結果不正確：H9 2026/06 P089 "
            "應排除 1、29 日，共 28 次；"
            f"目前解析結果：{details}"
        )

    target = max(valid_targets, key=_record_quality)

    print(
        "[PASS] H9 2026/06 P089 已解析："
        f"{target.get('date_raw')} | {target.get('time_raw')} | "
        f"count={target.get('event_count')} | "
        f"exclude={target.get('excluded_dates')}"
    )


def run_self_test():
    html = """
    <html><body><main>
    <h2>令和8年6月</h2>
    <table>
      <tr><th>期日</th><th>観測休止</th><th>F.D.</th><th>Reg</th><th>運用・障害</th><th>原因</th></tr>
      <tr><td>6月1日～14日</td><td>02:50 UTC(P017)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td></tr>
      <tr><td>6月1日～14日<br>1日を除く</td><td>14:50 UTC(P089)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td></tr>
      <tr><td>6月1日～14日<br>6月1日～14日<br>1日を除く</td><td>02:50 UTC(P017)<br>14:50 UTC(P089)</td><td>X<br>X</td><td>O<br>O</td><td>衛星メンテナンス</td><td></td></tr>
      <tr><td>6月1日～21日<br>1日を除く</td><td>14:50 UTC(P089)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td></tr>
      <tr><td>6月1日～30日<br>1、15、29日を除く</td><td>02:50 UTC(P017)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td></tr>
    </table>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    grid = table_to_grid(table)
    headers = grid[0]
    idx_date = header_index(headers, ["期日"], 0)
    idx_time = header_index(headers, ["観測休止"], 1)
    idx_fd = header_index(headers, ["F.D", "F.D."], 2)
    idx_reg = header_index(headers, ["Reg", "REG"], 3)
    idx_event = header_index(headers, ["運用", "障害"], 4)
    idx_memo = header_index(headers, ["原因"], 5)
    last = ""
    results = []
    for row in grid[1:]:
        for rec in expand_visual_row(row, idx_date, idx_time, idx_fd, idx_reg, idx_event, idx_memo):
            date_calc = rec["date_raw"]
            if is_exclusion_only(date_calc) and last:
                date_calc = f"{last} {date_calc}"
            else:
                tp, days = extract_affected_days(date_calc, 30)
                if tp in ["期間", "每日"] and days:
                    last = date_calc
            excl = extract_exclude_dates(date_calc)
            tp, days = extract_affected_days(date_calc, 30)
            if excl:
                days = [d for d in days if d not in excl]
            results.append((rec["date_raw"], rec["time_raw"], len(days), sorted(excl)))
    for r in results:
        print(r)

    assert ("6月1日～21日 1日を除く", "14:50 UTC(P089)", 20, [1]) in results
    assert ("6月1日～30日 1、15、29日を除く", "02:50 UTC(P017)", 27, [1, 15, 29]) in results

    malformed_html = """
    <html><body><main>
    <h2>令和8年6月</h2>
    <table>
      <tr><th>期日</th><th>観測休止</th><th>F.D.</th><th>Reg</th><th>運用・障害</th><th>原因</th></tr>
      <tr><td>6月1日～30日</td><td>02:50 UTC(P017)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td></tr>
      <td>6月1日～30日<br>1、29日を除く</td><td>14:50 UTC(P089)</td><td>X</td><td>O</td><td>衛星メンテナンス</td><td></td>
    </table>
    </main></body></html>
    """
    malformed_soup = BeautifulSoup(malformed_html, "html.parser")
    malformed_table = malformed_soup.find("table")
    recovered = recover_maintenance_rows_from_table_text(
        malformed_table.get_text(" ", strip=True),
        "H9",
        2026,
        115,
        "令和8年",
        6,
    )
    target = [r for r in recovered if r["p_code"] == "P089"]
    assert len(target) == 1
    assert target[0]["event_count"] == 28
    assert target[0]["excluded_dates"] == [1, 29]
    assert target[0]["affected_dates"] == [d for d in range(1, 31) if d not in (1, 29)]

    # Actual failure mode: P089 cells are outside the parsed table. The raw
    # page-source fallback must still recover the row under the correct month.
    orphan_page_html = """
    <html><body>
      <h2>ひまわり９号 観測休止履歴（令和8年）</h2>
      <div>令和8年6月</div>
      <table>
        <tr><th>期日</th><th>観測休止</th><th>F.D.</th><th>Reg</th><th>運用・障害</th></tr>
        <tr><td>6月1日～30日</td><td>02:50 UTC(P017)</td><td>X</td><td>O</td><td>衛星メンテナンス</td></tr>
      </table>
      <td>6月1日～30日<br>1、29日を除く</td>
      <td>14:50 UTC(P089)</td><td>X</td><td>O</td><td>衛星メンテナンス</td>
      <div>令和8年5月</div>
    </body></html>
    """
    page_recovered = recover_maintenance_rows_from_page_source(orphan_page_html, "H9")
    page_target = [
        r for r in page_recovered
        if r["ad_year"] == 2026 and r["month"] == 6 and r["p_code"] == "P089"
    ]
    assert len(page_target) == 1
    assert page_target[0]["event_count"] == 28
    assert page_target[0]["excluded_dates"] == [1, 29]

    print("self-test assertions passed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true", help="run parser self test and exit")
    parser.add_argument(
        "--source-dir", type=Path,
        help="parse saved H9.html and H8.html from this directory instead of fetching JMA",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_JS),
        help="output data.js path (default: same directory as this script)",
    )
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        import unittest
        suite = unittest.defaultTestLoader.discover(str(SCRIPT_DIR), pattern="test_*.py")
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
            raise SystemExit(1)
        return

    all_satellite_data = []
    for sat_code, url in URLS.items():
        if args.source_dir:
            sat_data = parse_satellite_html(sat_code, (args.source_dir / f"{sat_code}.html").read_text(encoding="utf-8"))
        else:
            sat_data = scrape_satellite_data(sat_code, url)
        if not sat_data:
            raise RuntimeError(f"{sat_code} 未解析出資料，已停止覆寫 data.js。")
        repaired = repair_maintenance_pairs(sat_data)
        sat_data = dedupe_records(sat_data)
        all_satellite_data.extend(sat_data)
        extra = f"，補完 {repaired} 筆" if repaired else ""
        print(f"-> 向日葵 {sat_code} 號解析完成，共 {len(sat_data)} 筆紀錄{extra}。")

    all_satellite_data = dedupe_records(all_satellite_data)
    print_check(all_satellite_data)
    validate_regression_records(all_satellite_data)
    output_path = write_data_js(all_satellite_data, args.output)
    print(f"\n【完成】已寫入：{output_path}")
    print("請確認網頁載入的 data.js 正是上述路徑。")


if __name__ == "__main__":
    main()

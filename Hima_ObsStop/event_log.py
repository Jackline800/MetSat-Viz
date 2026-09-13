"""Source-preserving parser for JMA's event logs and processing change lists."""

import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment

from event_translation import translate_event, translation_status
from observation_time import _instant, _iso


EVENT_URLS = {sat: f'https://www.data.jma.go.jp/mscweb/ja/oper/event_{sat}.html' for sat in ('H8', 'H9')}
STAMP = re.compile(
    r'(?:(?P<year>\d{4})年\s*)?(?:(?P<month>\d{1,2})月\s*)?'
    r'(?:(?P<day>\d{1,2})日\s*)?'
    r'(?P<hour>\d{1,2})(?::(?P<minute>\d{2})(?::(?P<second>\d{2}))?|(?=\s*UTC))'
    r'\s*(?:UTC)?\s*(?:\(\s*(?P<pcode>P\d+)\s*\))?'
)
SERVICES = ('HimawariCast', 'HimawariCloud', 'アデス')


def normalized(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).strip()


def key_text(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).rstrip('。')


def plain(node):
    clone = BeautifulSoup(str(node), 'html.parser')
    for tag in clone.find_all(['s', 'del', 'strike', 'script', 'style']):
        tag.decompose()
    for br in clone.find_all('br'):
        br.replace_with('\n')
    return '\n'.join(line for part in clone.get_text().splitlines() if (line := normalized(part)))


def own_header(li):
    return plain(''.join(str(child) for child in li.contents if not isinstance(child, Comment)
                         and getattr(child, 'name', None) not in ('ul', 'ol', 'li')))


def source_entries(source_html):
    """Yield complete dated entries even when JMA leaves li/ul tags unclosed."""
    soup = BeautifulSoup(source_html, 'html.parser')
    article = soup.find('article') or soup
    found = {'quality': 0, 'change': 0}
    for dt in article.find_all('dt'):
        heading = dt.find_previous('h2')
        if not heading or '品質低下' not in heading.get_text():
            continue
        parts = []
        for sibling in dt.next_siblings:
            if getattr(sibling, 'name', None) in ('dt', 'h2'):
                break
            parts.append(str(sibling))
        body = BeautifulSoup(''.join(parts), 'html.parser')
        found['quality'] += 1
        yield 'quality', plain(dt), plain(body), body, []

    for li in article.find_all('li'):
        heading = li.find_previous('h2')
        if not heading or '処理方法' not in heading.get_text():
            continue
        header = own_header(li)
        if not re.match(r'\d{4}年\d{1,2}月\d{1,2}日', normalized(header)):
            continue
        clone = BeautifulSoup(str(li), 'html.parser').find('li')
        # A malformed li may own subsequent dated records. Remove those but
        # keep its undated sub-bullets, including the complete change details.
        for nested in list(clone.find_all('li')):
            if nested.parent is not None and re.match(r'\d{4}年', own_header(nested)):
                nested.decompose()
        revisions = [normalized(tag.get_text()) for tag in clone.find_all(['s', 'del', 'strike'])]
        found['change'] += 1
        yield 'change', header, plain(clone), clone, revisions
    if not all(found.values()):
        raise ValueError(f'Event log is missing dated quality/change entries: {found}')


def parse_log_time(text, fallback=None):
    # Parenthesized JST is an alternate display, not a second event endpoint.
    text = re.sub(r'\([^)]*JST[^)]*\)', '', normalized(text))
    matches = list(STAMP.finditer(text))
    if not matches:
        raise ValueError(f'Cannot parse event-log time: {text}')
    if fallback is None:
        date = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if not date:
            raise ValueError(f'Event-log entry has no full date: {text}')
        fallback = datetime(*map(int, date.groups()))
    instants = []
    for match in matches:
        previous = instants[-1] if instants else None
        instant = _instant(match, previous or fallback, previous=previous)
        if match['second']:
            instant = instant.replace(second=int(match['second']))
        instants.append(instant)
    continuous = len(matches) == 2 and bool(re.search(r'[-~～〜]|から', text[matches[0].end():matches[1].start()]))
    if len(matches) > 1 and not continuous:
        intervals = [{'start_utc': _iso(instant), 'end_utc': _iso(instant), 'start_p_code': match['pcode'] or '', 'end_p_code': match['pcode'] or ''}
                     for instant, match in zip(instants, matches)]
        time_type = 'multiple'
    else:
        intervals = [{'start_utc': _iso(instants[0]), 'end_utc': _iso(instants[-1]) if continuous else None,
                      'start_p_code': matches[0]['pcode'] or '', 'end_p_code': matches[-1]['pcode'] or '' if continuous else ''}]
        time_type = 'continuous' if continuous else 'point'
    p_range = re.search(r'\((P\d+)\s*[-~～]\s*(P\d+)\)', text)
    if p_range and continuous:
        intervals[0]['start_p_code'], intervals[0]['end_p_code'] = p_range.groups()
    approximate = '頃' in text
    precision = 'approximate' if approximate else 'second' if any(m['second'] for m in matches) else 'hour' if any(m['minute'] is None for m in matches) else 'minute'
    return {'intervals': intervals, 'time_type': time_type, 'time_precision': precision,
            'start_utc': intervals[0]['start_utc'], 'end_utc': intervals[-1]['end_utc'],
            'start_p_code': intervals[0]['start_p_code'], 'end_p_code': intervals[-1]['end_p_code']}


def attachments(node, url):
    result = []
    for link in node.find_all('a', href=True):
        target = urljoin(url, link['href'])
        if urlparse(target).scheme not in ('https', 'http'):
            continue
        item = {'url': target, 'title_jp': plain(link), 'title_tw': translate_event(plain(link))}
        if item not in result:
            result.append(item)
    return result


def impact_tags(text):
    tags = []
    patterns = {'delay': r'遅れ', 'distribution': r'配信|画像提供|画像の提供',
                'missing': r'欠[損落配]|配信ができ|配信でき|提供ができ',
                'noise': r'ノイズ|階調異常|諧調', 'quality': r'品質|精度|画像異常|性能低下',
                'metadata': r'ヘッダ|ヘッダー|ライン番号'}
    for name, pattern in patterns.items():
        if re.search(pattern, text):
            tags.append(name)
    return tags


def coverage(text):
    text = normalized(text)
    bands = set()
    for match in re.finditer(r'バンド\s*(\d+(?:\s*[、,~～-]\s*\d+)*)', text):
        for part in re.split(r'[、,]', match[1]):
            nums = list(map(int, re.findall(r'\d+', part)))
            bands.update(range(nums[0], nums[-1] + 1))
    regions = [tw for jp, tw in [('全球|フルディスク', '全圓盤'), ('日本域', '日本區域'), ('機動観測', '機動觀測'),
                                ('領域4', '區域4'), ('領域5|領域4[、,]5', '區域5'), ('赤道', '赤道附近'),
                                ('可視', '可見光'), ('近赤外', '近紅外線')] if re.search(jp, text)]
    products = [name for name in ('HimawariCast', 'HimawariCloud', 'HRIT', 'LRIT', 'Navigation Monitor') if name in text]
    if 'ひまわり標準データ' in text:
        products.append('HSD')
    if '全観測画像およびプロダクト' in text:
        regions.append('所有觀測影像與產品')
    return {'bands': sorted(b for b in bands if 1 <= b <= 16), 'regions': regions,
            'services': [s for s in SERVICES if s in text], 'products': products}


def service_intervals(description, timing):
    fallback = datetime.fromisoformat(timing['start_utc'].rstrip('Z'))
    result = []
    # Explicit per-channel periods take precedence over the main header.
    for line in description.splitlines():
        match = re.match(r'\s*[・•]?\s*(HimawariCast|HimawariCloud|アデス)\s+(.*)', normalized(line))
        if match and STAMP.search(match[2]):
            parsed = parse_log_time(match[2], fallback)
            result.append({'service': match[1], 'time_raw': match[2], **parsed['intervals'][0], 'basis': 'explicit'})
    # Shared service exception, e.g. H8 2020-03-23 (all three resume at 20:30).
    for sentence in description.split('。'):
        names = [s for s in SERVICES if s in sentence]
        if names and ('間の' in sentence or '配信を再開' in sentence):
            segment = re.search(r'(?:\d{1,2}月\s*\d{1,2}日\s*)?\d{1,2}:\d{2}.*?間の', normalized(sentence))
            if segment:
                raw = segment.group().removesuffix('間の')
                parsed = parse_log_time(raw, fallback)
                for name in names:
                    result.append({'service': name, 'time_raw': raw, **parsed['intervals'][0], 'basis': 'explicit'})
    explicit = {r['service'] for r in result}
    for name in SERVICES:
        if name in description and name not in explicit:
            for period in timing['intervals']:
                result.append({'service': name, 'time_raw': '', **period, 'basis': 'header'})
    return result


def parse_event_log(sat, source_html):
    url = EVENT_URLS[sat]
    records = []
    for section, header, description, node, revisions in source_entries(source_html):
        timing = parse_log_time(header)
        start = datetime.fromisoformat(timing['start_utc'].rstrip('Z'))
        anticipated = section == 'quality' and bool(re.search(r'予想されています|発生すると予想', description))
        uncertain = bool(re.search(r'可能性|調査中', description))
        intermittent = bool(re.search(r'断続的', header + description))
        category = 'change' if section == 'change' else 'pause' if '観測を休止' in description else 'quality'
        role = 'effective' if section == 'change' else 'announcement' if anticipated else 'distribution' if any(s in description for s in SERVICES) or re.search(r'配信|画像提供|画像の提供', description) else 'event'
        # Header timestamps describe the event envelope. Never infer lost images.
        if section == 'change':
            first_time = STAMP.search(header)
            short_title = re.sub(r'^\s*\([^)]*JST[^)]*\)\s*', '', header[first_time.end():]).strip(' ()）')
        else:
            short_title = ''
        source = {'kind': 'event_log', 'url': url + ('#change' if section == 'change' else '#data'),
                  'section': section, 'time_raw': header, 'description_jp': description, 'time_role': role,
                  'start_utc': timing['start_utc'], 'end_utc': timing['end_utc'],
                  'start_p_code': timing['start_p_code'], 'end_p_code': timing['end_p_code']}
        record = {
            'id': f'{sat}-log-' + hashlib.sha256((section + key_text(header) + key_text(description)).encode()).hexdigest()[:16],
            'satellite': sat, 'ad_year': start.year, 'roc_year': start.year - 1911, 'month': start.month,
            'date_raw': f'{start.year}年{start.month}月{start.day}日', 'time_raw': header,
            'record_type': 'change' if section == 'change' else 'notice' if anticipated else 'event',
            'category': category, 'categories': [category], 'status': 'anticipated' if anticipated else 'reported',
            'uncertainty': uncertain, 'temporal_pattern': 'intermittent' if intermittent else 'onset' if timing['time_type'] == 'point' and '出力不安定' in description else timing['time_type'],
            'time_role': role, 'event_count': 0 if section == 'change' or anticipated else 1,
            'change_count': int(section == 'change'), 'notice_count': int(anticipated),
            'observation_count': None, 'covered_slot_count': None, 'date_type': '期間' if timing['time_type'] == 'continuous' else '單日',
            'event_jp': description, 'event_tw': translate_event(description),
            'title_tw': translate_event(short_title) if short_title else '', 'memo': '', 'memo_tw': '',
            'sources': [source], 'attachments': attachments(node, url), 'revised_dates_jp': revisions,
            'impact_tags': impact_tags(description), 'excluded_dates': [], 'fd': '', 'reg': '',
            **timing, **coverage(description),
        }
        record['p_code'] = record['start_p_code']
        record['service_intervals'] = service_intervals(description, timing) if section == 'quality' else []
        record['translation_status'] = translation_status(description)
        records.append(record)
    return records

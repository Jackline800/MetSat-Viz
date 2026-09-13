"""Combine history and event-log reports without losing their individual claims."""

import copy
import hashlib
import re
from datetime import datetime

from event_log import coverage, impact_tags, key_text
from event_translation import translation_status


ROUTINE = {'東西軌道制御', '南北軌道制御', '放射計太陽校正', '衛星メンテナンス', '衛星保守作業', 'システムメンテナンス'}


def classify_history(record):
    if record.get('record_type') == 'notice':
        return 'notice'
    return 'pause' if record['event_jp'] in ROUTINE else 'quality'


def title_for(record):
    if record.get('title_tw'):
        return record['title_tw']
    if record['category'] == 'pause':
        return record['event_tw'] if record['event_jp'] in ROUTINE else '衛星維護延長／觀測休止'
    if record['category'] == 'notice':
        return '衛星觀測任務交接公告'
    tags = record['impact_tags']
    label = ('影像提供延遲' if 'delay' in tags else '資料標頭資訊異常' if 'metadata' in tags
             else '影像雜訊／色階異常' if 'noise' in tags else '配發中斷／資料缺漏' if 'distribution' in tags and 'missing' in tags
             else '影像缺漏' if 'missing' in tags else '影像品質下降')
    if record.get('status') == 'anticipated':
        label = '預期影響：' + label
    if record.get('bands'):
        label = '第' + '、'.join(map(str, record['bands'])) + '頻道 · ' + label
    return label


def decorate_history(record):
    r = copy.deepcopy(record)
    category = classify_history(r)
    r['category'] = category
    r['categories'] = [category]
    raw = r['event_jp'] + '\n' + r.get('memo', '')
    r['id'] = r['satellite'] + '-history-' + hashlib.sha256(key_text(
        f"{r['ad_year']}/{r['month']}/{r.get('date_calc_raw', r['date_raw'])}/{r['time_raw']}/{r['event_jp']}"
    ).encode()).hexdigest()[:16]
    r['sources'] = [{'kind': 'pause_history', 'url': f"https://www.data.jma.go.jp/mscweb/ja/oper/opr_pause_{r['satellite']}.html",
                     'section': 'pause', 'date_raw': r['date_raw'], 'time_raw': r['time_raw'], 'description_jp': raw.strip(),
                     'time_role': 'announcement' if category == 'notice' else 'observation',
                     'start_utc': r.get('start_utc'), 'end_utc': r.get('end_utc'),
                     'start_p_code': r.get('start_p_code'), 'end_p_code': r.get('end_p_code')}]
    r['time_role'] = 'announcement' if category == 'notice' else 'observation'
    r['status'] = 'reported'
    r['temporal_pattern'] = r.get('time_type', 'unknown')
    r['impact_tags'] = impact_tags(raw)
    r.update(coverage(raw))
    r['service_intervals'] = []
    r['attachments'] = []
    if r.get('related_url'):
        r['attachments'].append({'url': r['related_url'], 'title_tw': '相關衛星觀測休止履歷', 'title_jp': ''})
    r['covered_slot_count'] = r.get('observation_count')
    # Interval coverage cannot establish how many products/channels were lost.
    if category == 'quality':
        r['event_count'] = int(bool(r.get('event_count')))
        r['observation_count'] = None
    r['translation_status'] = ('translated' if all(translation_status(text) == 'translated'
                               for text in (r['event_jp'], r.get('memo', ''))) else 'partial')
    r['change_count'] = 0
    r['notice_count'] = int(category == 'notice')
    r['title_tw'] = title_for(r)
    return r


def cause_groups(text):
    groups = set()
    if re.search(r'地上|テレメトリ|通信|衛星回線', text):
        groups.add('ground')
    if re.search(r'衛星(?:本体)?(?:の)?(?:障害|異常)|AHI|検出素子', text):
        groups.add('satellite')
    return groups


def compatible(history, log):
    # A scheduled control/calibration must not be merged into a simultaneous
    # quality problem simply because they share a timestamp.
    if history['category'] != 'quality' or log['category'] != 'quality' or log['record_type'] != 'event':
        return False
    if history.get('time_type') not in ('point', 'continuous') or history.get('event_count') != 1:
        return False
    for field in ('bands', 'services'):
        if history.get(field) and log.get(field) and not set(history[field]) & set(log[field]):
            return False
    hcause = cause_groups(history['event_jp'] + history.get('memo', ''))
    lcause = cause_groups(log['event_jp'])
    if hcause and lcause and not hcause & lcause:
        return False
    htags, ltags = set(history['impact_tags']), set(log['impact_tags'])
    # Image quality descriptions often become more specific in the log.
    family = {'noise', 'quality', 'metadata'}
    return bool(htags & ltags or htags & family and ltags & family)


def interval(record):
    if not record.get('start_utc'):
        return None
    start = datetime.fromisoformat(record['start_utc'].replace('Z', '+00:00'))
    end = datetime.fromisoformat((record.get('end_utc') or record['start_utc']).replace('Z', '+00:00'))
    return start, end


def overlaps(a, b):
    # Discrete observations do not include the gap between those points.
    aa = [interval(p) for p in a.get('intervals', [a])]
    bb = [interval(p) for p in b.get('intervals', [b])]
    return any(x and y and max(x[0], y[0]) <= min(x[1], y[1]) for x in aa for y in bb)


def build_catalog(history, logs):
    records = [decorate_history(r) for r in history]
    for log_source in logs:
        log = copy.deepcopy(log_source)
        log['title_tw'] = title_for(log)
        candidates = [h for h in records if h['satellite'] == log['satellite']
                      and any(s['kind'] == 'pause_history' for s in h['sources'])
                      and not any(s['kind'] == 'event_log' for s in h['sources'])
                      and compatible(h, log) and interval(h) == interval(log)
                      and log['time_type'] != 'multiple' and log['time_precision'] not in ('hour', 'approximate')]
        if len(candidates) == 1:
            target = candidates[0]
            sources = target['sources'] + log['sources']
            previous_codes = {k: target.get(k) for k in ('p_code', 'start_p_code', 'end_p_code')}
            retained = {k: target.get(k) for k in ('id', 'covered_slot_count', 'fd', 'reg', 'affected_dates', 'affected_dates_iso')}
            target.update(log)
            target.update(retained)
            target['sources'] = sources
            for key, code in previous_codes.items():
                if not target.get(key):
                    target[key] = code
            target['merge_basis'] = '相同衛星、相同起迄時間，且影響類型與原因相容；保留兩份來源記載。'
        else:
            records.append(log)

    # Possible matches remain separate; a different service/time claim must
    # never silently replace another report. These links do not change counts.
    quality = [r for r in records if r['category'] == 'quality' and r['record_type'] == 'event']
    for i, a in enumerate(quality):
        ai = interval(a)
        if not ai:
            continue
        for b in quality[i + 1:]:
            bi = interval(b)
            if not bi or a['satellite'] != b['satellite']:
                continue
            if overlaps(a, b):
                a.setdefault('related_events', []).append({'id': b['id'], 'reason': '時段重疊，保留各來源記載'})
                b.setdefault('related_events', []).append({'id': a['id'], 'reason': '時段重疊，保留各來源記載'})
    return sorted(records, key=lambda r: (r.get('start_utc') or '', r['satellite'], r['id']), reverse=True)

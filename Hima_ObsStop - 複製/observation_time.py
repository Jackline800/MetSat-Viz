"""Parse JMA observation times without deriving clocks from historical P codes."""

import calendar
import re
from datetime import datetime, timedelta


RANGE = r"[～〜~－―–-]"
ENDPOINT = re.compile(
    r"(?:(?P<year>\d{4})年\s*)?"
    r"(?:(?P<month>\d{1,2})月\s*)?"
    r"(?:(?P<day>\d{1,2})日\s*)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2})|(?=\s*UTC))"
    r"\s*(?:UTC)?\s*(?:[（(]\s*(?P<pcode>P\d+)\s*[）)])?"
)
P_RANGE = re.compile(r"[（(]\s*(P\d+)\s*" + RANGE + r"\s*(P\d+)\s*[）)]")
TIME_PREFIX = re.compile(
    r"^\s*(?:" + ENDPOINT.pattern + r")"
    # Use the endpoint without named groups when embedding it a second time.
    + r"(?:\s*" + RANGE + r"\s*"
    + re.sub(r"\(\?P<\w+>", "(?:", ENDPOINT.pattern) + r")?"
    + r"(?:\s*" + P_RANGE.pattern + r")?"
)


def time_entries(text):
    """A line break may continue a range/P-code, or start another observation."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        continuation = entries and (
            re.search(RANGE + r"\s*$", entries[-1])
            or re.match(r"^" + RANGE, line)
            or not ENDPOINT.search(line)
        )
        if continuation:
            entries[-1] += " " + line
        else:
            entries.append(line)
    return entries


def extract_event_time(event_text):
    """Older quality incidents put the time in the event column."""
    match = TIME_PREFIX.match(event_text)
    if not match:
        return "", event_text
    return match.group().strip(), event_text[match.end():].strip()


def date_instances(text, year, month):
    if "毎日" in text:
        return [datetime(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]
    match = re.search(
        r"(?:(\d{1,2})月\s*)?(\d{1,2})日?\s*" + RANGE
        + r"\s*(?:(\d{1,2})月\s*)?(\d{1,2})日?", text
    )
    if match:
        sm, sd, em, ed = match.groups()
        sm = int(sm or month)
        em = int(em or sm)
        start = datetime(year, sm, int(sd))
        end_year = year + int(em < sm)
        if not match.group(3) and int(ed) < int(sd):
            em = sm % 12 + 1
            end_year = year + int(em < sm)
        # JMA has published monthly maintenance as e.g. November 1–31.
        # Only real calendar dates can be affected; keep the raw text upstream.
        end = datetime(end_year, em, min(int(ed), calendar.monthrange(end_year, em)[1]))
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    dates = []
    current_month = month
    for match in re.finditer(r"(?:(\d{1,2})月\s*)?((?:\d{1,2}\s*[、,，・]\s*)*\d{1,2})日", text):
        current_month = int(match.group(1) or current_month)
        dates.extend(datetime(year, current_month, int(day)) for day in re.findall(r"\d+", match.group(2)))
    return sorted(set(dates))


def _instant(match, fallback, previous=None):
    year = int(match['year'] or fallback.year)
    month = int(match['month'] or fallback.month)
    day = int(match['day'] or fallback.day)
    if previous and not match['year'] and match['month'] and month < previous.month:
        year += 1
    if previous and match['day'] and not match['month'] and day < previous.day:
        month = previous.month % 12 + 1
        year = previous.year + int(month == 1)
    result = datetime(year, month, day, int(match['hour']), int(match['minute'] or 0))
    if previous and result < previous and not match['day'] and not match['month']:
        result += timedelta(days=1)
    if previous and result < previous:
        raise ValueError(f"Observation range ends before it starts: {previous} > {result}")
    return result


def _iso(instant):
    return instant.isoformat(timespec='seconds') + 'Z'


def add_time_metadata(record, dates):
    """Event counts and inclusive 10-minute affected slots are separate metrics."""
    record['record_type'] = record.get('record_type', 'event')
    record['observation_count'] = None
    record['time_type'] = 'unknown'
    record['affected_dates_iso'] = [d.date().isoformat() for d in dates]
    matches = list(ENDPOINT.finditer(record['time_raw']))
    if not dates and record['event_count'] == 0:
        record['observation_count'] = 0
    if not dates or not matches:
        return record
    start_match = matches[0]
    start = _instant(start_match, dates[0])
    record['start_utc'] = _iso(start)
    record['start_p_code'] = start_match['pcode'] or ''
    p_range = P_RANGE.search(record['time_raw'])
    if p_range:
        record['start_p_code'] = p_range[1]
    record['p_code'] = record['start_p_code']
    record['time_type'] = 'point'
    record['time_precision'] = 'minute' if start_match['minute'] is not None else 'hour'
    record['observation_count'] = len(dates) if start_match['minute'] is not None else None
    if len(matches) >= 2:
        between = record['time_raw'][start_match.end():matches[1].start()]
        if not re.search(RANGE, between):
            record['time_type'] = 'unknown'
            record['observation_count'] = None
            return record
        end_match = matches[1]
        end = _instant(end_match, start, previous=start)
        record['end_utc'] = _iso(end)
        record['end_p_code'] = end_match['pcode'] or (p_range[2] if p_range else '')
        # A date range + a clock range without endpoint dates repeats each day.
        recurring = len(dates) > 1 and not (start_match['day'] or end_match['day'])
        record['time_type'] = 'recurring_range' if recurring else 'continuous'
        record['date_type'] = '期間'
        record['event_count'] = len(dates) if recurring else 1
        span_minutes = int((end - start).total_seconds() / 60)
        exact = start_match['minute'] is not None and end_match['minute'] is not None
        record['time_precision'] = 'minute' if exact else 'hour'
        record['observation_count'] = ((span_minutes // 10 + 1) * record['event_count']
                                       if exact and span_minutes % 10 == 0 else None)
        if not recurring:
            dates = [datetime(start.year, start.month, start.day) + timedelta(days=i)
                     for i in range((end.date() - start.date()).days + 1)]
        else:
            dates = sorted({date + timedelta(days=i) for date in dates
                            for i in range((end.date() - start.date()).days + 1)})
        record['affected_dates_iso'] = [d.date().isoformat() for d in dates]
        record['affected_dates'] = sorted({d.day for d in dates if d.year == start.year and d.month == start.month})
        record['ad_year'], record['month'] = start.year, start.month
        record['roc_year'] = start.year - 1911
    elif re.search(RANGE, record['time_raw'][start_match.end():]):
        record['time_type'] = 'open_range'
        record['observation_count'] = None
    if record['record_type'] == 'notice':
        record['event_count'] = record['observation_count'] = 0
        record['affected_dates'] = []
        record['affected_dates_iso'] = []
    return record

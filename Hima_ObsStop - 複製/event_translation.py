"""Translate JMA observation-history labels and notices into Traditional Chinese.

These are deliberately phrase/sentence rules, not word substitutions: in
``A に代わり B で観測`` it is B that takes over from A. Callers must keep
``event_jp`` / ``memo_jp`` alongside the returned display text. Unknown text is
left intact so that a new JMA description cannot acquire an invented meaning.
"""

import re
import unicodedata


EVENT_TRANSLATIONS = {
    "東西軌道制御": "東西軌道控制",
    "南北軌道制御": "南北軌道控制",
    "放射計太陽校正": "輻射計太陽校正",
    "衛星メンテナンス": "衛星例行維護",
    "衛星保守作業": "衛星檢修作業",
    "システムメンテナンス": "系統維護",
    # Missing distribution does not necessarily mean the observation failed.
    "欠配": "資料未配發（欠配）",
    "画像品質低下": "影像品質下降",
    "画像品質の低下": "影像品質下降",
    "画像データ異常": "影像資料異常",
    "画像異常": "影像異常",
    "画像の一部欠損": "影像部分缺漏",
    "観測休止": "暫停觀測",
}

CAUSE_TRANSLATIONS = {
    "地上システム異常": "地面系統異常",
    "地上システムの異常": "地面系統異常",
    "地上システム障害": "地面系統故障",
    "地上システムの障害": "地面系統故障",
    "衛星異常": "衛星異常",
    "衛星障害": "衛星故障",
    "衛星本体の障害": "衛星本體故障",
    "衛星および地上システム障害": "衛星及地面系統故障",
    "衛星及び地上システム障害": "衛星及地面系統故障",
    "衛星及び地上システムの障害": "衛星及地面系統故障",
    "衛星および地上システムの障害": "衛星及地面系統故障",
    "中止": "取消",
    "原因調査中": "原因調查中",
    "原因は調査中です": "原因仍在調查中",
    "AHIの検出素子異常": "AHI 偵測元件異常",
}


def _match_key(text):
    # HTML may split a sentence across tags or use full-width digits/spaces.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).rstrip("。,，")


_PHRASES = {
    _match_key(jp): tw
    for jp, tw in {**EVENT_TRANSLATIONS, **CAUSE_TRANSLATIONS}.items()
}
_DATE_TIME = (
    r"(?P<date>\d{4}年\d{1,2}月\d{1,2}日)"
    r"(?P<time>\d{1,2}:\d{2})UTC(?:\((?P<pcode>P\d+)\))?"
)
_HANDOVER = re.compile(
    _DATE_TIME
    + r"から[、,]?ひまわり(?P<old>\d+)号に代わり[、,]?"
    r"ひまわり(?P<new>\d+)号で観測を行います"
)
_OBSERVE_FROM = re.compile(
    _DATE_TIME + r"から[、,]?ひまわり(?P<new>\d+)号で観測を行います"
)
_START_OPERATIONS = re.compile(
    r"ひまわり(?P<new>\d+)号は"
    + _DATE_TIME
    + r"から[、,]?ひまわり(?P<old>\d+)号に代わり[、,]?観測運用を開始します"
)
_HISTORY_LINK = re.compile(r"ひまわり(?P<sat>\d+)号観測休止履歴はこちら")
_SCOPED_IMAGE = re.compile(
    r"(?P<scope>日本域観測|機動観測|フルディスク)(?:\((?P<image>\d+)枚目\))?(?P<event>.*)"
)
_BAND_IMAGE = re.compile(r"バンド(?P<band>\d+)(?P<event>.*)")
_UPDATE_NOTE = re.compile(r"(?P<date>\d{1,2}/\d{1,2})(?P<action>追加|変更|訂正)")


def _timestamp(match):
    result = f"{match['date']} {match['time']} UTC"
    if match["pcode"]:
        result += f"（{match['pcode']}）"
    return result


def _translate_clause(text):
    key = _match_key(text)
    if key in _PHRASES:
        return _PHRASES[key]

    match = _HANDOVER.fullmatch(key)
    if match:
        return (
            f"自 {_timestamp(match)}起，改由向日葵{match['new']}號"
            f"接替向日葵{match['old']}號進行觀測。"
        )
    match = _START_OPERATIONS.fullmatch(key)
    if match:
        return (
            f"向日葵{match['new']}號自 {_timestamp(match)}起，"
            f"接替向日葵{match['old']}號，開始執行觀測任務。"
        )
    match = _OBSERVE_FROM.fullmatch(key)
    if match:
        return f"自 {_timestamp(match)}起，由向日葵{match['new']}號進行觀測。"
    match = _HISTORY_LINK.fullmatch(key)
    if match:
        return f"向日葵{match['sat']}號觀測休止紀錄請見此處"

    match = _SCOPED_IMAGE.fullmatch(key)
    if match and (not match["event"] or match["event"] in _PHRASES):
        result = {"日本域観測": "日本區域觀測", "機動観測": "機動觀測", "フルディスク": "全圓盤"}[match["scope"]]
        if match["image"]:
            result += f"（第{match['image']}張影像）"
        if match["event"]:
            result += f"：{_PHRASES[match['event']]}"
        return result

    match = _BAND_IMAGE.fullmatch(key)
    if match and match["event"] in _PHRASES:
        return f"第{match['band']}頻道：{_PHRASES[match['event']]}"

    match = _UPDATE_NOTE.fullmatch(key)
    if match:
        action = {"追加": "新增", "変更": "變更", "訂正": "更正"}[match["action"]]
        return f"{match['date']} {action}"
    return None


def translate_event(text):
    """Return display text; unknown clauses retain their original Japanese.

    Complete-cell matching comes first, preserving notices and labels whose
    wording is divided by HTML line breaks. Only if that fails are independent
    sentences/lines translated separately.
    """
    if text is None:
        return ""
    source = str(text).strip()
    if not source:
        return ""
    translated = _translate_clause(source)
    if translated is not None:
        return translated

    sentences = [part.strip() for part in re.split(r"(?<=[。！？])\s*", source) if part.strip()]
    if len(sentences) > 1:
        return "\n".join(translate_event(part) for part in sentences)
    lines = [part.strip() for part in source.splitlines() if part.strip()]
    if len(lines) > 1:
        return "\n".join(translate_event(part) for part in lines)
    return source


def translate_memo(text):
    """Translate the cause/remarks column using the same source-safe rules."""
    return translate_event(text)

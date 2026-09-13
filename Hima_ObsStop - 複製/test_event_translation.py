"""Sentence-meaning regressions from the JMA H8/H9 observation histories."""

import unittest

from event_translation import translate_event, translate_memo


class EventTranslationTest(unittest.TestCase):
    def test_october_2025_h9_handover_to_h8(self):
        source = (
            "2025年10月12日 13:00 UTC（P079）から、"
            "ひまわり9号に代わり、ひまわり8号で観測を行います。"
        )
        self.assertEqual(
            translate_event(source),
            "自 2025年10月12日 13:00 UTC（P079）起，改由向日葵8號接替向日葵9號進行觀測。",
        )

    def test_november_2025_handover_back_to_h9(self):
        self.assertEqual(
            translate_event(
                "2025年11月26日 05:00 UTC（P030）から、"
                "ひまわり8号に代わり、ひまわり9号で観測を行います。"
            ),
            "自 2025年11月26日 05:00 UTC（P030）起，改由向日葵9號接替向日葵8號進行觀測。",
        )

    def test_2022_start_of_h9_operations_keeps_roles_and_start_time(self):
        self.assertEqual(
            translate_event(
                "ひまわり9号は2022年12月13日 05:00 UTC (P030)から、"
                "ひまわり8号に代わり、観測運用を開始します。"
            ),
            "向日葵9號自 2022年12月13日 05:00 UTC（P030）起，"
            "接替向日葵8號，開始執行觀測任務。",
        )

    def test_notice_without_previous_satellite_does_not_invent_one(self):
        self.assertEqual(
            translate_event("2025年10月12日 13:00 UTC（P079）から、ひまわり8号で観測を行います。"),
            "自 2025年10月12日 13:00 UTC（P079）起，由向日葵8號進行觀測。",
        )

    def test_handover_handles_html_breaks_and_full_width_numbers(self):
        self.assertEqual(
            translate_event(
                "２０２５年１０月１２日　１３：００ UTC（P０７９）から、\n"
                "ひまわり９号に代わり、\nひまわり８号で観測を行います。"
            ),
            "自 2025年10月12日 13:00 UTC（P079）起，改由向日葵8號接替向日葵9號進行觀測。",
        )

    def test_notice_and_history_link_are_separate_complete_clauses(self):
        self.assertEqual(
            translate_event(
                "2025年11月26日 05:00 UTC（P030）から、ひまわり9号で観測を行います。\n"
                "ひまわり9号観測休止履歴はこちら"
            ),
            "自 2025年11月26日 05:00 UTC（P030）起，由向日葵9號進行觀測。\n"
            "向日葵9號觀測休止紀錄請見此處",
        )

    def test_distribution_failure_is_not_claimed_as_observation_failure(self):
        self.assertEqual(translate_event("欠配"), "資料未配發（欠配）")

    def test_nonroutine_event_vocabulary(self):
        cases = [
            ("システムメンテナンス", "系統維護"),
            ("画像品質低下", "影像品質下降"),
            ("画像データ異常", "影像資料異常"),
            ("衛星保守作業", "衛星檢修作業"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(translate_event(source), expected)

    def test_multiline_image_label_keeps_the_image_number_and_failure(self):
        self.assertEqual(
            translate_event("日本域観測（1枚目）\n画像品質低下"),
            "日本區域觀測（第1張影像）：影像品質下降",
        )

    def test_ground_and_satellite_causes_are_distinct(self):
        self.assertEqual(translate_memo("地上システム障害"), "地面系統故障")
        self.assertEqual(translate_memo("地上システム異常"), "地面系統異常")
        self.assertEqual(translate_memo("衛星異常"), "衛星異常")
        self.assertEqual(translate_memo("衛星および地上システム障害"), "衛星及地面系統故障")

    def test_cancelled_and_revised_schedule_memos(self):
        self.assertEqual(translate_memo("中止"), "取消")
        self.assertEqual(translate_memo("4/16訂正"), "4/16 更正")
        self.assertEqual(translate_memo("3/29変更"), "3/29 變更")
        self.assertEqual(translate_memo("11/27追加"), "11/27 新增")

    def test_unknown_future_phrase_is_preserved_without_partial_word_changes(self):
        source = "ひまわり10号から新形式の配信へ移行する予定です。"
        self.assertEqual(translate_event(source), source)
        self.assertEqual(translate_memo("parser補完：依JMA表格原始文字復原"),
                         "parser補完：依JMA表格原始文字復原")

    def test_empty_optional_memo(self):
        self.assertEqual(translate_memo(None), "")
        self.assertEqual(translate_memo(" \n "), "")


if __name__ == "__main__":
    unittest.main()

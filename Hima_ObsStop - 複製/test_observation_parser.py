"""Offline regressions for the different layouts in the JMA H8/H9 histories."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import requests
import update_data_stable as parser


HEADER = '<tr><th>期日</th><th>観測休止</th><th>F.D.</th><th>Reg</th><th>運用・障害</th><th>原因</th></tr>'


def row(date, time, event='欠配', memo='地上システム障害', fd='X', reg='X'):
    return '<tr>' + ''.join(f'<td>{value}</td>' for value in (date, time, fd, reg, event, memo)) + '</tr>'


def parse(rows, heading='令和2年3月', satellite='H8'):
    return parser.parse_satellite_html(satellite, f'<main><table>{heading}{HEADER}{rows}</table></main>')


class ObservationParserTests(unittest.TestCase):
    def test_reported_2020_cross_day_outage_is_45_observations(self):
        records = parse(row('3月23日', '3月23日19:30UTC(P118)～</br>3月24日02:50UTC(P018)'))
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record['start_utc'], '2020-03-23T19:30:00Z')
        self.assertEqual(record['end_utc'], '2020-03-24T02:50:00Z')
        self.assertEqual((record['start_p_code'], record['end_p_code']), ('P118', 'P018'))
        self.assertEqual(record['affected_dates_iso'], ['2020-03-23', '2020-03-24'])
        self.assertEqual(record['affected_dates'], [23, 24])
        self.assertEqual((record['event_count'], record['observation_count']), (1, 45))
        self.assertEqual(record['memo_tw'], '地面系統故障')

    def test_line_break_continues_the_same_range(self):
        record, = parse(row('12月17日', '04:10 UTC(P025)～<br>04:40 UTC(P028)'), '令和元年12月')
        self.assertEqual(record['ad_year'], 2019)
        self.assertEqual(record['observation_count'], 4)

    def test_separate_pcode_line_does_not_become_an_event(self):
        record, = parse(row('1月1日', '00:10～00:40 UTC<br>(P001～P004)'), '平成28年1月')
        self.assertEqual(record['observation_count'], 4)
        self.assertEqual(record['end_p_code'], 'P004')

    def test_hyphen_range_and_inconsistent_pcodes_use_clocks(self):
        record, = parse(row('4月3日', '10:30UTC - 12:20UTC (P064 - P074)'), '平成29年4月')
        self.assertEqual(record['observation_count'], 12)

    def test_multi_day_period_with_endpoint_days_is_one_event(self):
        record, = parse(row('2月13日～14日', '13日02:30(P015)～<br>14日07:20(P044)'), '平成30年2月')
        self.assertEqual((record['event_count'], record['observation_count']), (1, 174))
        self.assertEqual(record['affected_dates'], [13, 14])

    def test_implicit_overnight_and_explicit_year_rollover(self):
        for text in ('23:50 UTC(P143)～00:10 UTC(P001)',
                     '12月31日23:50 UTC(P143)～1月1日00:10 UTC(P001)'):
            with self.subTest(text=text):
                record, = parse(row('12月31日', text), '令和7年12月')
                self.assertEqual(record['affected_dates_iso'], ['2025-12-31', '2026-01-01'])
                self.assertEqual(record['end_utc'], '2026-01-01T00:10:00Z')
                self.assertEqual(record['observation_count'], 3)

    def test_leap_day_and_month_rollover(self):
        record, = parse(row('2月29日', '29日23:50 UTC～1日00:10 UTC'), '令和6年2月')
        self.assertEqual(record['affected_dates_iso'], ['2024-02-29', '2024-03-01'])

    def test_two_distinct_times_remain_two_records(self):
        records = parse(row('3月1日～3日', '02:50 UTC(P017)<br>14:50 UTC(P089)', '衛星メンテナンス', ''))
        self.assertEqual(len(records), 2)
        self.assertEqual([r['event_count'] for r in records], [3, 3])
        self.assertEqual([r['observation_count'] for r in records], [3, 3])

    def test_daily_clock_range_repeats_instead_of_filling_the_gaps(self):
        record, = parse(row('3月1日～3日', '10:00～10:20 UTC'))
        self.assertEqual(record['time_type'], 'recurring_range')
        self.assertEqual((record['event_count'], record['observation_count']), (3, 9))

    def test_maintenance_exclusions_and_orphaned_cells_are_preserved(self):
        orphan = row('6月1日～30日', '14:50 UTC(P089)', '衛星メンテナンス', '', reg='O')
        orphan = orphan.replace('6月1日～30日', '6月1日～30日<br>1、29日を除く').replace('<tr>', '').replace('</tr>', '')
        record, = parse(orphan, '令和8年6月', 'H9')
        self.assertEqual(record['excluded_dates'], [1, 29])
        self.assertEqual(record['observation_count'], 28)

    def test_every_excluded_date_means_zero_not_one(self):
        record, = parse(row('3月1日～2日<br>1、2日を除く', '02:50 UTC(P017)'))
        self.assertEqual(record['event_count'], 0)
        self.assertEqual(record['affected_dates_iso'], [])

    def test_times_inside_event_column_and_band_are_recovered(self):
        record, = parse(row('1月6日-10日', '', '1月6日 19:30UTC (P118) ～1月10日 07:00UTC (P042) バンド8 画像品質低下',
                            'AHIの検出素子異常'), '平成29年1月')
        self.assertEqual(record['observation_count'], 502)
        self.assertEqual(record['event_tw'], '第8頻道：影像品質下降')
        self.assertEqual(record['memo_tw'], 'AHI 偵測元件異常')

    def test_multiline_description_keeps_all_affected_image_types(self):
        record, = parse(row('1月1日', '00:00UTC(P144)',
                            '00:00UTC(P144)<br>フルディスク画像異常,<br>機動観測（4枚目）欠配'), '平成29年1月')
        self.assertEqual(record['event_tw'], '全圓盤：影像異常\n機動觀測（第4張影像）：資料未配發（欠配）')
        self.assertEqual(record['observation_count'], 1)

    def test_notice_is_one_translated_announcement_and_zero_incidents(self):
        notice = ('2025年10月12日 13:00 UTC（P079）から、ひまわり9号に代わり、ひまわり8号で観測を行います。'
                  '<br><a href="/mscweb/ja/oper/opr_pause_H8.html">ひまわり8号観測休止履歴はこちら</a>')
        record, = parse(f'<tr><td colspan="6">{notice}</td></tr>', '令和7年10月', 'H9')
        self.assertEqual(record['record_type'], 'notice')
        self.assertIn('改由向日葵8號接替向日葵9號進行觀測', record['event_tw'])
        self.assertEqual((record['event_count'], record['observation_count']), (0, 0))
        self.assertEqual((record['fd'], record['reg']), ('', ''))
        self.assertEqual(record['related_url'], parser.URLS['H8'])

    def test_table_year_heading_does_not_inherit_the_previous_year(self):
        html = '<main><h2>令和8年</h2>'
        for heading in ('令和元年12月', '平成31年1月'):
            html += f'<table>{heading}{HEADER}' + row('1日', '02:50UTC(P017)') + '</table>'
        records = parser.parse_satellite_html('H8', html + '</main>')
        self.assertEqual([(r['ad_year'], r['month'], r['era_year']) for r in records],
                         [(2019, 12, '令和1年'), (2019, 1, '平成31年')])

    def test_deleted_revision_and_cancelled_rows_are_not_counted(self):
        revised = row('<s>3月30日</s><br>3月31日', '<s>21:50UTC(P131)</s><br>02:50UTC(P017)', '東西軌道制御')
        cancelled = row('<s>3月2日</s>', '<s>07:20UTC(P044)</s>', '<s>東西軌道制御</s>', '中止')
        records = parse(revised + cancelled)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['affected_dates'], [31])
        self.assertNotIn('P131', records[0]['time_raw'])

    def test_rowspan_and_inline_tags_do_not_split_observations(self):
        rows = ('<tr><td rowspan="2">3月1日</td><td>02:<span>50</span> UTC(P017)</td>'
                '<td>X</td><td>O</td><td rowspan="2">衛星メンテナンス</td><td></td></tr>'
                '<tr><td>14:50 UTC(P089)</td><td>X</td><td>O</td><td></td></tr>')
        records = parse(rows)
        self.assertEqual([r['p_code'] for r in records], ['P017', 'P089'])

    def test_monthly_date_typo_cannot_add_nonexistent_november_day(self):
        record, = parse(row('11月1日～31日', '02:50 UTC(P017)'), '令和元年11月')
        self.assertEqual(record['event_count'], 30)
        self.assertEqual(record['date_raw'], '11月1日～31日')

    def test_hour_only_and_open_ranges_do_not_claim_an_exact_count(self):
        for text in ('20UTC～23UTC', '04:10 UTC(P025)～'):
            with self.subTest(text=text):
                record, = parse(row('3月1日', text))
                self.assertIsNone(record['observation_count'])

    def test_http_failure_and_missing_satellite_cannot_overwrite_data(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'data.js'
            target.write_text('existing data', encoding='utf-8')
            response = Mock()
            response.raise_for_status.side_effect = requests.HTTPError('503')
            with patch.object(parser.requests, 'get', return_value=response):
                with self.assertRaises(requests.HTTPError):
                    parser.scrape_satellite_data('H8', parser.URLS['H8'])
            with patch('sys.argv', ['update_data_stable.py', '--output', str(target)]), \
                 patch.object(parser, 'scrape_satellite_data', return_value=[]):
                with self.assertRaises(RuntimeError):
                    parser.main()
            self.assertEqual(target.read_text(encoding='utf-8'), 'existing data')


if __name__ == '__main__':
    unittest.main()

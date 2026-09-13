"""Offline regressions against JMA event-log snapshots retrieved 2026-09-11."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import update_data_stable as updater
from event_catalog import build_catalog, decorate_history
from event_log import parse_event_log, parse_log_time, coverage
from event_translation import translate_event, translation_status
from test_observation_parser import parse, row


FIXTURES = Path(__file__).with_name('fixtures')


class EventLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs = {sat: parse_event_log(sat, (FIXTURES / f'{sat}_event.html').read_text(encoding='utf-8'))
                    for sat in ('H8', 'H9')}

    def record(self, sat, start):
        matches = [r for r in self.logs[sat] if r['start_utc'].startswith(start)]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_all_dated_records_survive_malformed_lists(self):
        for sat, quality, changes in [('H8', 72, 10), ('H9', 28, 3)]:
            with self.subTest(sat=sat):
                logs = self.logs[sat]
                self.assertEqual(sum(r['category'] == 'change' for r in logs), changes)
                self.assertEqual(len(logs), quality + changes)
                self.assertEqual(len({r['id'] for r in logs}), len(logs))
        change = self.record('H8', '2017-07-25')
        self.assertIn('隨時間變化', change['event_tw'])
        self.assertIn('校正一次係數', change['event_tw'])
        self.assertNotIn('2016年', change['event_jp'])
        self.assertEqual(len(change['attachments']), 1)

    def test_revision_and_jst_do_not_create_an_extra_event_or_endpoint(self):
        r = self.record('H9', '2025-12-16')
        self.assertEqual(r['start_utc'], '2025-12-16T07:00:00Z')
        self.assertIsNone(r['end_utc'])
        self.assertEqual(r['time_role'], 'effective')
        self.assertIn('2025年10月21日', r['revised_dates_jp'][0])
        self.assertFalse(any(r['start_utc'].startswith('2025-10-21') for r in self.logs['H9']))
        self.assertEqual(self.record('H8', '2021-07-15')['revised_dates_jp'], ['2021年7月12日'])

    def test_comments_never_leak_into_change_titles(self):
        for r in self.logs['H8'] + self.logs['H9']:
            self.assertNotIn('====', r['title_tw'])
            self.assertNotIn('<!--', r['event_jp'])

    def test_complete_current_log_descriptions_and_titles_have_translations(self):
        for r in self.logs['H8'] + self.logs['H9']:
            with self.subTest(id=r['id']):
                self.assertEqual(r['translation_status'], 'translated')
                self.assertNotRegex((r['event_tw'] + r['title_tw']).replace('アデス', ''), '[ぁ-んァ-ヴ]')
                self.assertTrue(r['sources'][0]['description_jp'])

    def test_discrete_points_do_not_become_a_continuous_outage(self):
        r = self.record('H9', '2023-02-02')
        self.assertEqual(r['time_type'], 'multiple')
        self.assertEqual([p['start_utc'] for p in r['intervals']], ['2023-02-02T07:10:00Z', '2023-02-02T07:50:00Z'])
        self.assertEqual([p['start_p_code'] for p in r['intervals']], ['P043', 'P047'])
        self.assertIsNone(r['observation_count'])
        self.assertEqual(len(r['service_intervals']), 2)

    def test_2020_cross_day_event_preserves_earlier_channel_recovery(self):
        log = self.record('H8', '2020-03-23')
        history = parse(row('3月23日', '3月23日19:30UTC(P118)～<br>3月24日02:50UTC(P018)'))
        merged, = build_catalog(history, [log])
        self.assertEqual(merged['end_utc'], '2020-03-24T02:50:00Z')
        self.assertEqual((merged['start_p_code'], merged['end_p_code']), ('P118', 'P018'))
        self.assertEqual(merged['covered_slot_count'], 45)
        self.assertIsNone(merged['observation_count'])
        self.assertEqual(merged['event_count'], 1)
        self.assertEqual(len(merged['sources']), 2)
        self.assertEqual({s['service'] for s in merged['service_intervals']}, {'HimawariCast', 'HimawariCloud', 'アデス'})
        self.assertEqual({s['end_utc'] for s in merged['service_intervals']}, {'2020-03-23T20:30:00Z'})
        self.assertEqual({s['basis'] for s in merged['service_intervals']}, {'explicit'})
        self.assertEqual(merged['sources'][0]['time_role'], 'observation')
        self.assertEqual(merged['sources'][1]['time_role'], 'distribution')

    def test_services_can_start_before_the_header_and_end_differently(self):
        r = self.record('H8', '2022-02-18')
        self.assertEqual(r['start_utc'], '2022-02-18T08:36:00Z')
        periods = {s['service']: s for s in r['service_intervals']}
        self.assertEqual(periods['HimawariCast']['start_utc'], '2022-02-18T08:30:00Z')
        self.assertEqual(periods['HimawariCast']['end_utc'], '2022-02-18T09:20:00Z')
        self.assertEqual(periods['HimawariCloud']['end_utc'], '2022-02-18T09:30:00Z')
        r = self.record('H8', '2021-11-11')
        self.assertEqual([s['end_utc'] for s in r['service_intervals']], ['2021-11-11T07:20:00Z', '2021-11-11T07:10:00Z'])

    def test_anticipated_moon_impact_is_an_announcement(self):
        r = self.record('H9', '2025-02-14')
        self.assertEqual((r['status'], r['record_type'], r['event_count']), ('anticipated', 'notice', 0))
        self.assertEqual(r['notice_count'], 1)
        self.assertIn('預期', r['event_tw'])
        self.assertTrue(r['attachments'])

    def test_maintenance_extension_is_an_actual_pause(self):
        r = self.record('H9', '2025-01-21')
        self.assertEqual(r['category'], 'pause')
        self.assertEqual(r['start_utc'], '2025-01-21T16:30:00Z')
        self.assertEqual(r['end_utc'], '2025-01-21T17:40:00Z')
        self.assertIn('延長', r['event_tw'])

    def test_intermittent_and_approximate_periods_have_no_missing_slot_count(self):
        r = self.record('H8', '2018-03-10')
        self.assertEqual(r['temporal_pattern'], 'intermittent')
        self.assertEqual(r['time_precision'], 'approximate')
        self.assertIsNone(r['observation_count'])
        self.assertIsNone(r['covered_slot_count'])

    def test_pcodes_never_supply_a_missing_clock(self):
        r = self.record('H8', '2021-12-16')
        self.assertEqual(r['start_utc'], '2021-12-16T03:00:00Z')
        self.assertEqual(r['start_p_code'], '')
        self.assertIn('可能', r['event_tw'])
        self.assertTrue(r['uncertainty'])

    def test_explicit_year_rollover_and_second_precision(self):
        result = parse_log_time('2025年12月31日 23:59:40 UTC ～ 1月1日 00:00:20 UTC')
        self.assertEqual(result['end_utc'], '2026-01-01T00:00:20Z')
        self.assertEqual(result['time_precision'], 'second')

    def test_band_ranges_keep_each_affected_band(self):
        self.assertEqual(coverage('バンド7、13～16でノイズ')['bands'], [7, 13, 14, 15, 16])

    def test_unknown_and_partial_future_translations_are_flagged(self):
        unknown = '新しい運用について調査しています。'
        self.assertEqual(translate_event(unknown), unknown)
        self.assertEqual(translation_status(unknown), 'source_retained')
        self.assertEqual(translation_status('欠配\n' + unknown), 'partial')
        self.assertEqual(translation_status('衛星異常'), 'translated')

    def test_overlap_different_endpoints_remain_separate_with_links(self):
        log = self.record('H8', '2020-03-23')
        history = parse(row('3月23日', '3月23日19:30UTC～3月24日02:40UTC'))
        result = build_catalog(history, [log])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(len(r['sources']) == 1 and r['related_events'] for r in result))

    def test_same_clock_different_cause_or_scope_is_not_merged(self):
        original = self.record('H8', '2020-03-23')
        history = parse(row('3月23日', '3月23日19:30UTC～3月24日02:50UTC'))
        for fields in ({'event_jp': '衛星本体の障害により欠配'}, {'bands': [12]}):
            with self.subTest(fields=fields):
                log = copy.deepcopy(original)
                log.update(fields)
                data = copy.deepcopy(history)
                if 'bands' in fields:
                    data[0]['event_jp'] = 'バンド8 欠配'
                self.assertEqual(len(build_catalog(data, [log])), 2)

    def test_routine_maintenance_is_not_merged_into_quality(self):
        history = parse(row('3月23日', '3月23日19:30UTC～3月24日02:50UTC', '衛星メンテナンス', ''))
        self.assertEqual(len(build_catalog(history, [self.record('H8', '2020-03-23')])), 2)

    def test_gap_between_discrete_points_is_not_an_overlap(self):
        history = parse(row('2月2日', '07:30 UTC', '欠配'), '令和5年2月', 'H9')
        result = build_catalog(history, [self.record('H9', '2023-02-02')])
        self.assertEqual(len(result), 2)
        self.assertFalse(any(r.get('related_events') for r in result))

    def test_excluded_record_stays_zero_after_classification(self):
        record, = parse(row('3月1日～2日<br>1、2日を除く', '02:50 UTC(P017)'))
        self.assertEqual(decorate_history(record)['event_count'], 0)

    def test_event_log_failure_preserves_the_existing_output(self):
        history = parse(row('3月23日', '19:30UTC(P118)'))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'data.js'
            output.write_text('previous valid data', encoding='utf-8')
            with patch('sys.argv', ['update_data_stable.py', '--output', str(output)]), \
                 patch.object(updater, 'scrape_satellite_data', return_value=history), \
                 patch.object(updater, 'fetch_html', return_value='<article>changed layout</article>'):
                with self.assertRaises(ValueError):
                    updater.main()
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous valid data')

    def test_offline_mode_requires_the_event_logs_as_well(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'data.js'
            output.write_text('previous valid data', encoding='utf-8')
            (Path(folder) / 'H9_pause.html').write_text('<main></main>', encoding='utf-8')
            with patch('sys.argv', ['update_data_stable.py', '--source-dir', folder, '--output', str(output)]), \
                 patch.object(updater, 'parse_satellite_html', return_value=parse(row('3月23日', '19:30UTC'))):
                with self.assertRaises(FileNotFoundError):
                    updater.main()
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous valid data')


if __name__ == '__main__':
    unittest.main()

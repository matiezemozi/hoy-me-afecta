"""Offline DPEC parser + collector integration tests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from dpec_corrientes import collect_dpec, extract_dpec_bulletins, fetch_dpec_html
from collector import collect

STAMP = '2026-11-04T18:00:03Z'  # Argentina 15:00 Nov 4


def article(title='MIERCOLES 04/11/26 | 08:00 a 11:00 h | CAPITAL: B Santa Teresita',
            url='/8869/MIRCOLES-041126-a-0800-a-1100-h-a-CAPITAL'):
    return '<article><h2><a href="' + url + '"><span>' + title + '</span></a></h2></article>'


class DpecCorrientesTests(unittest.TestCase):
    def test_official_dated_article_and_zone_kept_only_as_title(self):
        items, seen, links = extract_dpec_bulletins(article(), STAMP)
        self.assertEqual((seen, links, len(items)), (1, 1, 1))
        self.assertEqual(items[0]['scheduled_last_day'], '2026-11-04')
        self.assertEqual(items[0]['province'], 'Corrientes')
        self.assertIn('CAPITAL', items[0]['title'])
        self.assertNotIn('scheduled_start', items[0])
        self.assertNotIn('locality_hint', items[0])
        self.assertEqual(items[0]['status'], 'publication_only_not_current_outage')

    def test_archive_range_last_date_future(self):
        title = 'MIERCOLES 04/11/26 al VIERNES 06/11/26 | 08:00 a 16:00 h | MERCEDES'
        items, _, _ = extract_dpec_bulletins(article(title), STAMP)
        self.assertEqual(items[0]['scheduled_last_day'], '2026-11-06')

    def test_no_old_outages_even_when_archive_has_them(self):
        old = article('MARTES 03/11/26 | 08:00 a 12:00 h | CAPITAL')
        items, checked, _ = extract_dpec_bulletins(old, STAMP)
        self.assertEqual((items, checked), ([], 1))
        result = collect_dpec(STAMP, fetcher=lambda _: old)
        self.assertEqual(result['status'], 'stale')

    def test_block_unauthorized_domains_and_redirect_query(self):
        for url in ('https://evil.example/8869', 'http://www.dpec.com.ar/8869',
                    '/8869?redirect=https://evil.example', '//evil.example/8869',
                    '/comercial/cortes-programados/'):
            self.assertEqual(extract_dpec_bulletins(article(url=url), STAMP)[0], [], url)

    def test_block_cancelled_or_postponed(self):
        for prefix in ('SUSPENDIDO', 'Cancelado', 'Reprogramado', 'Postergado'):
            title = prefix + ': MIERCOLES 04/11/26 | 08:00 a 11:00 h | CAPITAL'
            self.assertEqual(extract_dpec_bulletins(article(title), STAMP)[0], [])

    def test_require_date_time_and_official_article(self):
        for title in ('Ahorro de energia 04/11/26', 'Corte previsto 04/11/26 zona norte',
                      'MIERCOLES 99/11/26 | 08:00 a 11:00 | CAPITAL'):
            self.assertEqual(extract_dpec_bulletins(article(title), STAMP)[0], [])

    def test_duplicate_links_and_multiple_schedule_segments(self):
        title = 'MIERCOLES 04/11/26 | 07:00 a 11:00 y de 14:00 a 18:00 h | BERON DE ASTRADA'
        html = article(title, '/8868') + article(title, '/8868')
        items, checked, _ = extract_dpec_bulletins(html, STAMP)
        self.assertEqual(checked, 2)
        self.assertEqual(len(items), 1)
        self.assertNotIn('scheduled_end', items[0])

    def test_source_unavailable_not_service_normal(self):
        result = collect_dpec(STAMP, fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'], 'unverified')
        self.assertIn('sin verificar', result['message'])

    def test_dynamic_empty_shell_unverified(self):
        result = collect_dpec(STAMP, fetcher=lambda _: '<h1>Cortes Programados</h1>')
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['article_links_seen'], 0)
        self.assertEqual(result['notices'], [])

    def test_offline_mode_does_not_fetch(self):
        with TemporaryDirectory() as folder:
            target = Path(folder, 'feed.json')
            with patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(target, Path(folder, 'manual.json'))
            feed = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(feed['dpec_corrientes']['status'], 'not_checked')

    def test_separate_from_live_electricity_alerts_and_notification_events(self):
        with TemporaryDirectory() as folder:
            target = Path(folder, 'feed.json')
            with patch('collector.now_utc', return_value=STAMP), \
                 patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(target, Path(folder, 'missing.json'),
                        fetch_dpec=lambda t: collect_dpec(t, fetcher=lambda _: article()))
            feed = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(feed['dpec_corrientes']['status'], 'ok')
            self.assertEqual(len(feed['dpec_corrientes']['notices']), 1)
            self.assertEqual(feed['alerts'], [])
            self.assertEqual(feed['notification_events']['events'], [])
            self.assertFalse(feed['coverage_argentina']['national_electricity_coverage'])
            source = [s for s in feed['coverage_argentina']['electricity'] if s['provider'] == 'DPEC']
            self.assertEqual(len(source), 1)
            self.assertEqual(source[0]['source_status'], 'ok')

    def test_fetcher_rejects_random_url(self):
        with self.assertRaises(ValueError):
            fetch_dpec_html('https://evil.example/')


if __name__ == '__main__':
    unittest.main()

"""Checks for official Neuquen EPEN dated bulletins (not live outages)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from epen_neuquen import collect_epen, extract_dated_bulletins
from collector import collect

STAMP = '2026-11-03T01:53:07Z'  # 2026-11-02 22:53 Argentina


def article(title='Cortes programados en sectores de Villa El Chocón el 3 al 5/11/26',
            slug='cortes-programados-en-sectores-de-villa-el-chocon-el-3-al-5-11-26',
            pub='2026/10/30', host='https://www.epen.gov.ar'):
    return f'<h2><a href="{host}/index.php/{pub}/{slug}/"><span>{title}</span></a></h2>'


class EpenNeuquenTests(unittest.TestCase):
    def test_accepts_verified_future_official_permalink(self):
        html = article()
        items, seen, future = extract_dated_bulletins(html, STAMP)
        self.assertEqual((seen, future), (1, 1))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['published_on'], '2026-10-30')
        self.assertEqual(items[0]['scheduled_last_day'], '2026-11-05')
        self.assertEqual(items[0]['province'], 'Neuquén')
        self.assertNotIn('scheduled_start', items[0])
        self.assertNotIn('locality_hint', items[0])

    def test_range_across_months(self):
        s = 'Mantenimiento programado en Aluminé y Villa Pehuenia del 27 al 30/10/26'
        items, seen, _ = extract_dated_bulletins(article(s, 'mantenimiento', '2026/10/23'), STAMP)
        self.assertEqual(items, [])
        self.assertEqual(seen, 1)

    def test_date_single_day_and_time_not_assumed(self):
        text = 'Corte Programado en zona rural de Senillosa el 03/11/2026'
        items, _, _ = extract_dated_bulletins(article(text, 'senillosa', '2026/11/01'), STAMP)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['scheduled_last_day'], '2026-11-03')
        self.assertNotIn('scheduled_end', items[0])

    def test_block_rogue_host(self):
        items, _, _ = extract_dated_bulletins(article(host='https://malicious.example'), STAMP)
        self.assertEqual(items, [])

    def test_block_future_publication(self):
        items, _, _ = extract_dated_bulletins(article(pub='2026/11/10'), STAMP)
        self.assertEqual(items, [])

    def test_block_suspended_and_canceled_titles(self):
        for marker in ('[SUSPENDIDO]', 'Cancelado', 'reprogramado'):
            html = article(marker + ' Corte Programado en sectores el 03/11/2026')
            self.assertEqual(extract_dated_bulletins(html, STAMP)[0], [])

    def test_block_old_publication_even_if_schedule_future(self):
        self.assertEqual(extract_dated_bulletins(article(pub='2026/06/01'), STAMP)[0], [])

    def test_require_explicit_valid_date_in_headline(self):
        html = article('Cortes programados en Neuquén durante la semana')
        self.assertEqual(extract_dated_bulletins(html, STAMP)[0], [])

    def test_block_bad_dates(self):
        self.assertEqual(extract_dated_bulletins(article('Corte programado el 99/11/26'), STAMP)[0], [])

    def test_dedupe_repeated_links(self):
        items, seen, _ = extract_dated_bulletins(article()+article(), STAMP)
        self.assertEqual(seen, 2)
        self.assertEqual(len(items), 1)

    def test_source_failure_not_reported_as_normal_service(self):
        result = collect_epen(STAMP, fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])

    def test_no_future_posts_is_stale_not_normal(self):
        result = collect_epen(STAMP, fetcher=lambda _: article('Corte programado el 30/10/2026'))
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['notices'], [])

    def test_no_recognized_posts_is_unverified(self):
        result = collect_epen(STAMP, fetcher=lambda _: '<p>Noticias de la empresa</p>')
        self.assertEqual(result['status'], 'unverified')

    def test_separate_from_live_alerts_and_push_events(self):
        with TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            with patch('collector.now_utc', return_value=STAMP), \
                 patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(dest, Path(folder, 'missing.json'),
                        fetch_epen=lambda t: collect_epen(t, fetcher=lambda _: article()))
            result = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(result['epen_neuquen']['status'], 'ok')
            self.assertEqual(len(result['epen_neuquen']['notices']), 1)
            self.assertEqual(result['alerts'], [])
            self.assertEqual(result['notification_events']['events'], [])
            self.assertFalse(result['coverage_argentina']['national_electricity_coverage'])

    def test_offline_direct_collect_does_not_contact_epen(self):
        with TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            with patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(dest, Path(folder, 'missing.json'))
            result = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(result['epen_neuquen']['status'], 'not_checked')


if __name__ == '__main__':
    unittest.main()

"""Offline checks for strict ENERSA bulletin monitoring and feed integration."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from collector import collect
from enersa_entre_rios import (TAG_RSS, GENERAL_RSS, collect_enersa,
                              extract_enersa_rss, fetch_enersa_rss)

STAMP = '2026-11-04T18:00:03Z'
ARTICLE = 'https://www.enersa.com.ar/enersa-informa-corte-programado-en-parana-el-miercoles/'


def rss(*entries):
    return '<rss version="2.0"><channel><title>ENERSA</title>' + ''.join(entries) + '</channel></rss>'


def item(title='ENERSA informa corte programado para el 05/11/2026',
         link=ARTICLE, published='Tue, 03 Nov 2026 15:00:00 -0300',
         description='Interrupcion programada del suministro en Parana.'):
    return ('<item><title>' + title + '</title><link>' + link + '</link>'
            '<pubDate>' + published + '</pubDate><description>' + description + '</description></item>')


class EnersaTests(unittest.TestCase):
    def test_future_dated_official_notice(self):
        notices, checked, scanned = extract_enersa_rss(rss(item()), STAMP)
        self.assertEqual((checked, scanned, len(notices)), (1, 1, 1))
        n = notices[0]
        self.assertEqual(n['scheduled_last_day'], '2026-11-05')
        self.assertEqual(n['province'], 'Entre Rios')
        self.assertEqual(n['status'], 'publication_only_not_current_outage')
        self.assertNotIn('scheduled_start', n)
        self.assertNotIn('locality_hint', n)

    def test_natural_language_date_with_year(self):
        notices, _, _ = extract_enersa_rss(rss(item(
            title='ENERSA: corte programado el 6 de noviembre de 2026')), STAMP)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['scheduled_last_day'], '2026-11-06')

    def test_month_and_year_must_be_complete(self):
        cases = [
            ('Corte programado para el 5 de noviembre', 'en la zona'),
            ('Corte programado sin fecha', 'Parana'),
            ('ENERSA realizó trabajos de poda preventiva 05/11/2026', 'En Parana'),
            ('ENERSA informa interrupcion sin anuncio programado 05/11/2026', ''),
        ]
        for title, description in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_enersa_rss(
                    rss(item(title=title, description=description)), STAMP)[0], [])

    def test_old_and_far_future_dates_rejected(self):
        for when in ('03/11/2026', '27/11/2026', '05/11/2025', '99/11/2026'):
            with self.subTest(when=when):
                self.assertEqual(extract_enersa_rss(
                    rss(item(title='ENERSA informa corte programado el '+when)), STAMP)[0], [])

    def test_cancelled_or_already_completed(self):
        for modifier in ('Suspendido:', 'Cancelado:', 'Reprogramado:', 'Finalizo:', 'Se realizo:'):
            with self.subTest(modifier=modifier):
                self.assertEqual(extract_enersa_rss(rss(item(
                    title=modifier+' ENERSA informa corte programado 05/11/2026')), STAMP)[0], [])

    def test_official_link_restrictions(self):
        invalids = [
            'https://evil.example/enersa-informa-corte-programado-2026/',
            'http://www.enersa.com.ar/enersa-informa-corte-programado-2026/',
            'https://www.enersa.com.ar/feed/',
            'https://www.enersa.com.ar/enersa-informa-corte-programado-2026/?redirect=x',
            'https://www.enersa.com.ar:444/enersa-informa-corte-programado-2026/',
            'https://www.enersa.com.ar@evil.example/enersa-informa-corte-programado-2026/',
        ]
        for link in invalids:
            with self.subTest(link=link):
                self.assertEqual(extract_enersa_rss(rss(item(link=link)), STAMP)[0], [])

    def test_reject_malformed_xml_doctype_large_or_no_timezone(self):
        for xml in ('bad', '', '<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+rss(item()),
                    rss(item()) + 'X'*710_000):
            with self.assertRaises(ValueError):
                extract_enersa_rss(xml, STAMP)
        with self.assertRaises(ValueError):
            extract_enersa_rss(rss(item()), '2026-11-04T18:00:00')

    def test_duplicate_article_links(self):
        notices, checked, scanned = extract_enersa_rss(rss(item(), item()), STAMP)
        self.assertEqual((len(notices), checked, scanned), (1, 2, 2))

    def test_fallback_to_general_rss(self):
        queried = []
        def fetch(url):
            queried.append(url)
            return rss() if url == TAG_RSS else rss(item())
        result = collect_enersa(STAMP, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['source_used'], GENERAL_RSS)
        self.assertEqual(queried, [TAG_RSS, GENERAL_RSS])
        self.assertEqual(result['source_attempts'][0]['rss_items_seen'], 0)
        self.assertEqual(len(result['notices']), 1)

    def test_stale_is_not_normal_service(self):
        result = collect_enersa(STAMP, fetcher=lambda url: rss(item(
            title='ENERSA informa corte programado 01/11/2026')))
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['notices'], [])
        self.assertIn('no confirma', result['message'])

    def test_failed_requests_never_appear_as_normal_supply(self):
        result = collect_enersa(STAMP, fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])
        self.assertEqual(len(result['source_attempts']), 2)
        self.assertEqual(result['source_attempts'][0]['error_type'], 'TimeoutError')

    def test_one_valid_feed_skips_fallback(self):
        result = collect_enersa(STAMP, fetcher=lambda u: rss(item()))
        self.assertEqual(len(result['source_attempts']), 1)
        self.assertEqual(result['source_used'], TAG_RSS)

    def test_fetcher_rejects_external_urls(self):
        with self.assertRaises(ValueError):
            fetch_enersa_rss('https://evil.example/feed/')

    def test_separate_from_live_alerts_and_phone_notifications(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp)/'feed.json'
            with patch('collector.now_utc', return_value=STAMP), \
                 patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(target, Path(tmp)/'manual.json',
                        fetch_enersa=lambda t: collect_enersa(t, fetcher=lambda u: rss(item())))
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(data['enersa_entre_rios']['status'], 'ok')
            self.assertEqual(len(data['enersa_entre_rios']['notices']), 1)
            self.assertEqual(data['alerts'], [])
            self.assertEqual(data['notification_events']['events'], [])
            x = [p for p in data['coverage_argentina']['electricity'] if p['provider']=='ENERSA']
            self.assertEqual(len(x), 1)
            self.assertEqual(x[0]['source_status'], 'ok')
            self.assertFalse(data['coverage_argentina']['national_electricity_coverage'])

    def test_default_offline_collector_does_not_call_enersa(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp)/'feed.json'
            with patch('collector.fetch_js', side_effect=TimeoutError()):
                collect(target, Path(tmp)/'manual.json')
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))[
                'enersa_entre_rios']['status'], 'not_checked')


if __name__ == '__main__':
    unittest.main()

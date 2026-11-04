"""Regression tests for EPEN's official RSS fallback; no live network required."""
import unittest
from epen_neuquen import RSS_URL, SOURCE_URL, collect_epen, extract_rss_bulletins, extract_dated_bulletins, fetch_html

STAMP = '2026-11-04T02:41:22Z'  # Nov 3, Argentina
GOOD = 'https://www.epen.gov.ar/index.php/2026/11/03/corte-programado-en-sectores-de-centenario-el-04-11-2026/'
GOOD2 = 'https://www.epen.gov.ar/index.php/2026/11/02/cortes-programados-en-senillosa-y-arroyito-del-03-al-06-11-2026/'


def feed(*items):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0"><channel><title>EPEN</title>' +
            ''.join('<item><title>%s</title><link>%s</link></item>' % (t, u) for t, u in items) +
            '</channel></rss>')


class EpenRssFallbackTests(unittest.TestCase):
    def test_official_rss_recognizes_future_dates(self):
        raw = feed(('Corte programado en sectores de Centenario el 04/11/2026', GOOD),
                   ('Cortes programados en Senillosa y Arroyito del 03 al 06/11/2026', GOOD2))
        items, eligible, future = extract_rss_bulletins(raw, STAMP)
        self.assertEqual((len(items), eligible, future), (2, 2, 2))
        self.assertEqual(items[0]['company'], 'EPEN')
        self.assertIn('publication_only_not_current_outage', str(items))

    def test_feed_fallback_after_archive_with_no_post_links(self):
        rss = feed(('Corte programado en sectores de Centenario el 04/11/2026', GOOD))
        calls = []
        def fetch(url):
            calls.append(url)
            return '<h2>Corte programado en sectores de Centenario el 04/11/2026</h2>' if url == SOURCE_URL else rss
        result = collect_epen(STAMP, fetcher=fetch)
        self.assertEqual(calls, [SOURCE_URL, RSS_URL])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['fallback_rss'], 'verified')
        self.assertEqual(result['rss_candidates'], 1)
        self.assertEqual(len(result['notices']), 1)
        self.assertNotIn('scheduled_start', result['notices'][0])

    def test_feed_not_fetched_if_archive_works(self):
        body = '<a href="%s">Corte programado en sectores de Centenario el 04/11/2026</a>' % GOOD
        calls = []
        def fetch(url):
            calls.append(url)
            return body
        result = collect_epen(STAMP, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(calls, [SOURCE_URL])
        self.assertEqual(result['fallback_rss'], 'not_needed')

    def test_only_official_links_and_fresh_publications(self):
        raw = feed(('Corte programado en sectores de Centenario el 04/11/2026', GOOD.replace('www.epen.gov.ar','example.org')),
                   ('Corte programado en sectores de Centenario el 04/11/2026', GOOD.replace('2026/11/03','2026/01/03')),
                   ('Corte programado en sectores de Centenario el 04/11/2026', GOOD))
        items, eligible, future = extract_rss_bulletins(raw, STAMP)
        self.assertEqual((len(items), eligible, future), (1, 1, 1))

    def test_cancelled_and_stale_not_accepted(self):
        raw = feed(('Cancelado: Corte programado en Centenario el 04/11/2026', GOOD),
                   ('Corte programado en Centenario el 31/10/2026', GOOD2))
        items, eligible, future = extract_rss_bulletins(raw, STAMP)
        self.assertEqual(items, [])
        self.assertEqual((eligible, future), (1, 0))

    def test_rss_unavailable_does_not_invent_clean_status(self):
        def fetch(url):
            if url == RSS_URL:
                raise TimeoutError('RSS inaccessible')
            return '<h2>sin enlaces</h2>'
        output = collect_epen(STAMP, fetcher=fetch)
        self.assertEqual(output['status'], 'unverified')
        self.assertEqual(output['fallback_rss'], 'unverified')
        self.assertEqual(output['rss_error_type'], 'TimeoutError')

    def test_invalid_xml_does_not_make_future_notices(self):
        result = collect_epen(STAMP, fetcher=lambda url: '<p>No XML</p>')
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])

    def test_archive_image_alt_or_title_attributes(self):
        for inner in ('<img alt="Corte programado en Centenario el 04/11/2026"/>', ''):
            if inner:
                html = '<a href="%s">%s</a>' % (GOOD, inner)
            else:
                html = '<a title="Corte programado en Centenario el 04/11/2026" href="%s"></a>' % GOOD
            items, eligible, future = extract_dated_bulletins(html, STAMP)
            self.assertEqual((len(items), eligible, future), (1, 1, 1))

    def test_no_unlisted_external_url_allowed(self):
        with self.assertRaises(ValueError):
            fetch_html('https://example.com/rss')


if __name__ == '__main__':
    unittest.main()

"""Offline regression tests for OSSE v5.45; run with unittest discover."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import water_notices as w

CHECKED = '2026-11-15T16:00:00Z'
SITE = 'https://www.osmgp.gov.ar/osse/'
ARTICLE = SITE + 'interrupcion-del-servicio-de-agua-en-batan/'
OLD = SITE + 'osse-amplia-la-red-de-agua-en-punta-mogotes-2/'
TITLE = 'Interrupción del servicio de agua en Batán'
IMPACT = ('OSSE informa que se registra una interrupción del servicio de agua '
          'en Batán, en el barrio Los Tilos, mientras se realizan tareas de reparación.')

def rss(items):
    return '<rss version="2.0"><channel>' + ''.join(
        '<item><title>{}</title><link>{}</link><pubDate>{}</pubDate></item>'.format(*t)
        for t in items) + '</channel></rss>'

def article_html(title=TITLE, when='Nov 15, 2026', body=IMPACT):
    return (f'<html><head><title>{title}</title></head><body>'
            f'<h1>{title}</h1><div>por prensa | {when} | Obras y servicios</div>'
            f'<p>{body}</p></body></html>')

def listing(items):
    return '<html><body><h1>Últimas Noticias</h1>' + ''.join(
        f'<h2><a href="{url}">{label}</a></h2><div>{dt} | Obras y servicios</div>'
        for url, label, dt in items) + '</body></html>'

class TestOsseV545(unittest.TestCase):
    def test_keeps_all_existing_sources_and_notifications_off(self):
        self.assertEqual(len(w.SOURCES), 12)
        self.assertIn('absa_buenos_aires', w.SOURCES)
        self.assertIn('edos_concordia', w.SOURCES)
        self.assertIn('osse_mar_del_plata', w.SOURCES)
        example = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=lambda u: rss([])
                                if u == w._OSSE_RSS else listing([]))
        self.assertFalse(example['notifications_enabled'])

    def test_rss_recognizes_old_articles_instead_of_zero_links(self):
        data = rss([('OSSE amplía la red de agua en Punta Mogotes', OLD,
                     'Tue, 20 Oct 2026 15:00:00 +0000')])
        def fetch(url):
            if url == w._OSSE_RSS:
                return data
            raise AssertionError('Old article should not be fetched')
        out = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=fetch)
        self.assertEqual(out['index_mode'], 'rss')
        self.assertEqual(out['article_links_seen'], 1)
        self.assertEqual(out['articles_skipped_old'], 1)
        self.assertEqual(out['articles_checked'], 0)
        self.assertEqual(out['status'], 'stale')
        self.assertEqual(out['notices'], [])

    def test_rss_generates_read_only_localized_bulletin(self):
        data = rss([(TITLE, ARTICLE, 'Sun, 15 Nov 2026 15:00:00 +0000')])
        def fetch(url):
            return data if url == w._OSSE_RSS else article_html()
        out = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=fetch)
        self.assertEqual(out['article_links_seen'], 1)
        self.assertEqual(out['articles_checked'], 1)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(len(out['notices']), 1)
        item = out['notices'][0]
        self.assertEqual(item['locality_hint'], 'Batán')
        self.assertFalse(item['notification_allowed'])
        self.assertEqual(item['status'], 'publication_only_not_live')
        self.assertFalse(out['notifications_enabled'])

    def test_html_fallback_recognizes_links_even_without_alarm_keywords(self):
        html = listing([('https://www.osmgp.gov.ar/osse/osse-amplia-la-red-de-agua-en-punta-mogotes-2/',
                         'OSSE amplía la red de agua en Punta Mogotes', 'Nov 2, 2026')])
        def fetch(url):
            if url == w._OSSE_RSS:
                raise OSError('RSS temporalmente inaccesible')
            if url == w.SOURCES['osse_mar_del_plata'][2]:
                return html
            raise AssertionError('Old article should not be fetched')
        out = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=fetch)
        self.assertEqual(out['index_mode'], 'html')
        self.assertEqual(out['article_links_seen'], 1)
        self.assertEqual(out['articles_skipped_old'], 1)
        self.assertEqual(out['notices'], [])

    def test_no_false_water_alert_from_generic_works(self):
        data = rss([('OSSE amplía la red de agua en Punta Mogotes', OLD,
                     'Sun, 15 Nov 2026 15:00:00 +0000')])
        body = ('OSSE Mar del Plata adjudicó una obra para ampliar la cobertura. '
                'La intervención contempla la instalación de cañerías y mejoras en la red.')
        out = w.collect_one('osse_mar_del_plata', CHECKED,
                            fetcher=lambda u: data if u == w._OSSE_RSS
                            else article_html('OSSE amplía la red de agua en Punta Mogotes', body=body))
        self.assertEqual(out['notices'], [])
        self.assertEqual(out['articles_checked'], 1)
        self.assertEqual(out['status'], 'unverified')

    def test_company_name_is_not_enough_for_geographic_precision(self):
        data = rss([('Interrupción del servicio de agua por trabajos', ARTICLE,
                     'Sun, 15 Nov 2026 15:00:00 +0000')])
        generic = ('Obras Sanitarias Mar del Plata informa a sus usuarios sobre sus servicios. '
                   'Se registra una interrupción del servicio por tareas operativas en sectores no identificados.')
        out = w.collect_one('osse_mar_del_plata', CHECKED,
                            fetcher=lambda u: data if u == w._OSSE_RSS else
                            article_html('Interrupción del servicio de agua por trabajos', body=generic))
        self.assertEqual(out['notices'], [])

    def test_negated_interruption_not_issued(self):
        data = rss([(TITLE, ARTICLE, 'Sun, 15 Nov 2026 15:00:00 +0000')])
        body = ('OSSE informa a los vecinos de Batán que no se interrumpirá el servicio '
                'de agua mientras duren las tareas de mantenimiento programado.')
        out = w.collect_one('osse_mar_del_plata', CHECKED,
                            fetcher=lambda u: data if u == w._OSSE_RSS
                            else article_html(body=body))
        self.assertFalse(out['notices'])

    def test_inaccessible_indexes_do_not_claim_normal_supply(self):
        def fail(url):
            raise OSError('offline')
        out = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=fail)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['index_mode'], 'unavailable')
        self.assertEqual(len(out['index_attempts']), 2)
        self.assertEqual(out['notices'], [])
        self.assertIn('desconocida', out['message'])

    def test_html_headings_without_links_raise_diagnostic(self):
        def fetch(url):
            if url == w._OSSE_RSS:
                raise OSError('RSS not available')
            return ('<html><body><h1>Últimas Noticias</h1>'
                    '<h2>Interrupción del servicio de agua en Batán</h2>'
                    '</body></html>')
        out = w.collect_one('osse_mar_del_plata', CHECKED, fetcher=fetch)
        self.assertEqual(out['article_links_seen'], 0)
        self.assertEqual(out['index_mode'], 'unavailable')
        self.assertGreater(out['html_news_headings_seen'], 0)
        self.assertIn('estructura HTML', out['index_warning'])
        self.assertEqual(out['status'], 'unverified')

    def test_rss_rejects_malicious_external_article_links(self):
        xml = rss([('Interrupción del servicio de agua en Batán',
                    'https://imposter.example/osse/interrupcion-del-servicio-de-agua-en-batan/',
                    'Sun, 15 Nov 2026 15:00:00 +0000')])
        self.assertEqual(w._osse_rss_index(xml), [])
        with self.assertRaises(ValueError):
            w._osse_rss_index('<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss/>')

    def test_missing_or_conflicting_publication_dates_do_not_generate_alerts(self):
        data = rss([(TITLE, ARTICLE, 'Sun, 15 Nov 2026 15:00:00 +0000')])
        out = w.collect_one('osse_mar_del_plata', CHECKED,
                            fetcher=lambda u: data if u == w._OSSE_RSS else
                            article_html(when='Nov 14, 2026'))
        self.assertFalse(out['notices'])

if __name__ == '__main__':
    unittest.main()

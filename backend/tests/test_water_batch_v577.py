"""v5.77: Normalize only legitimate first-party Cordoba article hrefs.

Real-world official press cards provide hrefs without a leading slash, even
though their index is nested under HomeSalaPrensa/. This suite does NOT infer
outages from a repair notice or dates from an URL slug.
"""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-23T21:38:24Z'
ROOT='https://www.aguascordobesas.com.ar'
PRESS_INDEX=ROOT+'/CanalSaladePrensa/HomeSalaPrensa/'
NEWS_INDEX=ROOT+'/CanalNoticias/HomeNoticias'
PRESS_REL='CanalSaladePrensa/DetalleComunicado/600/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
PRESS_URL=ROOT+'/'+PRESS_REL
NEWS_REL='CanalNoticias/DetalleNoticia/895/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
NEWS_URL=ROOT+'/'+NEWS_REL
TITLE='Trabajos de reparación en barrio Centro - 20/11/2026'


def index(*links):
    return '<html><body><h1>Sala de Prensa</h1>'+''.join(
        '<article><p>20 Noviembre 2026</p><a href="%s">%s</a></article>'%(href,label)
        for href,label in links)+'</body></html>'


def article(body,dated='20/11/2026'):
    return ('<html><body><div>'+dated+'</div><h1>'+TITLE+'</h1><p>'+body+'</p></body></html>')


class CordobaRelativeLinksV577(unittest.TestCase):
    def test_real_website_relative_press_href_is_rooted(self):
        self.assertEqual(w._cba_resolve_article_href(PRESS_REL,PRESS_INDEX),PRESS_URL)

    def test_real_website_relative_news_href_is_rooted(self):
        self.assertEqual(w._cba_resolve_article_href(NEWS_REL,NEWS_INDEX),NEWS_URL)

    def test_article_url_is_never_nested_under_index(self):
        resolved=w._cba_resolve_article_href(PRESS_REL,PRESS_INDEX)
        self.assertNotIn('/HomeSalaPrensa/CanalSaladePrensa/',resolved)
        self.assertTrue(w._cba_article_url(resolved))

    def test_root_relative_and_fully_qualified_links_still_work(self):
        for href in ('/'+PRESS_REL,PRESS_URL):
            with self.subTest(href=href):
                self.assertEqual(w._cba_resolve_article_href(href,PRESS_INDEX),PRESS_URL)

    def test_explicitly_permitted_secondary_host(self):
        aws=PRESS_URL.replace('www.aguascordobesas','www.aws.aguascordobesas')
        self.assertEqual(w._cba_resolve_article_href(aws,PRESS_INDEX),aws)

    def test_traversal_other_hosts_and_unsafe_urls_are_rejected(self):
        invalid=[
            '../'+PRESS_REL,
            './../'+PRESS_REL,
            'https://evil.example/'+PRESS_REL,
            '//evil.example/'+PRESS_REL,
            'http://www.aguascordobesas.com.ar/'+PRESS_REL,
            'javascript:alert(1)',
            PRESS_REL+'?token=x',
            PRESS_REL+'#frag',
            PRESS_REL.replace('/600/','/600/../'),
            'https://user:pass@www.aguascordobesas.com.ar/'+PRESS_REL,
            'CanalNoticias/HomeNoticias',
            '/CanalSaladePrensa/HomeSalaPrensa/Page/2',
            'https://www.aguascordobesas.com.ar/PrintContenido/c/600/something',
        ]
        for href in invalid:
            with self.subTest(href=href):
                self.assertIsNone(w._cba_resolve_article_href(href,PRESS_INDEX))

    def test_nested_official_index_deduplicates_aliases(self):
        selected,stats=w._cba_index(index((PRESS_REL,'Leer mas'),('/'+PRESS_REL,'Leer más'),
                                          (PRESS_URL,'Leer más')),PRESS_INDEX,w.checked_instant(NOW))
        self.assertEqual(selected,[PRESS_URL])
        self.assertEqual(stats['press_article_links_seen'],1)
        self.assertEqual(stats['valid_article_links_seen'],1)
        self.assertEqual(stats['relative_article_links_fixed'],1)

    def test_both_relative_routes_are_discovered(self):
        selected,stats=w._cba_index(index((PRESS_REL,'Leer mas'),(NEWS_REL,'Leer mas')),
                                    PRESS_INDEX,w.checked_instant(NOW))
        self.assertEqual(set(selected),{PRESS_URL,NEWS_URL})
        self.assertEqual(stats['press_article_links_seen'],1)
        self.assertEqual(stats['news_article_links_seen'],1)
        self.assertEqual(stats['relative_article_links_fixed'],2)

    def test_old_date_in_relative_url_is_skipped_as_candidate_only(self):
        old=PRESS_REL.replace('20-11-2026','10-10-2026')
        selected,stats=w._cba_index(index((old,'Leer más')),PRESS_INDEX,w.checked_instant(NOW))
        self.assertEqual(selected,[])
        self.assertEqual(stats['press_article_links_seen'],1)
        self.assertEqual(stats['articles_skipped_dated_slug'],1)

    def test_completed_work_title_never_selected(self):
        done=PRESS_REL.replace('trabajos-de-reparacion','finalizaron-los-trabajos-de-reparacion')
        selected,stats=w._cba_index(index((done,'Leer más')),PRESS_INDEX,w.checked_instant(NOW))
        self.assertFalse(selected)
        self.assertEqual(stats['articles_skipped_completed_title'],1)

    def test_nested_press_index_reads_article_no_fabricated_cut(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==PRESS_INDEX:return index((PRESS_REL,'Leer mas'))
            if url==PRESS_URL:return article('Trabajamos en Av. Velez Sarsfield al 100, barrio Centro. '
                   'El tanque provee autonomia y no deberian experimentar inconvenientes. '
                   'Se solicita cuidar las reservas domiciliarias.')
            raise AssertionError('unexpected fetch '+url)
        result=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(calls,[PRESS_INDEX,PRESS_URL])
        self.assertEqual(result['articles_checked'],1)
        self.assertEqual(result['source_attempts'][0]['result'],'no_explicit_water_service_interruption')
        self.assertEqual(result['relative_article_links_fixed'],1)
        self.assertEqual(result['notices'],[])
        self.assertFalse(result['notifications_enabled'])
        self.assertEqual(result['parser_revision'],'CBA-ARTICLE-HEADER-PUBLISHED-DATE-v5.78')

    def test_explicit_impact_with_verified_article_date_is_informational(self):
        def fetch(url):
            if url==PRESS_INDEX:return index((PRESS_REL,'Leer mas'))
            if url==PRESS_URL:return article('Se registra falta de agua potable en barrio Centro de la ciudad de Córdoba.')
            raise AssertionError(url)
        r=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(len(r['notices']),1)
        n=r['notices'][0]
        self.assertEqual(n['published_on'],'2026-11-20')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])

    def test_url_slug_date_does_not_replace_missing_article_date(self):
        def fetch(url):
            if url==PRESS_INDEX:return index((PRESS_REL,'Leer mas'))
            if url==PRESS_URL:return article('Se registra falta de agua potable en barrio Centro.',
                                            dated='Sin fecha visible')
            raise AssertionError(url)
        r=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')
        self.assertEqual(r['notices'],[])

    def test_no_impact_on_website_keeps_second_index_fallback(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==PRESS_INDEX:return '<html><body><h1>Prensa</h1></body></html>'
            if url==NEWS_INDEX:return index((NEWS_REL,'Leer mas'))
            if url==NEWS_URL:return article('La empresa publica consejos de uso responsable en barrio Centro.')
            raise AssertionError(url)
        r=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(calls,[PRESS_INDEX,NEWS_INDEX,NEWS_URL])
        self.assertEqual(r['relative_article_links_fixed'],1)
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(r['notices'],[])

    def test_30_sources_and_all_water_notifications_remain_off(self):
        r=w.collect_water(NOW,lambda url:'<html><body>Sin comunicados</body></html>')
        self.assertEqual(len(r['sources']),30)
        self.assertEqual(r['notices'],[])
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(all(not v['notifications_enabled'] for v in r['sources'].values()))

if __name__=='__main__':unittest.main()

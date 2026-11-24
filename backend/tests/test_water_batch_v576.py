"""v5.76: official Cordoba press detail routes + conservative fallback."""
import unittest
import sys
from pathlib import Path
from urllib.error import URLError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW = '2026-11-23T19:07:35Z'
BASE = 'https://www.aguascordobesas.com.ar'
PRESS = BASE + '/CanalSaladePrensa/DetalleComunicado/630/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
NEWS = BASE + '/CanalNoticias/DetalleNoticia/930/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
OLD = BASE + '/CanalSaladePrensa/DetalleComunicado/470/trabajos-de-reparacion-en-barrio-centro-10-10-2026'
TITLE = 'Trabajos de reparación en barrio Centro - 20/11/2026'


def index(*items):
    return '<html><body><h1>Sala de prensa</h1>' + ''.join(
        '<section><p>20 Noviembre 2026</p><a href="%s">%s</a></section>' % (link, title)
        for link, title in items) + '</body></html>'


def article(body=None, published='20/11/2026', heading=TITLE):
    if body is None:
        body='Se registra baja presión en el suministro de agua potable del barrio Centro.'
    return ('<html><body><h2>Comunicado de prensa</h2><div>'+published+'</div>'
            '<h1>'+heading+'</h1><p>'+body+'</p></body></html>')


class CordobaPressV576(unittest.TestCase):
    def test_new_press_route_accepted(self):
        self.assertTrue(w._cba_article_url(PRESS))
        self.assertTrue(w._cba_article_url(PRESS.replace('www.aguascordobesas','www.aws.aguascordobesas')))
        self.assertTrue(w._cba_article_url(NEWS))

    def test_press_external_and_other_routes_rejected(self):
        bad = [PRESS.replace('https:', 'http:'), PRESS.replace('www.aguascordobesas.com.ar','evil.test'),
               PRESS + '?foo=1',PRESS+'#anything',
               BASE + '/CanalSaladePrensa/DetalleComunicado/630',
               BASE + '/CanalSaladePrensa/HomeSalaPrensa/',
               BASE + '/CanalNoticias/NoticiasCategoria/2/servicio',
               BASE + '/CanalSaladePrensa/DetalleComunicado/630/../evil-story',
               'https://www.aguascordobesas.com.ar@evil.test/CanalSaladePrensa/DetalleComunicado/630/foofoo',
               'https://foo:bar@www.aguascordobesas.com.ar/CanalSaladePrensa/DetalleComunicado/630/foofoo']
        for u in bad:
            with self.subTest(u=u):self.assertFalse(w._cba_article_url(u))

    def test_press_index_recognizes_generic_read_more(self):
        selected, stats = w._cba_index(index((PRESS,'Leer mas')),BASE,w.checked_instant(NOW))
        self.assertEqual(selected,[PRESS])
        self.assertEqual(stats['press_article_links_seen'],1)
        self.assertEqual(stats['news_article_links_seen'],0)

    def test_both_routes_are_counted(self):
        selected, stats = w._cba_index(index((PRESS,'Leer mas'),(NEWS,'Leer mas')),BASE,w.checked_instant(NOW))
        self.assertEqual(len(selected),2)
        self.assertEqual(stats['valid_article_links_seen'],2)
        self.assertEqual(stats['press_article_links_seen'],1)
        self.assertEqual(stats['news_article_links_seen'],1)

    def test_old_press_slug_only_screened_not_fetched(self):
        selected, stats = w._cba_index(index((OLD,'Leer mas')),BASE,w.checked_instant(NOW))
        self.assertFalse(selected)
        self.assertEqual(stats['articles_skipped_dated_slug'],1)

    def test_new_press_article_accepts_verified_water_impact(self):
        notice, published, reason = w._cba_article(article(),PRESS,w.checked_instant(NOW))
        self.assertEqual(reason,'parsed')
        self.assertEqual(published.isoformat(),'2026-11-20')
        self.assertEqual(notice['locality_hint'],'Córdoba')
        self.assertEqual(notice['status'],'publication_only_not_live')
        self.assertFalse(notice['notification_allowed'])

    def test_realistic_center_article_not_inferred_as_water_cut(self):
        body=('Les informamos que estamos realizando tareas de reparación en Av. Vélez Sarsfield '
              'al 100, barrio Centro. Nuestros equipos se encuentran trabajando para resolver '
              'la situación en el menor tiempo posible. El único barrio alcanzado por los '
              'trabajos es Centro. Les pedimos que cuiden el agua de sus reservas domiciliarias. '
              'No deberían experimentar inconvenientes si realizan un uso responsable.')
        notice, _, reason = w._cba_article(article(body),PRESS,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'no_explicit_water_service_interruption')

    def test_article_date_cannot_be_inferred_from_slug(self):
        notice, _, reason = w._cba_article(article(published='Sin fecha'),PRESS,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'publication_date_not_verified')

    def test_bad_title_remains_filtered(self):
        done=PRESS.replace('trabajos-de-reparacion','finalizaron-los-trabajos-de-reparacion')
        urls, stats = w._cba_index(index((done,'Leer mas')),BASE,w.checked_instant(NOW))
        self.assertEqual(urls,[])
        self.assertEqual(stats['articles_skipped_completed_title'],1)

    def test_real_press_index_without_impact_never_publishes(self):
        visited=[]
        def fetch(url):
            visited.append(url)
            if url==w.SOURCES['aguas_cordobesas'][2]:
                return index((PRESS,'Leer mas'))
            if url==PRESS:
                return article('Estamos realizando trabajos en calle Vélez Sarsfield, barrio Centro. '
                               'El tanque brinda autonomía, no deberían experimentar inconvenientes.')
            raise AssertionError('unexpected URL '+url)
        result = w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(result['articles_checked'],1)
        self.assertEqual(result['source_attempts'][0]['result'],'no_explicit_water_service_interruption')
        self.assertEqual(result['index_attempts'][0]['result'],'official_index_read')
        self.assertEqual(result['press_article_links_seen'],1)
        self.assertEqual(result['parser_revision'],'CBA-ARTICLE-HEADER-PUBLISHED-DATE-v5.78')
        self.assertEqual(result['notices'],[])
        self.assertFalse(result['notifications_enabled'])

    def test_candidate_fallback_if_first_index_has_only_archive(self):
        visited=[]
        def fetch(url):
            visited.append(url)
            if url==w.SOURCES['aguas_cordobesas'][2]:return index((OLD,'Leer mas'))
            if url==w._CBA_INDEX_FALLBACK:return index((NEWS,'Leer mas'))
            if url==NEWS:return article()
            raise AssertionError('unexpected URL '+url)
        result=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(len(result['index_attempts']),2)
        self.assertEqual(result['article_links_seen'],2)
        self.assertEqual(result['press_article_links_seen'],1)
        self.assertEqual(result['news_article_links_seen'],1)
        self.assertEqual(result['articles_checked'],1)
        self.assertEqual(len(result['notices']),1)
        self.assertFalse(result['notices'][0]['notification_allowed'])
        self.assertIn(w._CBA_INDEX_FALLBACK,visited)

    def test_portal_fetch_failure_never_causes_notice(self):
        result=w.collect_one('aguas_cordobesas',NOW,lambda u: (_ for _ in ()).throw(URLError('no connection')))
        self.assertEqual(len(result['index_attempts']),2)
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['status'],'unverified')

    def test_global_30_water_sources_remain_off(self):
        result=w.collect_water(NOW,lambda u:'<html><body>Sin avisos</body></html>')
        self.assertEqual(len(result['sources']),30)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(not x['notifications_enabled'] for x in result['sources'].values()))

if __name__=='__main__':unittest.main()

"""v5.75 Córdoba first-party public news fallback; never infer live cuts."""
import unittest
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
NOW='2026-11-23T16:24:47Z'
BASE='https://www.aguascordobesas.com.ar'
URL=BASE+'/CanalNoticias/DetalleNoticia/930/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
OLD=BASE+'/CanalNoticias/DetalleNoticia/900/trabajos-de-reparacion-en-barrio-centro-10-10-2026'
TITLE='Trabajos de reparación en barrio Centro - 20/11/2026'


def index(url=URL,title=TITLE):
    return ('<html><h1>Comunicados de Prensa</h1><div><span>20 Noviembre 2026</span>'
            '<a href="'+url+'">'+title+'</a></div></html>')


def article(title=TITLE,date='20/11/2026',body=None,meta=''):
    if body is None:
        body=('Desde Aguas Cordobesas informamos que el suministro de agua potable '
              'se encuentra afectado con baja presión por reparación en barrio Centro.')
    return ('<html><head>'+meta+'</head><body><div>Servicio '+date+'</div>'
            '<h1>'+title+'</h1><p>'+body+'</p></body></html>')


class CordobaCanonicalNews(unittest.TestCase):
    def test_source_kept_and_canonical_hostname(self):
        self.assertEqual(len(w.SOURCES),30)
        self.assertEqual(w.SOURCES['aguas_cordobesas'][2],BASE+'/CanalSaladePrensa/HomeSalaPrensa/')

    def test_index_allows_only_first_party_articles(self):
        self.assertTrue(w._cba_article_url(URL))
        self.assertTrue(w._cba_article_url(URL.replace('www.aguascordobesas','www.aws.aguascordobesas')))
        for value in ('http://www.aguascordobesas.com.ar/CanalNoticias/DetalleNoticia/1/foofoo',
                      'https://evil.example/CanalNoticias/DetalleNoticia/930/evil-story',
                      'https://www.aguascordobesas.com.ar.evil.example/CanalNoticias/DetalleNoticia/930/foofoo',
                      'https://u:p@www.aguascordobesas.com.ar/CanalNoticias/DetalleNoticia/930/foofoo',
                      URL+'?next=https://evil.example',URL+'#frag',
                      BASE+'/CanalNoticias/DetalleNoticia/930/../../bad',
                      BASE+'/CanalNoticias/NoticiasCategoria/2/servicio'):
            self.assertFalse(w._cba_article_url(value),value)

    def test_index_tracks_old_slug_but_never_claims_notice(self):
        urls,stats=w._cba_index(index(url=OLD),BASE,w.checked_instant(NOW))
        self.assertEqual(urls,[])
        self.assertEqual(stats['articles_skipped_dated_slug'],1)
        self.assertEqual(stats['valid_article_links_seen'],1)

    def test_generic_read_more_uses_first_party_slug_as_candidate_not_date(self):
        urls,stats=w._cba_index(index(title='Leer más'),BASE,w.checked_instant(NOW))
        self.assertEqual(urls,[URL])
        self.assertEqual(stats['valid_article_links_seen'],1)

    def test_valid_explicit_impact_published_article_only(self):
        notice,pub,reason=w._cba_article(article(),URL,w.checked_instant(NOW))
        self.assertEqual(reason,'parsed')
        self.assertEqual(pub.isoformat(),'2026-11-20')
        self.assertEqual(notice['locality_hint'],'Córdoba')
        self.assertEqual(notice['published_on'],'2026-11-20')
        self.assertEqual(notice['status'],'publication_only_not_live')
        self.assertFalse(notice['notification_allowed'])
        self.assertIsNone(notice['scheduled_end'])

    def test_work_news_without_affectation_is_not_water_cut(self):
        body=('Les informamos que estamos realizando tareas de reparación en Av. Vélez Sarsfield '
              'al 100, barrio Centro. Nuestros equipos se encuentran trabajando para resolver '
              'la situación en el menor tiempo posible. Les pedimos cuidar el agua de las '
              'reservas domiciliarias. El tanque brinda 24 horas de autonomía, por lo cual '
              'no deberían experimentar inconvenientes si realizan un uso responsable.')
        notice,_,reason=w._cba_article(article(body=body),URL,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'no_explicit_water_service_interruption')

    def test_negated_explicit_impact_excluded(self):
        notice,_,reason=w._cba_article(article(body='No se verá afectado el suministro de agua potable del barrio Centro.'),URL,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'no_explicit_water_service_interruption')

    def test_completed_article_excluded(self):
        title='Finalizaron los trabajos de reparación en barrio Centro - 20/11/2026'
        html=article(title=title,body='Se interrumpió el suministro de agua potable por la reparación.')
        n,_,reason=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'completed_or_institutional_title')

    def test_article_missing_date_is_not_assumed_from_slug(self):
        n,_,reason=w._cba_article(article(date='sin fecha'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'publication_date_not_verified')

    def test_publication_date_not_mined_from_article_body(self):
        html=article(date='sin fecha',body='El 20/11/2026 se registró una interrupción del suministro de agua en barrio Centro.')
        n,_,reason=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'publication_date_not_verified')

    def test_published_date_from_first_party_meta(self):
        html=article(date='sin fecha',meta='<meta property="article:published_time" content="2026-11-20T10:00:00-03:00">')
        n,_,reason=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertEqual(reason,'parsed')
        self.assertEqual(n['published_on'],'2026-11-20')

    def test_outside_window(self):
        n,p,reason=w._cba_article(article(date='10/11/2026'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'outside_publication_window')

    def test_future_date(self):
        n,p,reason=w._cba_article(article(date='25/11/2026'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'outside_publication_window')

    def test_article_must_confirm_title(self):
        n,p,reason=w._cba_article(article(title='Comunicado de otra empresa por un anuncio general'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(reason,'article_heading_not_confirmed')

    def test_needs_specific_service_area(self):
        n,p,reason=w._cba_article(article(title='Trabajos de reparación de conducto de agua - 20/11/2026',
             body='Se registró baja presión del agua en sectores no identificados de Córdoba.'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertIn(reason,('service_area_not_precise','article_heading_not_confirmed'))

    def test_fallback_on_url_error(self):
        called=[]
        def fetch(u):
            called.append(u)
            if u==w.SOURCES['aguas_cordobesas'][2]:raise URLError('offline')
            if u==w._CBA_INDEX_FALLBACK:return index()
            return article()
        r=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['articles_checked'],1)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_denied_server_not_bypassed(self):
        urls=[]
        def fetch(u):
            urls.append(u)
            raise HTTPError(u,403,'denied',{},None)
        r=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(len(urls),1)
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])
        self.assertEqual(r['index_attempts'][0]['http_status'],403)

    def test_other_errors_unverified(self):
        r=w.collect_one('aguas_cordobesas',NOW,lambda _: (_ for _ in ()).throw(URLError('not available')))
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])
        self.assertIn('desconocido',r['message'])

    def test_no_index_articles_does_not_claim_service_normal(self):
        r=w.collect_one('aguas_cordobesas',NOW,lambda _: '<html><body>Acceso solo por cuenta</body></html>')
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])

    def test_global_water_off_and_30_sources(self):
        r=w.collect_water(NOW,lambda _: '<html><body>Sin noticias</body></html>')
        self.assertEqual(len(r['sources']),30)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(all(not s['notifications_enabled'] for s in r['sources'].values()))


class AdditionalConservativeCases(unittest.TestCase):
    def test_no_hay_interrupcion_is_not_outage(self):
        notice,day,reason=w._cba_article(article(body='No hay interrupción del suministro de agua potable en barrio Centro.'),URL,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'no_explicit_water_service_interruption')

    def test_no_se_interrumpira_is_not_outage(self):
        notice,day,reason=w._cba_article(article(body='No se interrumpirá el suministro de agua potable en barrio Centro.'),URL,w.checked_instant(NOW))
        self.assertIsNone(notice)
        self.assertEqual(reason,'no_explicit_water_service_interruption')

if __name__=='__main__':unittest.main()

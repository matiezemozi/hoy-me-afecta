"""v5.71: official La Rioja water-ministry public news, strict, read-only."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='la_rioja_ministerio_agua'
BASE='https://aguayenergia.larioja.gob.ar/'
URL=BASE+'noticia/corte-programado-de-agua-en-chilecito-por-una-reparacion/'
TITLE='Chilecito: corte programado de agua por una reparación'
NOW='2026-11-22T21:34:22Z'
BODY='Debido a una reparación de la red de agua potable en Chilecito, se registrará un corte de agua en el barrio centro.'

def idx(heading=TITLE,url=URL):
    return '<html><nav><a href="/contacto/">Contacto</a></nav><main><article><h3><a href="%s">%s</a></h3></article></main></html>'%(url,heading)

def art(heading=TITLE,date='22/11/2026',body=BODY,tag=True):
    header=('Fecha de Publicación '+date) if tag else date
    return '<html><h1>%s</h1><div>%s</div><p>%s</p></html>'%(heading,header,body)

def run(idx_html=None,art_html=None):
    pages={BASE:idx() if idx_html is None else idx_html,URL:art() if art_html is None else art_html}
    return w.collect_one(KEY,NOW,lambda url:pages[url])

class V571Rioja(unittest.TestCase):
    def test_province_configured(self):
        self.assertEqual(w.SOURCES[KEY][2],BASE)
        self.assertGreaterEqual(len(w.SOURCES),27)
    def test_index_correct_public_story(self):
        selected,diag=w._rioja_index(idx(),BASE)
        self.assertEqual(selected,[(URL,TITLE)])
        self.assertEqual(diag['valid_article_links_seen'],1)
    def test_positive_notice_read_only(self):
        r=run();self.assertEqual(r['status'],'ok')
        self.assertEqual(r['parser_revision'],'LA-RIOJA-OFFICIAL-PUBLIC-NEWS-v5.71')
        n=r['notices'][0]
        self.assertEqual(n['locality_hint'],'Chilecito')
        self.assertEqual(n['published_on'],'2026-11-22')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_start'])
    def test_expansion_without_service_impact_rejected(self):
        title='Chilecito: se amplía la red de agua potable en barrio nuevo'
        r=run(idx(title),art(title,body='La nueva red de agua potable permitirá realizar conexiones para más vecinos en Chilecito.'))
        self.assertEqual(r['notices'],[])
    def test_denied_impact_is_not_notice(self):
        for text in ('La obra de la red de agua potable se realiza sin afectar el servicio en Chilecito.',
                     'No habrá cortes de agua por las reparaciones de la red de agua potable en Chilecito.',
                     'Se trabaja en la red de agua potable de Chilecito para prevenir cortes del servicio.'):
            self.assertFalse(run(art_html=art(body=text))['notices'],text)
    def test_concluded_impact_is_not_current_notice(self):
        title='Chilecito: finalizaron los trabajos y se normalizó el servicio de agua'
        self.assertEqual(run(idx(title),art(heading=title))['notices'],[])
    def test_no_publication_label_rejected(self):
        r=run(art_html=art(tag=False))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')
    def test_work_date_is_not_publication(self):
        page='<h1>%s</h1><p>Los trabajos se realizarán el 22/11/2026.</p><p>%s</p>'%(TITLE,BODY)
        self.assertEqual(run(art_html=page)['notices'],[])
    def test_outdated_article_rejected(self):
        r=run(art_html=art(date='18/11/2026'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'stale')
    def test_future_date_rejected(self):
        self.assertFalse(run(art_html=art(date='23/11/2026'))['notices'])
    def test_invalid_calendar_date_rejected(self):
        self.assertFalse(run(art_html=art(date='31/11/2026'))['notices'])
    def test_ambiguous_province_vs_capital(self):
        title='Gobierno de La Rioja anuncia cortes de agua potable'
        body='El gobierno provincial comunica un corte de agua potable en el territorio, sin individualizar localidad.'
        r=run(idx(title),art(title,body=body))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'locality_not_explicit_or_ambiguous')
    def test_multiple_cities_rejected(self):
        title='Chilecito y Chepes: trabajos sobre la red de agua potable'
        self.assertFalse(run(idx(title),art(title))['notices'])
    def test_broken_homepage_reports_unverified(self):
        r=w.collect_one(KEY,NOW,lambda _:(_ for _ in ()).throw(HTTPError(BASE,403,'Forbidden',{},None)))
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['notices'],[])
    def test_no_links_does_not_mean_service_normal(self):
        r=run(idx_html='<html><body><div id="root"></div></body></html>')
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'unverified')
    def test_story_url_reject_untrusted_host_query_or_protocol(self):
        self.assertTrue(w._rioja_story_url(URL))
        for candidate in (URL+'?q=account',URL+'#fragment',URL.replace('https','http'),
                          URL.replace('aguayenergia.larioja.gob.ar','thirdparty.example'),
                          URL.replace('https://','https://user:pass@'),
                          BASE+'noticia/../../../secret',BASE+'contacto/'):
            self.assertFalse(w._rioja_story_url(candidate),candidate)
    def test_limit_articles(self):
        html=''.join(idx(heading='Corte de agua en Chilecito por reparación número '+str(i),
                             url=BASE+'noticia/corte-de-agua-en-chilecito-reparacion-'+str(i)+'/') for i in range(8))
        selected,stats=w._rioja_index(html,BASE)
        self.assertEqual(len(selected),3)
        self.assertEqual(stats['articles_deferred_by_budget'],5)
    def test_water_not_electricity(self):
        title='Chilecito: corte programado de electricidad'
        self.assertFalse(run(idx(title),art(title,body='Se interrumpirá el servicio eléctrico en Chilecito por obras.'))['notices'])
    def test_full_feed_safety_flags(self):
        d=w.collect_water(NOW,lambda _:'<html></html>')
        self.assertGreaterEqual(len(d['sources']),27)
        self.assertEqual(d['status'],'pilot_read_only_in_android')
        self.assertFalse(d['notifications_enabled'])
        self.assertFalse(d['android_display_enabled'])
        self.assertTrue(all(n['notification_allowed'] is False for n in d['notices']))
        self.assertTrue(all(src['notifications_enabled'] is False for src in d['sources'].values()))

if __name__=='__main__':unittest.main()

"""v5.69: pilot Santa Cruz SPSE official government press; honest San Juan diagnostic."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='spse_santa_cruz_prensa'
INDEX='https://noticias.santacruz.gob.ar/organismos/entes-publicos/servicios-publicos'
LINK=INDEX+'/corte-programado-de-agua-en-caleta-olivia'
TITLE='Caleta Olivia: corte programado de agua por reparacion'
NOW='2026-11-22T14:56:11Z'
IMPACT='Se registrara un corte del servicio de agua potable en Caleta Olivia debido a una reparacion de la red de distribucion.'

def index(title=TITLE,pub='22 Noviembre 2026',url=LINK):
    return '<html><main><a href="%s"><span>SERVICIOS BASICOS</span> | %s %s</a></main></html>'%(url,pub,title)

def article(title=TITLE,pub='22 Noviembre 2026',body=IMPACT):
    return '<html><h1>%s</h1><p>Servicio tecnico del distrito informa trabajos programados.</p><p>%s</p><p>%s</p></html>'%(title,pub,body)

def collect(idx=None,art=None):
    pages={INDEX:index() if idx is None else idx,LINK:article() if art is None else art}
    return w.collect_one(KEY,NOW,lambda u:pages[u])

class TestWaterV569(unittest.TestCase):
    def test_configured_26_safe_sources(self):
        self.assertEqual(w.SOURCES[KEY][2],INDEX)
        self.assertEqual(len(w.SOURCES),26)
        self.assertNotIn('api',INDEX)
    def test_index_story_dates_and_titles(self):
        got,diag=w._spse_index(index(),INDEX,w.checked_instant(NOW))
        self.assertEqual(got,[(LINK,TITLE,w.date(2026,11,22))])
        self.assertEqual(diag['valid_article_links_seen'],1)
        self.assertEqual(diag['dated_headlines_seen'],1)
    def test_realistic_nested_index_markup(self):
        html='<a href="%s"><span>Servicios públicos</span><small>22 Noviembre 2026</small><strong>%s</strong></a>'%(LINK,TITLE)
        chosen,_=w._spse_index(html,INDEX,w.checked_instant(NOW))
        self.assertEqual(len(chosen),1)
    def test_publication_only_not_live(self):
        r=collect()
        self.assertEqual(r['parser_revision'],'SPSE-PROVINCIAL-PRESS-v5.69')
        self.assertEqual(r['status'],'ok')
        n=r['notices'][0]
        self.assertEqual(n['locality_hint'],'Caleta Olivia')
        self.assertEqual(n['published_on'],'2026-11-22')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])
        self.assertFalse(n['notification_allowed'])
    def test_no_negative_current_status(self):
        r=collect(art=article(body='Se realizan trabajos preventivos sin afectar el servicio de agua potable. No habra cortes.'))
        self.assertEqual(r['notices'],[])
    def test_completed_title_rejected(self):
        t='Caleta Olivia: finalizo corte del servicio de agua potable'
        got,_=w._spse_index(index(title=t),INDEX,w.checked_instant(NOW))
        self.assertEqual(got,[])
    def test_outdated_index_rejected(self):
        r=collect(idx=index(pub='11 Noviembre 2026'))
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['headlines_skipped_outside_window'],1)
    def test_future_publication_rejected(self):
        r=collect(idx=index(pub='23 Noviembre 2026'))
        self.assertFalse(r['notices'])
    def test_undated_index_rejected(self):
        r=collect(idx=index(pub=''))
        self.assertFalse(r['notices'])
        self.assertEqual(r['articles_checked'],0)
    def test_article_date_mismatch_rejected(self):
        r=collect(art=article(pub='21 Noviembre 2026'))
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'article_publication_date_not_confirmed')
    def test_not_event_date_instead_of_publication(self):
        art='<h1>%s</h1><p>El trabajo sera el 22 Noviembre 2026.</p><p>%s</p>'%(TITLE,IMPACT)
        r=collect(art=art)
        self.assertFalse(r['notices'])
    def test_no_area_explicit_rejected(self):
        t='Corte programado de agua por reparacion de la red'
        r=collect(idx=index(title=t),art=article(title=t,body='Se preve un corte del servicio de agua potable por reparacion de cañeria.'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'locality_not_explicit_or_ambiguous')
    def test_nonwater_power_outage_rejected(self):
        t='Caleta Olivia: corte programado de energia electrica por mantenimiento'
        r=collect(idx=index(title=t),art=article(title=t,body='Se registrara un corte del servicio electrico en Caleta Olivia por trabajos de mantenimiento.'))
        self.assertEqual(r['notices'],[])
    def test_water_infrastructure_expansion_not_outage(self):
        t='SPSE amplía la red de agua potable en Pico Truncado'
        r=collect(idx=index(title=t),art=article(title=t,body='Se inaugura una red de agua potable nueva en Pico Truncado.'))
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['notices'],[])
    def test_safe_url_no_credentials_third_parties_or_queries(self):
        self.assertTrue(w._spse_story_url(LINK))
        for u in (LINK+'?service_account=123',LINK+'#x',LINK.replace('noticias.santacruz.gob.ar','thirdparty.example'),
                  LINK.replace('https:','http:'),INDEX+'/../../../admin',INDEX+'/contacto'):
            self.assertFalse(w._spse_story_url(u),u)
    def test_limit_articles_and_no_mass_fetch(self):
        html=''.join(index(title='Caleta Olivia: corte del servicio de agua '+str(i),url=LINK+'-'+str(i)) for i in range(9))
        selected,diag=w._spse_index(html,INDEX,w.checked_instant(NOW))
        self.assertEqual(len(selected),3)
        self.assertEqual(diag['articles_deferred_by_budget'],6)
    def test_broken_index_reports_unknown_not_clean(self):
        def fetch(_):raise HTTPError(INDEX,403,'denied',{},None)
        r=w.collect_one(KEY,NOW,fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['notices'],[])
    def test_san_juan_zero_links_clearly_diagnosed(self):
        r=w.collect_one('osse_san_juan_prensa',NOW,lambda _:'<html><head><script src="/main.js"></script></head><body><div id="root"></div></body></html>')
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['index_mode'],'client_rendered_shell_suspected')
        self.assertEqual(r['html_anchors_seen'],0)
        self.assertEqual(r['notices'],[])
    def test_read_only_safety_with_new_source(self):
        r=w.collect_water(NOW,lambda _:'<html></html>')
        self.assertEqual(len(r['sources']),26)
        self.assertEqual(r['status'],'pilot_read_only_in_android')
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(r['android_read_only_pilot_available'])
        self.assertTrue(all(n['notification_allowed'] is False for n in r['notices']))

if __name__=='__main__':unittest.main()

"""v5.68: OSSE San Juan public news pilot, read-only, no invented alerts."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='osse_san_juan_prensa'
INDEX='https://www.ossesanjuan.com.ar/'
LINK='https://www.ossesanjuan.com.ar/noticias/corte-programado-rawson'
TITLE='Rawson: corte programado de agua potable por reparación'
WHEN='2026-11-21T23:10:59Z'
POS='Se registrara baja presion en el servicio de agua potable en Rawson, por reparaciones sobre la red.'

def index(title=TITLE,href='/noticias/corte-programado-rawson'):
    return f'<html><h2>{title}</h2><a href="{href}">Ver más</a></html>'

def article(title=TITLE,body=POS,meta='<meta property="article:published_time" content="2026-11-21T12:00:00-03:00">'):
    return f'<html>{meta}<h1>{title}</h1><p>{body}</p></html>'

def collect(idx=None,body=None):
    pages={INDEX:index() if idx is None else idx,LINK:article() if body is None else body}
    return w.collect_one(KEY,WHEN,lambda u:pages[u])

class TestWaterV568(unittest.TestCase):
    def test_configured_official_source(self):
        self.assertEqual(w.SOURCES[KEY][2],INDEX)
        self.assertGreaterEqual(len(w.SOURCES),25)

    def test_carousel_ver_mas_takes_nearby_h2(self):
        got,stats=w._osse_sj_index(index(),INDEX)
        self.assertEqual(got,[(LINK,TITLE)])
        self.assertEqual(stats['valid_article_links_seen'],1)

    def test_official_article_parsed_as_publication_only(self):
        r=collect()
        self.assertEqual(r['parser_revision'],'OSSE-SANJUAN-PUBLIC-NEWS-v5.68')
        self.assertEqual(r['status'],'ok')
        n=r['notices'][0]
        self.assertEqual((n['locality_hint'],n['published_on']),('Rawson','2026-11-21'))
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])
        self.assertFalse(n['notification_allowed'])

    def test_without_date_no_notice(self):
        r=collect(body=article(meta=''))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_explicit_numeric_heading_date_is_allowed(self):
        r=collect(body=article(meta='').replace('</h1>','</h1><p>Publicado el 21/11/2026</p>'))
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-21')

    def test_unlabelled_event_date_is_not_published_day(self):
        r=collect(body=article(meta='').replace('</h1>','</h1><p>Trabajos el 21/11/2026</p>'))
        self.assertEqual(r['notices'],[])

    def test_future_publication_is_rejected(self):
        r=collect(body=article(meta='<meta property="article:published_time" content="2026-11-23">'))
        self.assertEqual(r['notices'],[])

    def test_old_publication_is_rejected(self):
        r=collect(body=article(meta='<meta property="article:published_time" content="2026-11-01">'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'outside_publication_window')

    def test_no_locality_not_inferred_from_province(self):
        t='San Juan: corte programado de agua potable por reparación'
        r=collect(idx=index(title=t),body=article(title=t))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'locality_not_explicit_in_title')

    def test_no_positive_effect_in_body(self):
        r=collect(body=article(body='Se realizan mejoras sobre una red de agua potable sin afectar el servicio de agua potable.'))
        self.assertEqual(r['notices'],[])

    def test_water_use_restrictions_are_not_cut(self):
        titles='Obras Sanitarias mantiene horario restringido para usar agua potable'
        r=collect(idx=index(title=titles))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['articles_checked'],0)

    def test_finished_title_does_not_make_active_notice(self):
        t='Rawson: finalizó corte de agua por reparación'
        r=collect(idx=index(title=t),body=article(title=t))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'completed_or_restored_title')

    def test_safe_url_validation_and_legacy_official_article_path(self):
        ok='https://www.ossesanjuan.com.ar/v4/prensa/noticia?noticia=TkRkaVpXTTFNR1F0WVRRd01TMHhNV1Zs'
        self.assertTrue(w._osse_sj_news_url(ok))
        for url in ['https://evil.example/noticias/corte-programado-rawson',
                    'https://www.ossesanjuan.com.ar/noticias/usuario',
                    'https://www.ossesanjuan.com.ar/noticias/corte-programado-rawson?token=x',
                    'https://www.ossesanjuan.com.ar/v4/prensa/noticia?cuenta=1234567890',
                    'http://www.ossesanjuan.com.ar/noticias/corte-programado-rawson']:
            self.assertFalse(w._osse_sj_news_url(url),url)

    def test_unknown_official_routes_are_diagnostic_only(self):
        r=collect(idx=index(href='/v5/comunicado-nuevo'))
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])

    def test_access_denial_not_reported_as_no_outage(self):
        def fetch(u):raise HTTPError(u,403,'denied',{},None)
        r=w.collect_one(KEY,WHEN,fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertFalse(r['notices'])

    def test_all_safety_switches_stay_off(self):
        r=w.collect_water(WHEN,lambda _: '<html></html>')
        self.assertGreaterEqual(len(r['sources']),25)
        self.assertEqual(r['status'],'pilot_read_only_in_android')
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(r['android_read_only_pilot_available'])
        self.assertTrue(all(not n['notification_allowed'] for n in r['notices']))

if __name__=='__main__':unittest.main()

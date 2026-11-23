"""v5.73: verify canonical Chaco index and bounded official fallback."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='sameep_chaco_prensa_gobierno'
MAIN='https://chaco.gob.ar/'
FALLBACK='https://www.chaco.gob.ar/'
NOW='2026-11-23T00:14:01Z'
TITLE='SAMEEP informa corte de agua potable en Fontana'
STORY='https://chaco.gob.ar/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-11-30'
BODY='En Fontana se registra una baja presion del servicio de agua potable por reparacion de una caneria.'

def idx(url=STORY,title=TITLE):
    return '<html><a href="%s">%s</a></html>'%(url,title)
def article(title=TITLE,body=BODY,day='22/11/2026'):
    return '<html><div>%s</div><h1>%s</h1><p>%s</p></html>'%(day,title,body)

def run(fetch):
    return w.collect_one(KEY,NOW,fetch)

class V573(unittest.TestCase):
    def test_canonical_source_is_official_home(self):
        self.assertEqual(w.SOURCES[KEY][2],MAIN)
        self.assertEqual(len(w.SOURCES),30)

    def test_canonical_index_with_valid_notice(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return {MAIN:idx(),STORY:article()}[url]
        r=run(fetch)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['notices'][0]['locality_hint'],'Fontana')
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-22')
        self.assertEqual(calls,[MAIN,STORY])

    def test_fallback_when_canonical_unreachable(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==MAIN:raise URLError('unavailable')
            return {FALLBACK:idx(),STORY:article()}[url]
        r=run(fetch)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(calls,[MAIN,FALLBACK,STORY])
        self.assertEqual(r['index_attempts'][0]['error_type'],'URLError')
        self.assertEqual(r['index_attempts'][1]['result'],'official_index_read')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_fallback_after_empty_canonical_html(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return {MAIN:'<html><body>Sin enlaces</body></html>',FALLBACK:idx(),STORY:article()}[url]
        r=run(fetch)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(calls,[MAIN,FALLBACK,STORY])

    def test_no_fallback_if_valid_official_links_but_no_water_impact(self):
        other='https://chaco.gob.ar/noticia-presentan-nuevas-obras-de-viviendas-2026-11-22-10-00'
        calls=[]
        def fetch(url):
            calls.append(url)
            return idx(other,'El gobierno presenta avances de viviendas')
        r=run(fetch)
        self.assertFalse(r['notices'])
        self.assertEqual(calls,[MAIN])
        self.assertEqual(r['index_attempts'][0]['valid_article_links_seen'],1)

    def test_both_hosts_fail_without_claim_of_normal_service(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            raise URLError('host temporarily unavailable')
        r=run(fetch)
        self.assertEqual(calls,[MAIN,FALLBACK])
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])
        self.assertIn('desconocido',r['message'])

    def test_http403_diagnosed_and_fallback_attempted(self):
        def fetch(url):
            if url==MAIN:raise HTTPError(url,403,'Forbidden',None,None)
            return {FALLBACK:idx(),STORY:article()}[url]
        r=run(fetch)
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['status'],'ok')

    def test_no_undated_publication(self):
        r=run(lambda u:{MAIN:idx(),STORY:'<html><h1>%s</h1><p>%s</p></html>'%(TITLE,BODY)}[u])
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_reject_older_publication_with_new_looking_title(self):
        r=run(lambda u:{MAIN:idx(),STORY:article(day='11/11/2026')}[u])
        self.assertFalse(r['notices'])

    def test_reject_incidental_electric_outage(self):
        title='SAMEEP informa corte electrico por mantenimiento en Fontana'
        r=run(lambda u:{MAIN:idx(STORY,title),STORY:article(title=title,body='En Fontana no se interrumpira el servicio de agua potable.')}[u])
        self.assertFalse(r['notices'])
        self.assertEqual(r['articles_checked'],0)

    def test_reject_explicit_no_service_impact(self):
        title='SAMEEP informa reparacion de red de agua potable en Fontana'
        r=run(lambda u:{MAIN:idx(STORY,title),STORY:article(title=title,body='En Fontana se realizan reparaciones de red de agua potable sin afectar el servicio.')}[u])
        self.assertFalse(r['notices'])

    def test_reject_missing_locality(self):
        title='SAMEEP informa corte de agua potable en varias localidades'
        r=run(lambda u:{MAIN:idx(STORY,title),STORY:article(title=title,body='La red de agua potable registra baja presion en algunas zonas.')}[u])
        self.assertFalse(r['notices'])

    def test_reject_date_mismatch_url_vs_article(self):
        r=run(lambda u:{MAIN:idx(),STORY:article(day='21/11/2026')}[u])
        self.assertFalse(r['notices'])

    def test_dont_follow_untrusted_domains(self):
        for bad in ('https://chaco.gob.ar.evil.net/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-11-30',
                    'https://chaco.gob.ar/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-11-30?cuenta=100',
                    'http://chaco.gob.ar/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-11-30'):
            self.assertFalse(w._water3_story_url(KEY,bad))

    def test_bounded_article_requests(self):
        entries=''.join(idx('https://chaco.gob.ar/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-%02d-30'%i,TITLE) for i in range(10))
        urls=[]
        def fetch(u):
            urls.append(u)
            if u==MAIN:return entries
            return article()
        r=run(fetch)
        self.assertLessEqual(r['articles_checked'],3)
        self.assertEqual(r['articles_deferred_by_budget'],7)
        self.assertEqual(len(urls),4)

    def test_feed_safety_invariants(self):
        report=w.collect_water(NOW,lambda _: '<html></html>')
        self.assertEqual(len(report['sources']),30)
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertTrue(all(not v['notifications_enabled'] for v in report['sources'].values()))
        self.assertTrue(all(not n['notification_allowed'] for n in report['notices']))

if __name__=='__main__':unittest.main()

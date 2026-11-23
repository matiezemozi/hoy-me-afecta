"""v5.72: three official pilot sources; known names and dates, false-positive guards."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-23T00:14:01Z' # Argentina still 22 Nov 2026
C='sameep_chaco_prensa_gobierno'
G='gualeguaychu_obras_sanitarias'
P='corpico_general_pico_agua'
UC='https://www.chaco.gob.ar/noticia-sameep-informa-corte-de-agua-potable-en-fontana-2026-11-22-11-30'
UG='https://gualeguaychu.gov.ar/redaccion/obras-sanitarias-informa-un-corte-de-agua-potable-en-la-ciudad'
UP='https://www.corpico.com.ar/novedades/1997/'
TC='SAMEEP INFORMA CORTE DE AGUA POTABLE EN FONTANA'
TG='Obras Sanitarias informa corte de agua potable en Gualeguaychú'
TP='CORPICO INFORMA CORTE DE AGUA POTABLE EN GENERAL PICO'
PC='En Fontana se registra una baja presión del servicio de agua potable durante una reparación de cañería.'
PG='En Gualeguaychú se registra un corte del suministro de agua potable por trabajos sobre la cañería.'
PP='En General Pico se registra un corte del servicio de agua potable en la zona de barrio Rucci.'

def index(url,title):
    return '<html><a href="%s">%s</a></html>' % (url,title)

def article(title,body,pub='22/11/2026'):
    return '<html><h1>%s</h1><div>%s</div><p>%s</p></html>' % (title,pub,body)

def run(key, url, title, body, pub='22/11/2026', indexed=None, published=None):
    src=w.SOURCES[key][2]
    return w.collect_one(key,NOW,lambda u:{src:index(url,title) if indexed is None else indexed,
                                             url:article(title,body,pub) if published is None else published}[u])

class V572(unittest.TestCase):
    def test_source_names_and_30_configured(self):
        self.assertEqual(len(w.SOURCES),30)
        self.assertIn('chaco.gob.ar',w.SOURCES[C][2])
        self.assertIn('gualeguaychu.gov.ar',w.SOURCES[G][2])
        self.assertIn('corpico.com.ar',w.SOURCES[P][2])
    def test_all_three_produce_read_only_when_fully_verified(self):
        for key,u,t,b,local in ((C,UC,TC,PC,'Fontana'),(G,UG,TG,PG,'Gualeguaychú'),(P,UP,TP,PP,'General Pico')):
            r=run(key,u,t,b)
            self.assertEqual(r['status'],'ok',(key,r))
            self.assertEqual(len(r['notices']),1,(key,r))
            n=r['notices'][0]
            self.assertEqual(n['published_on'],'2026-11-22')
            self.assertEqual(n['locality_hint'],local)
            self.assertEqual(n['status'],'publication_only_not_live')
            self.assertFalse(n['notification_allowed'])
            self.assertIsNone(n['scheduled_start'])
            self.assertIsNone(n['scheduled_end'])
    def test_no_article_date_is_no_notice(self):
        for key,u,t,b in ((C,UC,TC,PC),(G,UG,TG,PG),(P,UP,TP,PP)):
            r=run(key,u,t,b,published='<h1>%s</h1><p>%s</p>'%(t,b))
            self.assertFalse(r['notices'],key)
            self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')
    def test_work_date_in_body_not_publication_date(self):
        fake='<html><h1>%s</h1><p>Los trabajos se haran el 22/11/2026.</p><p>%s</p></html>'%(TG,PG)
        r=run(G,UG,TG,PG,published=fake)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')
    def test_explicit_publication_label_and_date_before_title(self):
        labelled='<html><h1>%s</h1><div>Fecha de publicación: 22/11/2026</div><p>%s</p></html>'%(TG,PG)
        self.assertEqual(len(run(G,UG,TG,PG,published=labelled)['notices']),1)
        preceding='<html><div>22/11/2026</div><h1>%s</h1><p>%s</p></html>'%(TC,PC)
        self.assertEqual(len(run(C,UC,TC,PC,published=preceding)['notices']),1)
    def test_future_or_stale_publication_rejected(self):
        for pub in ('16/11/2026','23/11/2026','31/11/2026'):
            r=run(G,UG,TG,PG,pub=pub)
            self.assertFalse(r['notices'],pub)
    def test_chaco_url_day_mismatch_rejected(self):
        self.assertFalse(run(C,UC,TC,PC,pub='21/11/2026')['notices'])
    def test_topic_electric_cannot_create_water_notices(self):
        title='CORPICO comunica corte programado electrico en General Pico'
        electric='En General Pico se cortará el servicio eléctrico por tareas programadas.'
        for key,url in ((C,UC),(G,UG),(P,UP)):
            self.assertFalse(run(key,url,title,electric)['notices'])
    def test_generic_cortes_programados_not_water(self):
        html='<a href="https://www.corpico.com.ar/cortesprogramados">Cortes programados</a>'
        r=run(P,UP,TP,PP,indexed=html)
        self.assertFalse(r['notices'])
        self.assertEqual(r['articles_checked'],0)
    def test_no_impact_expansion_excluded(self):
        for t in ('Obras Sanitarias amplía la red de agua potable',
                  'Obras Sanitarias inaugura nueva planta de agua potable'):
            self.assertFalse(run(G,UG,t,PG)['notices'])
    def test_explicit_not_affected_is_rejected(self):
        for body in ('Los trabajos en Gualeguaychú se realizan sin afectar el servicio de agua potable.',
                     'En Gualeguaychú no habrá cortes de agua potable por tareas en la red.',
                     'Se trabaja en la red de agua potable para evitar cortes de servicio en Gualeguaychú.'):
            self.assertFalse(run(G,UG,TG,body)['notices'],body)
    def test_restored_service_in_title_not_alert(self):
        title='SAMEEP restableció el servicio de agua potable en Fontana'
        self.assertFalse(run(C,UC,title,PC)['notices'])
    def test_missing_locality_in_chaco(self):
        title='SAMEEP informa corte de agua potable en varios puntos'
        self.assertFalse(run(C,UC,title,'La red de agua potable registra baja presión.')['notices'])
    def test_multiple_chaco_localities_ambiguous(self):
        title='SAMEEP informa corte de agua potable en Fontana y Barranqueras'
        self.assertFalse(run(C,UC,title,'En Fontana y Barranqueras el servicio de agua potable presenta baja presión.')['notices'])
    def test_corpico_not_assume_speluzzi_is_pico(self):
        title='CORPICO informa corte de agua potable en Speluzzi'
        self.assertFalse(run(P,UP,title,'En Speluzzi la red de agua potable tiene baja presión.')['notices'])
    def test_chaco_requires_sameep_in_headline(self):
        title='Chaco inaugura red de agua potable tras reparación de cañería'
        self.assertFalse(run(C,UC,title,PC)['notices'])
    def test_reject_untrusted_http_hosts_and_accounts(self):
        for key,u in ((C,UC),(G,UG),(P,UP)):
            self.assertTrue(w._water3_story_url(key,u),key)
            for bad in (u.replace('https','http',1),u+'?cuenta=123',
                        u+'#parte',u.replace('https://','https://user:pass@'),
                        u.replace('.gob.ar','.gob.ar.evil.net').replace('.gov.ar','.gov.ar.evil.net').replace('.com.ar','.com.ar.evil.net')):
                self.assertFalse(w._water3_story_url(key,bad),bad)
    def test_wrong_company_page_rejected(self):
        self.assertFalse(w._water3_story_url(P,UC))
        self.assertFalse(w._water3_story_url(C,UP))
    def test_deduplicate_index_links(self):
        idx=index(UC,TC)*3
        found,stats=w._water3_index(C,idx,w.SOURCES[C][2],w.checked_instant(NOW))
        self.assertEqual(len(found),1)
        self.assertEqual(stats['valid_article_links_seen'],1)
    def test_max_three_article_requests(self):
        idx=''.join(index('https://www.corpico.com.ar/novedades/%d/'%(2000+i),
                          'CORPICO comunica corte de agua potable en General Pico') for i in range(9))
        found,stats=w._water3_index(P,idx,w.SOURCES[P][2],w.checked_instant(NOW))
        self.assertEqual(len(found),3)
        self.assertEqual(stats['articles_deferred_by_budget'],6)
    def test_no_network_no_false_feed(self):
        d=w.collect_water(NOW,lambda _: '<html></html>')
        self.assertEqual(len(d['sources']),30)
        self.assertFalse(d['notifications_enabled'])
        self.assertFalse(d['android_display_enabled'])
        self.assertTrue(d['android_read_only_pilot_available'])
        self.assertTrue(all(not s['notifications_enabled'] for s in d['sources'].values()))
        self.assertTrue(all(not n['notification_allowed'] for n in d['notices']))
    def test_failures_are_isolated_and_diagnosed(self):
        def fails(u):raise HTTPError(u,403,'Forbidden',None,None)
        r=w.collect_one(G,NOW,fails)
        self.assertEqual(r['notices'],[])
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
    def test_cor_pico_old_news_no_new_events(self):
        title='CORPICO informa corte de agua potable en General Pico'
        self.assertFalse(run(P,UP,title,PP,pub='14/09/2026')['notices'])
    def test_article_with_different_heading_rejected(self):
        bad='<html><h1>Publicidad de agua potable</h1><div>22/11/2026</div><p>%s</p></html>'%PG
        self.assertFalse(run(G,UG,TG,PG,published=bad)['notices'])

if __name__=='__main__':unittest.main()

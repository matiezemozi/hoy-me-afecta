"""Offline contract tests for Corrientes AOSC and Parana municipal radio v5.62."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T03:23:08Z'
AOSC_INDEX='https://aosc.gob.ar/noticias'
AOSC_ART='https://aosc.gob.ar/noticias/TEST20261119'
PNA_INDEX='https://costa.parana.gob.ar/noticias/'
PNA_ART='https://costa.parana.gob.ar/corte-de-suministro-de-agua-en-parana-por-reparaciones/'

def index(key,title='Corte de suministro de agua en Parana por reparaciones'):
    if key=='aosc_corrientes_regulador':
        return '<html><a href="/noticias/TEST20261119">Leer mas</a></html>'
    return '<html><a href="'+PNA_ART+'">'+title+'</a></html>'

def article(key,body,day='19 de noviembre de 2026',title=None):
    if title is None:
        title=('Falta de agua potable en Goya por reparaciones'
               if key=='aosc_corrientes_regulador' else
               'Corte de suministro de agua en Parana por reparaciones')
    return ('<html><h1>'+title+'</h1><span>'+day+'</span>'
            '<p>'+body+'</p></html>')

class PublicNews562(unittest.TestCase):
    def test_sources_added_and_all_push_off(self):
        self.assertEqual(len(w.SOURCES),23)
        self.assertEqual(w.SOURCES['aosc_corrientes_regulador'][2],AOSC_INDEX)
        self.assertEqual(w.SOURCES['parana_radio_municipal_agua'][2],PNA_INDEX)
        for key in w.SOURCES:
            self.assertFalse(w.collect_one(key,NOW,fetcher=lambda _: '<html></html>')['notifications_enabled'])

    def test_regulator_recent_precise_notice(self):
        text='Personal reparo una caneria. La interrupcion del suministro de agua potable afecta varios barrios de Goya.'
        def get(url):return index('aosc_corrientes_regulador') if url==AOSC_INDEX else article('aosc_corrientes_regulador',text)
        r=w.collect_one('aosc_corrientes_regulador',NOW,get)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        n=r['notices'][0]
        self.assertEqual(n['locality_hint'],'Goya')
        self.assertFalse(n['notification_allowed'])
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])

    def test_regulator_old_2023_story_is_stale(self):
        html='<html><h1>La provision de agua en Curuzu Cuatia</h1><div>02-02-2023</div><p>La interrupcion del suministro de agua potable se produjo.</p></html>'
        r=w.collect_one('aosc_corrientes_regulador',NOW,
                        lambda u:index('aosc_corrientes_regulador') if u==AOSC_INDEX else html)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'stale')

    def test_regulator_ambiguous_location_is_not_guessed(self):
        body='La interrupcion del suministro de agua potable afectara a Goya y Bella Vista.'
        html=article('aosc_corrientes_regulador',body,title='Corte de agua en Goya y Bella Vista')
        r=w.collect_one('aosc_corrientes_regulador',NOW,
                        lambda u:index('aosc_corrientes_regulador') if u==AOSC_INDEX else html)
        self.assertEqual(r['notices'],[])

    def test_regulator_headline_no_locality_is_not_guessed(self):
        html=article('aosc_corrientes_regulador','Interrupcion del suministro de agua potable.',
                     title='Obras en el servicio de agua de la provincia')
        r=w.collect_one('aosc_corrientes_regulador',NOW,
                        lambda u:index('aosc_corrientes_regulador') if u==AOSC_INDEX else html)
        self.assertEqual(r['notices'],[])

    def test_parana_water_notice_with_official_domain(self):
        text='Obras Sanitarias realiza reparaciones. La interrupcion del suministro de agua potable afecta la zona sur de Parana.'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:index('parana_radio_municipal_agua') if u==PNA_INDEX else article('parana_radio_municipal_agua',text))
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['locality_hint'],'Parana')
        self.assertEqual(r['notices'][0]['province'],'Entre Rios')

    def test_flood_news_is_not_water_service_outage(self):
        title='Inundaciones: la crecida del rio avanza sobre las viviendas'
        idx=index('parana_radio_municipal_agua',title)
        r=w.collect_one('parana_radio_municipal_agua',NOW,lambda u:idx)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['articles_checked'],0)

    def test_news_saying_no_service_impact_is_rejected(self):
        body='No se interrumpira el suministro de agua potable durante los trabajos de hoy.'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:index('parana_radio_municipal_agua') if u==PNA_INDEX else article('parana_radio_municipal_agua',body))
        self.assertEqual(r['notices'],[])

    def test_undated_article_rejected(self):
        html='<html><h1>Corte de suministro de agua en Parana por reparaciones</h1><p>La interrupcion del suministro de agua potable afecta el centro de la ciudad.</p></html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:index('parana_radio_municipal_agua') if u==PNA_INDEX else html)
        self.assertEqual(r['notices'],[])

    def test_completed_notice_rejected(self):
        html=article('parana_radio_municipal_agua',
            'La interrupcion del suministro de agua potable afecto varios barrios.',
            title='Finalizaron reparaciones de agua en Parana')
        idx=index('parana_radio_municipal_agua',title='Finalizaron reparaciones de agua en Parana')
        r=w.collect_one('parana_radio_municipal_agua',NOW,lambda u:idx if u==PNA_INDEX else html)
        self.assertEqual(r['notices'],[])

    def test_domains_rejected_including_userinfo_and_http(self):
        for url in ('https://other.gov.ar/noticias/TEST20261119',
                    'http://aosc.gob.ar/noticias/TEST20261119',
                    'https://aosc.gob.ar@evil.example/noticias/TEST20261119',
                    'https://aosc.gob.ar/noticias/TEST20261119?q=1'):
            self.assertFalse(w._public_news_valid_url(url,'aosc_corrientes_regulador'))

    def test_http_403_not_treated_as_no_outages(self):
        def fetch(url):raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one('aosc_corrientes_regulador',NOW,fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['http_status'],403)
        self.assertFalse(r['notifications_enabled'])

    def test_malformed_dates_rejected(self):
        html=article('aosc_corrientes_regulador',
                     'La interrupcion del suministro de agua potable afecta Goya.',day='32-15-2026')
        r=w.collect_one('aosc_corrientes_regulador',NOW,
                        lambda u:index('aosc_corrientes_regulador') if u==AOSC_INDEX else html)
        self.assertEqual(r['notices'],[])

if __name__=='__main__':unittest.main()

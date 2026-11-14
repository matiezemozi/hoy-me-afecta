"""Offline tests for two conservative water services: AySA and SAMEEP."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-14T17:00:00Z'
INDEX='<html><a href="/noticias/detalle/199/">Resistencia: reparacion de red de agua potable</a><a href="https://evil.test/noticias/detalle/200/">Otra noticia</a></html>'
ART='<html><h1>Novedades</h1><h5>14/11/2026</h5><h2>Resistencia: trabajos de agua potable</h2><p>Se vera afectado el servicio de agua potable en barrios de Resistencia. Las cuadrillas trabajan en una caneria y solicitan cuidar las reservas domiciliarias hasta la normalizacion.</p></html>'
URL='https://sameep.gob.ar/noticias/detalle/199/'

class NewWaterSources(unittest.TestCase):
    def test_source_count(self):
        self.assertEqual(len(w.SOURCES),9)
    def test_aysa_lookup_does_not_access_account(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return '<h1>Chequea si estas afectado por interrupcion del servicio</h1><p>Ingresa tu cuenta de servicio</p>'
        data=w.collect_one('aysa_amba',STAMP,fetcher=fetch)
        self.assertEqual(calls,[w.SOURCES['aysa_amba'][2]])
        self.assertEqual(data['status'],'unverified')
        self.assertEqual(data['access_mode'],'account_required')
        self.assertTrue(data['account_lookup_required'])
        self.assertEqual(data['notices'],[])
        self.assertFalse(data['notifications_enabled'])
    def test_aysa_unknown_content_is_not_verified(self):
        data=w.collect_one('aysa_amba',STAMP,fetcher=lambda _: '<h1>AySA</h1>')
        self.assertEqual(data['status'],'unverified')
        self.assertEqual(data['notices'],[])
    def test_aysa_timeout_safe(self):
        data=w.collect_one('aysa_amba',STAMP,fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(data['status'],'unverified')
        self.assertFalse(data['portal_reachable'])
    def test_sameep_notice_precise_locality(self):
        item,d=w._sameep_article(ART,URL,w.checked_instant(STAMP))
        self.assertEqual(item['locality_hint'],'Resistencia')
        self.assertEqual(item['published_on'],'2026-11-14')
        self.assertFalse(item['notification_allowed'])
        self.assertEqual(d.isoformat(),'2026-11-14')
    def test_sameep_old_post_excluded(self):
        item,_=w._sameep_article(ART.replace('14/11/2026','20/10/2026'),URL,w.checked_instant(STAMP))
        self.assertIsNone(item)
    def test_sameep_future_date_excluded(self):
        item,_=w._sameep_article(ART.replace('14/11/2026','18/11/2026'),URL,w.checked_instant(STAMP))
        self.assertIsNone(item)
    def test_sameep_ambiguous_locality_excluded(self):
        item,_=w._sameep_article(ART.replace('Resistencia: trabajos','Resistencia y Barranqueras: trabajos'),URL,w.checked_instant(STAMP))
        self.assertIsNone(item)
    def test_sameep_no_cuts_excluded(self):
        item,_=w._sameep_article(ART.replace('Se vera afectado','Sin cortes del servicio. Se vera afectado'),URL,w.checked_instant(STAMP))
        self.assertIsNone(item)
    def test_sameep_resolved_title_excluded(self):
        item,_=w._sameep_article(ART.replace('Resistencia: trabajos','Resistencia: finalizaron trabajos'),URL,w.checked_instant(STAMP))
        self.assertIsNone(item)
    def test_sameep_official_links_only(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES['sameep_chaco'][2]:return INDEX
            if url==URL:return ART
            raise AssertionError(url)
        data=w.collect_one('sameep_chaco',STAMP,fetcher=fetch)
        self.assertEqual(calls,[w.SOURCES['sameep_chaco'][2],URL])
        self.assertEqual(data['status'],'ok')
        self.assertEqual(len(data['notices']),1)
    def test_sameep_archive_not_normal_service(self):
        def fetch(url):return INDEX if url==w.SOURCES['sameep_chaco'][2] else ART.replace('14/11/2026','20/10/2026')
        data=w.collect_one('sameep_chaco',STAMP,fetcher=fetch)
        self.assertEqual(data['status'],'stale')
        self.assertEqual(data['notices'],[])
    def test_source_error_isolated(self):
        data=w.collect_one('sameep_chaco',STAMP,fetcher=lambda _: (_ for _ in ()).throw(ConnectionError()))
        self.assertEqual(data['status'],'unverified')
    def test_all_sources_notifications_disabled(self):
        d=w.collect_water(STAMP,fetcher=lambda _: '<h1>No hay novedades</h1>')
        self.assertEqual(len(d['sources']),9)
        self.assertFalse(d['notifications_enabled'])
        self.assertFalse(d['android_display_enabled'])
        self.assertTrue(all(x['notifications_enabled'] is False for x in d['sources'].values()))

if __name__=='__main__':unittest.main()

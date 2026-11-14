"""EDOS Concordia public municipal dated water-service notices (offline)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-14T18:35:04Z'
BASE='https://www.concordia.gob.ar/noticias?area=obras-sanitarias'
CUT='https://www.concordia.gob.ar/noticias/el-municipio-anuncio-un-corte-programado-de-agua'
DONE='https://www.concordia.gob.ar/noticias/finalizaron-los-trabajos'
INFO='https://www.concordia.gob.ar/noticias/nuevo-plan-de-obras'
OLD='https://www.concordia.gob.ar/noticias/paro-de-planta-en-octubre'
INDEX=f'''<html><body><a href="/noticias/el-municipio-anuncio-un-corte-programado-de-agua">Corte programado de agua por renovacion de canerias</a>
<a href="/noticias/finalizaron-los-trabajos">Finalizaron los trabajos de agua y se normaliza el servicio</a>
<a href="/noticias/nuevo-plan-de-obras">Avanzan obras para el agua potable</a>
<a href="https://www.concordia.gob.ar.evil.tld/noticias/falso">Corte de agua falso</a>
<a href="http://www.concordia.gob.ar/noticias/unsafe">Corte inseguro</a>
<a href="/noticias/el-municipio-anuncio-un-corte-programado-de-agua">Corte programado de agua por renovacion de canerias</a>
</body></html>'''
CUT_ART='''<html><body>
<div>Noticia 14 de noviembre de 2026</div>
<h1>Corte programado de agua potable por recambio de válvulas y trabajos de extensión</h1>
<p>La Municipalidad de Concordia y el Ente Descentralizado de Obras Sanitarias informan que se interrumpirá el servicio de agua potable en algunos barrios de la ciudad debido al recambio de válvulas estratégicas.</p>
<p>Los barrios afectados serán Sarmiento y San Miguel II, en la ciudad de Concordia, entre las primeras horas y el mediodía. La recuperación del servicio será progresiva.</p>
<h2>Noticias relacionadas</h2><p>Otros avisos de la provincia</p>
</body></html>'''
DONE_ART='''<html><body><div>Noticia 14 de noviembre de 2026</div><h1>Finalizaron los trabajos y se normaliza el servicio de agua</h1><p>Se interrumpió el servicio de agua potable para renovar las conexiones y ya se ha reanudado la producción.</p></body></html>'''
INFO_ART='''<html><body><div>Noticia 14 de noviembre de 2026</div><h1>Avanzan obras para mejorar la red de agua potable</h1><p>La Municipalidad de Concordia refuerza las conexiones de servicio para evitar futuras interrupciones. Las tareas se desarrollan sin afectar el servicio.</p></body></html>'''

class EdosTests(unittest.TestCase):
    def test_new_official_source_and_schema(self):
        self.assertIn('edos_concordia',w.SOURCES)
        self.assertEqual(w.SOURCES['edos_concordia'][1],'Entre Ríos')
        self.assertGreaterEqual(len(w.SOURCES),11)
    def test_dated_interruption(self):
        n,d=w._edos_article(CUT_ART,CUT,w.checked_instant(STAMP))
        self.assertEqual(d.isoformat(),'2026-11-14')
        self.assertEqual(n['locality_hint'],'Concordia')
        self.assertEqual(n['province'],'Entre Ríos')
        self.assertIn('Sarmiento',n['zone_detail'])
        self.assertIn('San Miguel',n['zone_detail'])
        self.assertEqual(n['company'],'EDOS Concordia')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_start'])
        self.assertEqual(n['status'],'publication_only_not_live')
    def test_notices_not_inferred_from_old_news(self):
        old=CUT_ART.replace('14 de noviembre de 2026','31 de octubre de 2026')
        n,d=w._edos_article(old,CUT,w.checked_instant(STAMP))
        self.assertIsNone(n)
        self.assertEqual(d.isoformat(),'2026-10-31')
    def test_past_notice_with_unknown_end_not_live(self):
        one=CUT_ART.replace('14 de noviembre de 2026','12 de noviembre de 2026')
        n,d=w._edos_article(one,CUT,w.checked_instant(STAMP))
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_end'])
    def test_finished_is_not_outage(self):
        self.assertIsNone(w._edos_article(DONE_ART,DONE,w.checked_instant(STAMP))[0])
    def test_generic_works_is_not_outage(self):
        self.assertIsNone(w._edos_article(INFO_ART,INFO,w.checked_instant(STAMP))[0])
    def test_no_negated_impact(self):
        x=CUT_ART.replace('se interrumpirá el servicio','no se interrumpirá el servicio')
        self.assertIsNone(w._edos_article(x,CUT,w.checked_instant(STAMP))[0])
    def test_future_publication_rejected(self):
        x=CUT_ART.replace('14 de noviembre de 2026','17 de noviembre de 2026')
        self.assertIsNone(w._edos_article(x,CUT,w.checked_instant(STAMP))[0])
    def test_invalid_publication_rejected(self):
        x=CUT_ART.replace('14 de noviembre de 2026','31 de noviembre de 2026')
        self.assertIsNone(w._edos_article(x,CUT,w.checked_instant(STAMP))[0])
    def test_missing_publication_rejected(self):
        x=CUT_ART.replace('14 de noviembre de 2026','sin fecha')
        self.assertIsNone(w._edos_article(x,CUT,w.checked_instant(STAMP))[0])
    def test_official_host_only_duplicates_deduplicated(self):
        calls=[]
        pages={BASE:INDEX,CUT:CUT_ART,DONE:DONE_ART,INFO:INFO_ART}
        def fetch(url):
            calls.append(url)
            return pages[url]
        result=w.collect_one('edos_concordia',STAMP,fetcher=fetch)
        self.assertEqual(calls,[BASE,CUT,DONE,INFO])
        self.assertEqual(result['article_links_seen'],3)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(result['parser_revision'],'EDOS-MUNICIPIO-v5.43')
    def test_no_old_news_claims_normal_service(self):
        old=CUT_ART.replace('14 de noviembre de 2026','31 de octubre de 2026')
        def fetch(url):return INDEX if url==BASE else old
        result=w.collect_one('edos_concordia',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'stale')
        self.assertFalse(result['notices'])
        self.assertIn('antiguas',result['message'])
    def test_error_does_not_invent_notice(self):
        result=w.collect_one('edos_concordia',STAMP,fetcher=lambda _: (_ for _ in ()).throw(ConnectionError()))
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['notices'],[])
    def test_article_error_isolated(self):
        def fetch(url):
            if url==BASE:return INDEX
            if url==CUT:raise TimeoutError()
            return DONE_ART
        result=w.collect_one('edos_concordia',STAMP,fetcher=fetch)
        self.assertFalse(result['notices'])
        self.assertTrue(any(x.get('error_type')=='TimeoutError' for x in result['source_attempts']))
    def test_total_pilot_keeps_notifications_disabled(self):
        result=w.collect_water(STAMP,fetcher=lambda _: '<h1>Ningun aviso</h1>')
        self.assertGreaterEqual(len(result['sources']),11)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(x['notifications_enabled'] is False for x in result['sources'].values()))
    def test_aysa_limitation_is_explicit(self):
        result=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=lambda _: '<h1>Sin datos</h1>')
        self.assertIn('comunicados de emergencia',result['coverage_limitation'])

if __name__=='__main__':unittest.main()

"""OSSE Mar del Plata official notices; read-only Android metadata (offline)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-14T19:01:42Z'
INDEX_URL='https://www.osmgp.gov.ar/osse/noticias/'
ARTICLE_URL='https://www.osmgp.gov.ar/osse/osse-ejecutara-tareas-de-mantenimiento-electrico-en-al-estacion-elevadora-de-agua-plaza-mitre/'
FINISHED_URL='https://www.osmgp.gov.ar/osse/finalizaron-los-trabajos-en-la-red-de-agua/'
UNRELATED_URL='https://www.osmgp.gov.ar/osse/licitacion-de-obras-sanitarias/'
INDEX='''<html><body>
<a href="/osse/osse-ejecutara-tareas-de-mantenimiento-electrico-en-al-estacion-elevadora-de-agua-plaza-mitre/">OSSE ejecutará tareas de mantenimiento eléctrico en la estación elevadora de agua Plaza Mitre</a>
<a href="/osse/finalizaron-los-trabajos-en-la-red-de-agua/">Finalizaron los trabajos en el servicio de agua</a>
<a href="/osse/licitacion-de-obras-sanitarias/">OSSE licita obras cloacales</a>
<a href="https://www.osmgp.gov.ar.evil.test/osse/corte-de-agua/">Corte de agua malicioso</a>
<a href="http://www.osmgp.gov.ar/osse/corte-de-agua/">Corte de agua sin https</a>
<a href="/osse/osse-ejecutara-tareas-de-mantenimiento-electrico-en-al-estacion-elevadora-de-agua-plaza-mitre/">OSSE ejecutará tareas de mantenimiento eléctrico en la estación elevadora de agua Plaza Mitre</a>
</body></html>'''
ARTICLE='''<html><body>
<h1>OSSE ejecutará tareas de mantenimiento eléctrico en la estación elevadora de agua Plaza Mitre</h1>
<div>por prensa | Nov 14, 2026 | Obras y servicios</div>
<p>Obras Sanitarias Mar del Plata informa que en el marco de sus tareas de mantenimiento realizará una intervención técnica este sábado en la estación de agua Plaza Mitre.</p>
<p>Los equipos podrían generar una baja temporaria en la presión del servicio de agua potable en la zona de influencia de la terminal.</p>
<p>Las zonas afectadas serán las comprendidas entre la franja costera, avenida Constitución, avenida Jara, avenida Juan B. Justo y calle Olavarría.</p>
<h2>Noticias relacionadas</h2><p>En octubre hubo una obra de cloacas.</p>
</body></html>'''
DONE='''<html><body><h1>Finalizaron los trabajos en la red de agua y el servicio se normalizó</h1><div>Nov 14, 2026</div><p>Obras Sanitarias Mar del Plata confirmó que el servicio ya fue restablecido tras las tareas.</p></body></html>'''

class OsseTests(unittest.TestCase):
    def test_source_config(self):
        self.assertIn('osse_mar_del_plata',w.SOURCES)
        self.assertEqual(w.SOURCES['osse_mar_del_plata'][1],'Buenos Aires')
        self.assertGreaterEqual(len(w.SOURCES),12)
    def test_precise_official_dated_story(self):
        n,p=w._osse_article(ARTICLE,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual(p.isoformat(),'2026-11-14')
        self.assertEqual(n['locality_hint'],'Mar del Plata')
        self.assertEqual(n['province'],'Buenos Aires')
        self.assertFalse(n['notification_allowed'])
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_end'])
        self.assertIn('Constitución',n['zone_detail'])
        self.assertIn('no_toda_la_ciudad',n['area_precision'])
    def test_old_article_not_current(self):
        old=ARTICLE.replace('Nov 14, 2026','May 27, 2026')
        n,p=w._osse_article(old,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertIsNone(n)
        self.assertEqual(p.isoformat(),'2026-05-27')
    def test_finish_not_cut(self):
        self.assertIsNone(w._osse_article(DONE,FINISHED_URL,w.checked_instant(STAMP))[0])
    def test_negated_impact_is_not_cut(self):
        safe=ARTICLE.replace('podrían generar una baja temporaria en la presión del servicio de agua potable',
                             'no se interrumpirá el servicio de agua potable')
        self.assertIsNone(w._osse_article(safe,ARTICLE_URL,w.checked_instant(STAMP))[0])
    def test_without_locality_not_infer(self):
        no_loc=ARTICLE.replace('Obras Sanitarias Mar del Plata','La empresa')
        no_loc=no_loc.replace('Plaza Mitre','Plaza Central').replace('avenida Constitución','avenida Corrientes')
        self.assertIsNone(w._osse_article(no_loc,ARTICLE_URL,w.checked_instant(STAMP))[0])
    def test_without_date_no_notice(self):
        self.assertIsNone(w._osse_article(ARTICLE.replace('Nov 14, 2026','fecha no visible'),ARTICLE_URL,w.checked_instant(STAMP))[0])
    def test_invalid_date_no_notice(self):
        self.assertIsNone(w._osse_article(ARTICLE.replace('Nov 14, 2026','Nov 31, 2026'),ARTICLE_URL,w.checked_instant(STAMP))[0])
    def test_date_in_related_articles_not_used(self):
        fixture=ARTICLE.replace('Nov 14, 2026','fecha no visible').replace('En octubre hubo una obra de cloacas.',
            'Obra 14 de noviembre de 2026 en otra ciudad')
        self.assertIsNone(w._osse_article(fixture,ARTICLE_URL,w.checked_instant(STAMP))[0])
    def test_full_collector_one_official_notice(self):
        calls=[]
        pages={INDEX_URL:INDEX,ARTICLE_URL:ARTICLE,FINISHED_URL:DONE}
        def fetch(url):
            calls.append(url)
            return pages[url]
        result=w.collect_one('osse_mar_del_plata',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['parser_revision'],'OSSE-NEWS-v5.44')
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(calls,[INDEX_URL,ARTICLE_URL,FINISHED_URL])
        self.assertEqual(result['article_links_seen'],2)
    def test_old_stale_without_invented_current_status(self):
        old=ARTICLE.replace('Nov 14, 2026','May 27, 2026')
        result=w.collect_one('osse_mar_del_plata',STAMP,fetcher=lambda url:INDEX if url==INDEX_URL else old)
        self.assertEqual(result['status'],'stale')
        self.assertFalse(result['notices'])
    def test_unreachable_isolated(self):
        result=w.collect_one('osse_mar_del_plata',STAMP,fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'],'unverified')
        self.assertFalse(result['notices'])
    def test_read_only_status_distinguished_from_push_notification(self):
        result=w.collect_water(STAMP,fetcher=lambda _: '<h1>Sin datos</h1>')
        self.assertEqual(result['status'],'pilot_read_only_in_android')
        self.assertTrue(result['android_read_only_pilot_available'])
        # Guard retained for compatibility with the v5.38 electricity/water validator.
        self.assertFalse(result['android_display_enabled'])
        self.assertFalse(result['notifications_enabled'])
        self.assertTrue(all(n['notifications_enabled'] is False for n in result['sources'].values()))

if __name__=='__main__': unittest.main()

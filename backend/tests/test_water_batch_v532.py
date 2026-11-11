"""Offline tests for official water sources; no real network requests."""
from __future__ import annotations
import copy
from datetime import date, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
import build_water_feed as b

STAMP='2026-11-10T23:30:00Z'
LISTING='''<html><body><a href="/noticias/5104">Bahía Blanca: trabajos programados en la red de agua</a>
<a href="https://www.aguasbonaerenses.com.ar/noticias/5105">Patagones: baja presión</a>
<a href="https://evil.test/noticias/9900">false domain</a></body></html>'''
ARTICLE='''<html><body><h1>Noticias</h1><h1>Bahía Blanca: trabajos programados en la red de agua</h1>
10-11-2026
<p>El próximo jueves 12 se realizarán trabajos programados en tres puntos de la ciudad.</p>
<p>En General Daniel Cerri, en el marco de la obra de reemplazo y ampliación del acueducto que abastece a la localidad,
se prevén tareas a la altura de la Ruta 3 y el acceso a la localidad, por lo que se deberá interrumpir el suministro de agua desde las 8 y hasta hora de la tarde.</p>
<p>En tanto, en el marco de los recambios de cañería que lleva adelante la Dirección Provincial de Agua y Cloacas (DIPAC)
en la ciudad, se ejecutarán tareas en las intersecciones de Terrada y Roca; Brown y Undiano, y Brown y Montevideo.
De esta manera, se afectará el suministro en la calle Terrada, entre Roca y Blandengues, y el cuadrante Italia, Undiano, Montevideo y San Martín, hasta la finalización de las tareas.</p>
<p>Por esta razón, se solicita a las personas usuarias de los sectores mencionados que realicen las reservas de agua.</p>
<h3>Relacionado...</h3><p>Visita 12-12-2026 agua otro lado</p></body></html>'''
PATAGONES='''<h1>Patagones: baja presión en la red de agua en la zona alta</h1>10-11-2026
<p>Se están registrando episodios de baja presión y algunas faltas de agua en la zona alta de Carmen de Patagones,
esto es Barrio Bicentenario, Barrio 99 Viviendas y Barrio Dolores.</p>'''
AYSAM='''<html><table><tr><th>Zona</th><th>Departamento</th><th>Tipo</th><th>Fecha Inicio</th>
<th>Hora inicio</th><th>Fecha Fin</th><th>Hora fin</th></tr>
<tr><td>Barrio Centro y calles de la zona norte</td><td>Capital</td><td>Programado</td><td>12-11-2026</td><td>09:00</td><td>12-11-2026</td><td>14:00</td></tr>
<tr><td>Calles Rivadavia entre calles A y B</td><td>Guaymallen</td><td>Imprevisto</td><td>12-11-2026</td><td>10:00</td><td>12-11-2026</td><td>12:00</td></tr>
<tr><td>Zona antigua de San Martin, por todos lados</td><td>Este</td><td>Programado</td><td>14-10-2026</td><td>09:00</td><td>14-10-2026</td><td>11:00</td></tr></table></html>'''
SALTA='''<h3>CORTES PROGRAMADOS</h3><div>En este momento los trabajos en desarrollo no afectan el servicio.</div>'''

class WaterV532Tests(unittest.TestCase):
    def setUp(self):
        self.now=w.checked_instant(STAMP)

    def test_source_count(self):
        self.assertEqual(len(w.SOURCES),5)

    def test_timezone(self):
        self.assertEqual(self.now.hour,20)

    def test_naive_date_rejected(self):
        with self.assertRaises(ValueError):w.checked_instant('2026-11-10T15:00:00')

    def test_absa_two_localities(self):
        notes,published=w._absa_article(ARTICLE,'https://www.aguasbonaerenses.com.ar/noticias/5104',self.now)
        self.assertEqual(len(notes),2)
        self.assertEqual(published,date(2026,11,10))
        self.assertEqual({n['locality_hint'] for n in notes},{'General Daniel Cerri','Bahía Blanca'})

    def test_absa_start_without_end(self):
        notes,_=w._absa_article(ARTICLE,'https://www.aguasbonaerenses.com.ar/noticias/5104',self.now)
        cerri=next(n for n in notes if n['locality_hint']=='General Daniel Cerri')
        bahia=next(n for n in notes if n['locality_hint']=='Bahía Blanca')
        self.assertEqual(cerri['scheduled_start'],'2026-11-12T08:00-03:00')
        self.assertIsNone(cerri['scheduled_end'])
        self.assertIsNone(bahia['scheduled_start'])
        self.assertIsNone(bahia['scheduled_end'])
        self.assertEqual(bahia['time_precision'],'date_only')

    def test_absa_publication_not_live(self):
        notes,_=w._absa_article(PATAGONES,'https://www.aguasbonaerenses.com.ar/noticias/5105',self.now)
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['status'],'publication_only_not_live')
        self.assertFalse(notes[0]['notification_allowed'])

    def test_absa_old_article_rejected(self):
        old=ARTICLE.replace('10-11-2026','10-10-2026')
        notes,_=w._absa_article(old,'https://www.aguasbonaerenses.com.ar/noticias/5104',self.now)
        self.assertEqual(notes,[])

    def test_absa_weekday_mismatch_rejected(self):
        changed=ARTICLE.replace('jueves 12','viernes 12')
        notes,_=w._absa_article(changed,'https://www.aguasbonaerenses.com.ar/noticias/5104',self.now)
        self.assertFalse(any(n['kind']=='planned_water_service_impact' for n in notes))

    def test_absa_completed_bulletin_rejected(self):
        old=PATAGONES.replace('Patagones: baja presión','Finalizaron: baja presión')
        notes,_=w._absa_article(old,'https://www.aguasbonaerenses.com.ar/noticias/5105',self.now)
        self.assertEqual(notes,[])

    def test_absa_cross_domain_not_fetched(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES['absa_buenos_aires'][2]:return LISTING
            if url.endswith('5104'):return ARTICLE
            if url.endswith('5105'):return PATAGONES
            raise AssertionError(url)
        got=w.collect_one('absa_buenos_aires',STAMP,fetcher=fetch)
        self.assertEqual(got['status'],'ok')
        self.assertEqual(len(got['notices']),3)
        self.assertEqual(len(calls),3)
        self.assertTrue(all('evil' not in url for url in calls))

    def test_absa_failure_does_not_fabricate_clear(self):
        result=w.collect_one('absa_buenos_aires',STAMP,fetcher=lambda url: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['notices'],[])

    def test_absa_no_articles_is_unverified(self):
        result=w.collect_one('absa_buenos_aires',STAMP,fetcher=lambda _: '<html><body>Noticias</body></html>')
        self.assertEqual(result['status'],'unverified')

    def test_absa_unrelated_nav_date_not_used(self):
        result,_=w._absa_article('<h1>Pago facturas</h1><p>Trabajos de agua 12-11-2026</p>',
                                 'https://www.aguasbonaerenses.com.ar/noticias/5104',self.now)
        self.assertEqual(result,[])

    def test_aysam_table_parsed_only_planned(self):
        notes,count,newest=w._parse_aysam(AYSAM,self.now,w.SOURCES['aysam_mendoza'][2])
        self.assertEqual(count,3)
        self.assertEqual(newest,date(2026,11,12))
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['scheduled_end'],'2026-11-12T14:00-03:00')

    def test_aysam_old_only_stale(self):
        old=AYSAM.replace('12-11-2026','12-10-2026')
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=lambda _:old)
        self.assertEqual(result['status'],'stale')
        self.assertEqual(result['notices'],[])

    def test_aysam_bad_hours_rejected(self):
        malformed=AYSAM.replace('14:00','02:00')
        notes,count,_=w._parse_aysam(malformed,self.now,w.SOURCES['aysam_mendoza'][2])
        self.assertEqual(len(notes),0)

    def test_aysam_real_future_in_mock(self):
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=lambda _:AYSAM)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['notices'][0]['category'],'agua')

    def test_salta_explicit_empty(self):
        result=w.collect_one('aguas_del_norte_salta',STAMP,fetcher=lambda _:SALTA)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['coverage_horizon'],'works_in_progress_only')
        self.assertEqual(result['notices'],[])

    def test_salta_generic_empty_unverified(self):
        result=w.collect_one('aguas_del_norte_salta',STAMP,fetcher=lambda _: '<h1>Cortes programados</h1>')
        self.assertEqual(result['status'],'unverified')

    def test_salta_error_unverified(self):
        result=w.collect_one('aguas_del_norte_salta',STAMP,fetcher=lambda _: (_ for _ in ()).throw(OSError()))
        self.assertEqual(result['status'],'unverified')

    def test_other_sites_do_not_create_notices(self):
        for key in ('aguas_cordobesas','aguas_santafesinas'):
            result=w.collect_one(key,STAMP,fetcher=lambda _: '<h1>Trabajos en tu zona</h1><input>')
            self.assertEqual(result['notices'],[])
            self.assertEqual(result['status'],'unverified')
            self.assertTrue(result['account_lookup_required_for_address'])

    def test_outdated_archive_stale(self):
        got=w.collect_one('aguas_cordobesas',STAMP,fetcher=lambda _: '<p>Trabajos de agua 04/11/2026 en barrio</p>')
        self.assertEqual(got['status'],'stale')

    def test_total_aggregate_keeps_water_only(self):
        def fetch(url):
            if 'aguasbonaerenses' in url:
                if url.endswith('/noticias/'):return LISTING
                return ARTICLE if url.endswith('5104') else PATAGONES
            if 'nortesalta' in url:return SALTA
            if 'aysam' in url:return AYSAM
            return '<h1>Acceso a zona</h1>'
        result=w.collect_water(STAMP,fetcher=fetch)
        self.assertEqual(len(result['sources']),5)
        self.assertEqual(len(result['notices']),4)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(x['category']=='agua' for x in result['notices']))

    def test_invalid_source_key_rejected(self):
        with self.assertRaises(KeyError):w.collect_one('inventada',STAMP,fetcher=lambda _:SALTA)

    def test_merge_does_not_touch_electricity(self):
        demo={'schema_version':1,'generated_at':'prior','alerts':[{'id':'electricidad'}],
              'coverage':{'water':'manual_notices_only'},'provincial_electricity':{'some':'record'}}
        result=w.collect_water(STAMP,fetcher=lambda _: '<p>Sin publicaciones</p>')
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'feed.json'
            water=Path(d)/'water.json'
            dest.write_text(json.dumps(demo),encoding='utf-8')
            b.main(['--out',str(water),'--merge',str(dest)],collector=lambda _:result)
            merged=json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(merged['alerts'],demo['alerts'])
            self.assertEqual(merged['coverage'],demo['coverage'])
            self.assertEqual(merged['provincial_electricity'],demo['provincial_electricity'])
            self.assertEqual(merged['generated_at'],'prior')
            self.assertEqual(merged['water_services']['category'],'agua')
            self.assertTrue(water.is_file())

    def test_refuse_bad_main_feed(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'feed.json'
            dest.write_text(json.dumps({'schema_version':2,'alerts':[]}),encoding='utf-8')
            with self.assertRaises(ValueError):
                b.main(['--out',str(Path(d)/'water.json'),'--merge',str(dest)],collector=lambda _:{'category':'agua'})
            self.assertEqual(json.loads(dest.read_text())['schema_version'],2)

if __name__=='__main__':unittest.main()

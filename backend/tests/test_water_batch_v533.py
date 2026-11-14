"""v5.33 offline checks for Río Negro/Catamarca and safer water reports."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-11T19:33:41Z'
NOW=w.checked_instant(STAMP)
CATEGORY='''<html><body><nav><a href="https://evil.example/any">Un aviso externo: parece real</a></nav>
<h4><a href="/coronel-belisle-arsa-realizara-trabajos-para-fortalecer-el-sistema-de-abastecimiento-de-agua/">Coronel Belisle: ARSA realizará trabajos para fortalecer el sistema de abastecimiento de agua</a></h4>
<h4><a href="/cipolletti-arsa-inicio-trabajos-en-calle-mengelle-para-optimizar-la-red-de-agua-potable-en-toda-la-ciudad/">Cipolletti: ARSA inició trabajos en calle Mengelle para optimizar la red de agua potable en toda la ciudad</a></h4>
<h4><a href="/bariloche-arsa-ejecutara-trabajos-para-fortalecer-la-red-de-agua-potable/">Bariloche: ARSA ejecutará trabajos para fortalecer la red de agua potable en Riberas del Ñireco</a></h4>
<a href="/category/interrupciones/">Interrupciones de servicio</a>
</body></html>'''
BELISLE='''<html><body><h1>Coronel Belisle: ARSA realizará trabajos para fortalecer el sistema de abastecimiento de agua</h1>
11 noviembre, 2026 <p>Aguas Rionegrinas informa que este miércoles 11, desde las 21 y hasta entrada la madrugada, se llevarán adelante trabajos programados de lavado del acueducto que abastece a la localidad de Coronel Belisle.</p>
<p>Durante el desarrollo de los trabajos, los usuarios podrán registrar baja presión y turbiedad en el agua, por lo que se solicita hacer un uso responsable de las reservas domiciliarias hasta la finalización de las tareas.</p></body></html>'''
CIPOLLETTI='''<html><body><h1>Cipolletti: ARSA inició trabajos en calle Mengelle para optimizar la red de agua potable en toda la ciudad</h1>
11 noviembre, 2026 <p>Aguas Rionegrinas informa que personal del servicio local inició trabajos de intervención sobre una cañería ubicada en calle Mengelle, con el objetivo de optimizar el funcionamiento de la red y fortalecer la prestación del servicio de agua potable.</p>
<p>Las tareas comenzaron a las 13 horas y se extenderán hasta aproximadamente las 16 de este miércoles.</p>
<p>Durante el desarrollo de los trabajos, podrá registrarse baja presión de agua potable en toda la ciudad.</p></body></html>'''
BARILOCHE='''<html><body><h1>Bariloche: ARSA ejecutará trabajos para fortalecer la red de agua potable en el sector de Riberas del Ñireco</h1>
11 noviembre, 2026 <p>Aguas Rionegrinas informa que este jueves 12 de noviembre se realizarán trabajos de empalme de cañería en Bariloche, una intervención destinada a fortalecer la infraestructura.</p>
<p>Por las tareas, se podrá registrar baja presión de agua potable en el sector de Riberas del Ñireco.</p></body></html>'''
OFFICE='''<html><body><h1>Cinco Saltos: oficina de ARSA permanecerá cerrada</h1>11 noviembre, 2026
<p>El servicio de agua potable no presenta novedades, pero la oficina de atención al público estará cerrada.</p></body></html>'''

class WaterV533Tests(unittest.TestCase):
    def test_seven_sources(self):
        self.assertGreaterEqual(len(w.SOURCES),7)

    def test_arsa_belisle_scheduled_start_without_unproven_end(self):
        notes,published=w._arsa_article(BELISLE,'https://aguasrionegrinas.com/uno/',NOW)
        self.assertEqual(len(notes),1)
        n=notes[0]
        self.assertEqual(n['locality_hint'],'Coronel Belisle')
        self.assertEqual(n['scheduled_date'],'2026-11-11')
        self.assertEqual(n['scheduled_start'],'2026-11-11T21:00-03:00')
        self.assertIsNone(n['scheduled_end'])
        self.assertEqual(n['kind'],'planned_water_service_impact')
        self.assertFalse(n['notification_allowed'])
        self.assertEqual(published.isoformat(),'2026-11-11')

    def test_arsa_past_started_work_not_future(self):
        notes,_=w._arsa_article(CIPOLLETTI,'https://aguasrionegrinas.com/dos/',NOW)
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['status'],'publication_only_not_live')
        self.assertNotIn('scheduled_date',notes[0])

    def test_arsa_next_day_date_no_invented_hour(self):
        notes,_=w._arsa_article(BARILOCHE,'https://aguasrionegrinas.com/tres/',NOW)
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['scheduled_date'],'2026-11-12')
        self.assertEqual(notes[0]['time_precision'],'date_only')
        self.assertIsNone(notes[0]['scheduled_start'])

    def test_arsa_office_notice_excluded(self):
        self.assertEqual(w._arsa_article(OFFICE,'https://aguasrionegrinas.com/oficina/',NOW)[0],[])

    def test_arsa_old_article_rejected(self):
        old=BELISLE.replace('11 noviembre, 2026','11 octubre, 2026')
        self.assertEqual(w._arsa_article(old,'https://aguasrionegrinas.com/uno/',NOW)[0],[])

    def test_arsa_weekday_error_not_scheduled(self):
        bad=BELISLE.replace('miércoles 11','viernes 11')
        notes,_=w._arsa_article(bad,'https://aguasrionegrinas.com/uno/',NOW)
        self.assertFalse(any(n['kind']=='planned_water_service_impact' for n in notes))

    def test_arsa_category_limited_domain(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES['aguas_rionegrinas_arsa'][2]:return CATEGORY
            if url.endswith('/coronel-belisle-arsa-realizara-trabajos-para-fortalecer-el-sistema-de-abastecimiento-de-agua/'):return BELISLE
            if url.endswith('/cipolletti-arsa-inicio-trabajos-en-calle-mengelle-para-optimizar-la-red-de-agua-potable-en-toda-la-ciudad/'):return CIPOLLETTI
            if url.endswith('/bariloche-arsa-ejecutara-trabajos-para-fortalecer-la-red-de-agua-potable/'):return BARILOCHE
            raise ValueError(url)
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),3)
        self.assertEqual(result['articles_checked'],3)
        self.assertEqual(len(calls),4)
        self.assertTrue(all('evil' not in url for url in calls))

    def test_arsa_timeout_not_success(self):
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['notices'],[])

    def test_catamarca_empty_no_false_ok(self):
        result=w.collect_one('aguas_catamarca',STAMP,fetcher=lambda _: '<h1>Suspensiones de Servicio en Curso</h1>')
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['notices'],[])
        self.assertTrue(result['page_read'])

    def test_catamarca_connection_error(self):
        result=w.collect_one('aguas_catamarca',STAMP,fetcher=lambda _: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'],'unverified')

    def test_aysam_modern_explicit_empty(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return '<html><h1>Cortes de servicio</h1><p>No hay cortes</p></html>'
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['coverage_horizon'],'current_listings_only')
        self.assertEqual(len(calls),1)

    def test_aysam_modern_failure_then_legacy(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if 'index.html' not in url:raise ConnectionError()
            return '<table><tr><td>Centro de ciudad y alrededores</td><td>Capital</td><td>Programado</td><td>13-11-2026</td><td>09:00</td><td>13-11-2026</td><td>12:00</td></tr></table>'
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(len(calls),2)
        self.assertEqual(result['source_attempts'][0]['error_type'],'ConnectionError')

    def test_absa_patagonian_locality_precision(self):
        html='''<h1>Patagones: baja presión en la red de agua</h1>10-11-2026
        <p>Se están registrando episodios de baja presión y falta de agua en la zona alta de Carmen de Patagones, especialmente Barrio Bicentenario, 99 Viviendas y Dolores.</p>'''
        notes,_=w._absa_article(html,'https://www.aguasbonaerenses.com.ar/noticias/5105',NOW)
        self.assertEqual(notes[0]['locality_hint'],'Carmen de Patagones')

    def test_clean_excerpt_at_word_boundary(self):
        v=w.excerpt('Palabra larga repetida ' * 100,120)
        self.assertLessEqual(len(v),120)
        self.assertTrue(v.endswith('…'))
        self.assertTrue(v[:-1].endswith('repetida'))

    def test_all_7_sources_keep_disabled(self):
        result=w.collect_water(STAMP,fetcher=lambda _: '<h1>Sin avisos</h1>')
        self.assertGreaterEqual(len(result['sources']),7)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertEqual(result['notices'],[])

if __name__=='__main__': unittest.main()

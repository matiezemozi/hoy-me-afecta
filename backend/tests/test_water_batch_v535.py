"""v5.35 strict scheduled times, no invented end time or live alerts."""
from __future__ import annotations
import sys, unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
from test_water_batch_v533 import STAMP, NOW, BARILOCHE, BELISLE, CIPOLLETTI

BASE_URL='https://aguasrionegrinas.com/bariloche-arsa-ejecutara-trabajos-para-fortalecer-la-red-de-agua-potable-en-el-sector-de-riberas-del-nireco/'

# This excerpt mirrors the public notice's structure: date in one paragraph,
# work times in the next. The endpoint is approximate, not a guaranteed end.
BARILOCHE_TIMED=BARILOCHE.replace(
    '<p>Por las tareas, se podrá registrar baja presión de agua potable',
    '<p>Los trabajos comenzarán a las 8 y se extenderán hasta las 18 horas, aproximadamente.</p>'
    '<p>Por las tareas, se podrá registrar baja presión de agua potable')

class WaterV535Tests(unittest.TestCase):
    def test_bariloche_planned_start_detected_across_paragraphs(self):
        notes,_=w._arsa_article(BARILOCHE_TIMED,BASE_URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['scheduled_start'],'2026-11-12T08:00-03:00')

    def test_bariloche_approximate_end_is_not_exact_end(self):
        notes,_=w._arsa_article(BARILOCHE_TIMED,BASE_URL,NOW)
        n=notes[0]
        self.assertIsNone(n['scheduled_end'])
        self.assertEqual(n['scheduled_end_estimate'],'2026-11-12T18:00-03:00')
        self.assertEqual(n['time_precision'],'start_known_end_estimated')
        self.assertFalse(n['notification_allowed'])

    def test_exact_end_stays_exact(self):
        sample=BARILOCHE.replace(
            '<p>Por las tareas,',
            '<p>Los trabajos comenzarán a las 8 y finalizarán a las 12.</p><p>Por las tareas,')
        n=w._arsa_article(sample,BASE_URL,NOW)[0][0]
        self.assertEqual(n['scheduled_start'],'2026-11-12T08:00-03:00')
        self.assertEqual(n['scheduled_end'],'2026-11-12T12:00-03:00')
        self.assertEqual(n['time_precision'],'start_and_end_published')
        self.assertNotIn('scheduled_end_estimate',n)

    def test_approximate_before_end_hour_recognized(self):
        sample=BARILOCHE.replace(
            '<p>Por las tareas,',
            '<p>Los trabajos comenzarán a las 8 y se extenderán hasta aproximadamente las 18 horas.</p><p>Por las tareas,')
        n=w._arsa_article(sample,BASE_URL,NOW)[0][0]
        self.assertEqual(n['scheduled_end_estimate'],'2026-11-12T18:00-03:00')
        self.assertIsNone(n['scheduled_end'])

    def test_unpublished_hour_not_invented(self):
        n=w._arsa_article(BARILOCHE,BASE_URL,NOW)[0][0]
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n)
        self.assertEqual(n['time_precision'],'date_only')

    def test_until_the_early_morning_remains_unknown(self):
        n=w._arsa_article(BELISLE,'https://aguasrionegrinas.com/uno/',NOW)[0][0]
        self.assertEqual(n['scheduled_start'],'2026-11-11T21:00-03:00')
        self.assertIsNone(n['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n)

    def test_work_already_started_stays_bulletin(self):
        n=w._arsa_article(CIPOLLETTI,'https://aguasrionegrinas.com/dos/',NOW)[0][0]
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertNotIn('scheduled_end_estimate',n)

    def test_time_from_other_dated_work_not_borrowed(self):
        sample=BARILOCHE.replace(
            '<p>Por las tareas,',
            '<p>El viernes 13 de noviembre comenzarán a las 9 y finalizarán a las 14 otros trabajos.</p><p>Por las tareas,')
        n=w._arsa_article(sample,BASE_URL,NOW)[0][0]
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])

    def test_invalid_start_hour_rejected(self):
        sample=BARILOCHE.replace('<p>Por las tareas,',
            '<p>Los trabajos comenzarán a las 25 y finalizarán a las 18.</p><p>Por las tareas,')
        n=w._arsa_article(sample,BASE_URL,NOW)[0][0]
        self.assertIsNone(n['scheduled_start'])

    def test_end_before_start_not_assumed_next_day(self):
        sample=BARILOCHE.replace('<p>Por las tareas,',
            '<p>Los trabajos comenzarán a las 13 y finalizarán a las 8.</p><p>Por las tareas,')
        n=w._arsa_article(sample,BASE_URL,NOW)[0][0]
        self.assertEqual(n['scheduled_start'],'2026-11-12T13:00-03:00')
        self.assertIsNone(n['scheduled_end'])

    def test_publication_from_future_not_accepted(self):
        sample=BARILOCHE_TIMED.replace('11 noviembre, 2026','21 noviembre, 2026')
        notes,_=w._arsa_article(sample,BASE_URL,NOW)
        self.assertEqual(notes,[])

    def test_aysam_successful_fallback_is_proper_source_url(self):
        legacy='https://www.aysam.com.ar/cortes/index.html'
        def fetch(url):
            if url!=legacy:raise ConnectionError('alternative unavailable')
            return '<html><body><h2>Servicio de agua</h2>No hay cortes</body></html>'
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['source_url'],legacy)
        self.assertEqual(result['source_attempts'][1]['result'],'explicit_no_listed_cuts')

    def test_aysam_legacy_without_records_stays_unverified(self):
        legacy='https://www.aysam.com.ar/cortes/index.html'
        def fetch(url):
            if url!=legacy:raise ConnectionError('alternative unavailable')
            return '<html><body><h2>Listado público</h2></body></html>'
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['source_url'],legacy)

    def test_all_water_alerts_stay_disabled(self):
        result=w.collect_water(STAMP,fetcher=lambda _: '<p>Sin publicaciones</p>')
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(not notice.get('notification_allowed',False) for notice in result['notices']))

if __name__=='__main__':unittest.main()

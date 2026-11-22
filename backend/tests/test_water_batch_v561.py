"""v5.61: Bariloche publication-only clock metadata; day is never guessed."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

ARSA_URL = 'https://aguasrionegrinas.com/bariloche-arsa-realizara-trabajos-para-recuperar-el-servicio-de-agua-potable/'
NOW = '2026-11-20T21:42:28Z'
WORK = ('Aguas Rionegrinas informa que personal del servicio local inició '
        'trabajos de reparación sobre una cañería en la intersección de '
        'las calles Francia y Pioneros en la localidad de Bariloche.')
IMPACT = ('Por este motivo, desde las 12 y hasta aproximadamente las 19, '
          'podrá registrarse baja presión y falta de suministro de agua potable '
          'en los barrios Las Margaritas, Jardín Botánico, Altos del Jardín Botánico y Belgrano.')


def article(*paras, day='20 de noviembre de 2026'):
    return ('<html><h1>Bariloche: ARSA realizará trabajos para recuperar el servicio de agua potable</h1>'
            '<span>'+day+'</span>'+''.join('<p>'+p+'</p>' for p in paras)+'</html>')


class ArsaReportedHoursV561(unittest.TestCase):
    def test_actual_november_twenty_release_preserves_only_local_clocks(self):
        notices, published = w._arsa_article(article(WORK, IMPACT),ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(published,date(2026,11,20))
        self.assertEqual(len(notices),1)
        n=notices[0]
        self.assertEqual(n['reported_start_local_time'],'12:00')
        self.assertEqual(n['reported_end_local_time_estimate'],'19:00')
        self.assertEqual(n['time_precision'],'reported_hours_day_unverified_not_live')
        self.assertNotIn('scheduled_date',n)
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])

    def test_exact_end_is_not_marked_estimate(self):
        p=IMPACT.replace('aproximadamente ','')
        r=w._arsa_reported_hours_without_confirmed_day([WORK,p])
        self.assertEqual(r['reported_end_local_time'],'19:00')
        self.assertNotIn('reported_end_local_time_estimate',r)

    def test_explicit_minutes_retained(self):
        p=IMPACT.replace('las 12 y hasta aproximadamente las 19',
                         'las 12:15 y hasta aproximadamente las 19:30')
        r=w._arsa_reported_hours_without_confirmed_day([WORK,p])
        self.assertEqual(r['reported_start_local_time'],'12:15')
        self.assertEqual(r['reported_end_local_time_estimate'],'19:30')

    def test_office_hours_ignored(self):
        office=('La oficina informa que en horario de atención al público, '
                'desde las 12 y hasta aproximadamente las 19, podrá registrarse '
                'baja presión en el abastecimiento de agua potable.')
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([WORK,office]))

    def test_no_explicit_impact_means_no_window(self):
        nonimpact=('Por este motivo, desde las 12 y hasta las 19, '
                   'se desarrollará una actividad institucional en el centro.')
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([WORK,nonimpact]))

    def test_not_from_unrelated_previous_paragraph(self):
        nonwater=('La Municipalidad anuncia trabajos de reacondicionamiento de la plaza principal.')
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([nonwater,IMPACT]))

    def test_invalid_or_reversed_hours_rejected(self):
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([
            WORK,IMPACT.replace('las 12 y hasta aproximadamente las 19',
                                'las 19 y hasta aproximadamente las 12')]))
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([
            WORK,IMPACT.replace('las 12 y hasta aproximadamente las 19',
                                'las 24 y hasta aproximadamente las 28')]))

    def test_ambiguous_multiple_windows_rejected(self):
        two=IMPACT+(' Asimismo, desde las 9 y hasta las 10 '
                    'podrá registrarse baja presión de agua por las reparaciones.')
        self.assertIsNone(w._arsa_reported_hours_without_confirmed_day([WORK,two]))

    def test_too_old_article_stays_suppressed(self):
        notices,_=w._arsa_article(article(WORK,IMPACT,day='10 de noviembre de 2026'),
                                 ARSA_URL,w.checked_instant(NOW))
        self.assertFalse(notices)

    def test_previous_same_day_explicit_time_window_still_wins(self):
        para=('Aguas Rionegrinas informa que este viernes se realizarán tareas de limpieza '
              'en Planta Potabilizadora Pilar de Bariloche entre las 13 y las 17 horas. '
              'Durante los trabajos podría registrarse baja presión en el suministro de agua.')
        notices,_=w._arsa_article(article(para),ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(notices[0]['time_precision'],'published_same_day_work_window_not_live')
        self.assertEqual(notices[0]['scheduled_start'],'2026-11-20T13:00-03:00')
        self.assertNotIn('reported_start_local_time',notices[0])

    def test_collect_does_not_change_budget_or_notifications(self):
        self.assertGreaterEqual(len(w.SOURCES),21)
        result=w.collect_one('aguas_rionegrinas_arsa',NOW,
                             fetcher=lambda url: '<html></html>')
        self.assertEqual(result['parser_revision'],'ARSA-STARTED-WORK-ESTIMATES-v5.70')
        self.assertEqual(result['max_article_requests_per_run'],2)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['notices'])

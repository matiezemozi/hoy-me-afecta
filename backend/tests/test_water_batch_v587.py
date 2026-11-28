"""v5.87: precise two-day Comallo water-impact windows, no live-state inference."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

COMALLO_URL = ('https://aguasrionegrinas.com/comallo-maniobras-en-la-red-'
               'hoy-y-el-viernes-por-tareas-para-mejorar-el-servicio/')
TITLE = 'Comallo: maniobras en la red hoy y el viernes por tareas para mejorar el servicio'
WORK = ('En el marco de las obras que se están realizando para mejorar el servicio '
        'y aumentar el caudal de agua producido en Comallo, hoy se realizarán '
        'maniobras en la red de distribución. Por este motivo, hoy de 13:00 a 18:00 '
        'y el viernes de 00:00 a 07:00 horas se registrará baja presión en el servicio. '
        'Es posible que algunos sectores experimenten faltante del recurso durante esos horarios.')
NOW = w.checked_instant('2026-11-27T03:04:32Z')

def comallo_html(work=WORK, published='26 de noviembre de 2026'):
    return f'<html><h1>{TITLE}</h1><span>{published}</span><p>{work}</p></html>'

class V587TwoDayImpactWindows(unittest.TestCase):
    def parse(self, work=WORK, now=NOW):
        notices,day=w._arsa_article(comallo_html(work),COMALLO_URL,now)
        self.assertEqual(day,date(2026,11,26))
        self.assertEqual(len(notices),1)
        return notices[0]

    def test_actual_comallo_two_distinct_windows(self):
        n=self.parse()
        self.assertEqual(n['reported_water_impact_windows'],[
            {'start':'2026-11-26T13:00-03:00','end':'2026-11-26T18:00-03:00',
             'impact':'reported_possible_water_low_pressure_not_live'},
            {'start':'2026-11-27T00:00-03:00','end':'2026-11-27T07:00-03:00',
             'impact':'reported_possible_water_low_pressure_not_live'}])
        self.assertEqual(n['time_precision'],'two_published_water_impact_windows_not_live')

    def test_no_assertion_of_active_cut_or_water_recovery(self):
        n=self.parse()
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n)
        self.assertFalse(n['notification_allowed'])

    def test_retained_after_both_windows_elapsed_not_reclassified_live(self):
        n=self.parse(now=w.checked_instant('2026-11-27T17:00:00Z'))
        self.assertEqual(n['reported_water_impact_windows'][1]['end'],
                         '2026-11-27T07:00-03:00')
        self.assertEqual(n['status'],'publication_only_not_live')

    def test_second_weekday_must_follow_publication_day(self):
        self.assertIsNone(w._arsa_reported_two_day_water_windows(
            [WORK.replace('viernes','sábado')],date(2026,11,26)))
        self.assertIsNone(w._arsa_reported_two_day_water_windows(
            [WORK],date(2026,11,25)))

    def test_publication_midnight_month_and_year_rollover(self):
        d=date(2026,12,31)  # Thursday -> Friday 1 January 2027.
        n=w._arsa_reported_two_day_water_windows([WORK],d)
        self.assertEqual(n['reported_water_impact_windows'][0]['start'],
                         '2026-12-31T13:00-03:00')
        self.assertEqual(n['reported_water_impact_windows'][1]['end'],
                         '2027-01-01T07:00-03:00')

    def test_no_guessing_without_today_publication_anchor(self):
        self.assertIsNone(w._arsa_reported_two_day_water_windows(
            [WORK.replace('hoy de 13:00','el jueves de 13:00')],date(2026,11,26)))

    def test_no_borrowing_hours_from_unrelated_paragraph(self):
        a=WORK.split('Por este motivo,')[0]
        b='Por este motivo, '+WORK.split('Por este motivo,')[1]
        self.assertIsNone(w._arsa_reported_two_day_water_windows([a,b],date(2026,11,26)))

    def test_no_office_schedule_promoted(self):
        p=WORK.replace('Por este motivo, hoy de','La oficina en horario de atención al público: hoy de')
        self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_no_nonwater_works_promoted(self):
        p=WORK.replace('en la red de distribución','sobre el pavimento').replace('agua producido','alumbrado existente')
        self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_no_neutral_announcement_without_impact(self):
        p=WORK.replace('se registrará baja presión en el servicio',
                       'se completará una capacitación del personal')
        self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_no_negated_water_impact(self):
        p=WORK.replace('se registrará baja presión en el servicio',
                       'no se registrará baja presión en el servicio')
        self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_invalid_clock_values_and_reversed_interval(self):
        for p in (WORK.replace('13:00 a 18:00','25:00 a 18:00'),
                  WORK.replace('13:00 a 18:00','19:00 a 18:00'),
                  WORK.replace('00:00 a 07:00','00:60 a 07:00'),
                  WORK.replace('00:00 a 07:00','07:00 a 07:00')):
            with self.subTest(p=p[-120:]):
                self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_duplicate_windows_do_not_create_ambiguous_metadata(self):
        self.assertIsNone(w._arsa_reported_two_day_water_windows([WORK,WORK],date(2026,11,26)))

    def test_conflicting_second_window_not_selected(self):
        p=WORK+' Por este motivo, hoy de 13:00 a 18:00 y el viernes de 01:00 a 06:00 horas se registrará baja presión en el servicio.'
        self.assertIsNone(w._arsa_reported_two_day_water_windows([p],date(2026,11,26)))

    def test_article_without_independent_date_is_not_accepted(self):
        n,_=w._arsa_article(comallo_html(published=''),COMALLO_URL,NOW)
        self.assertEqual(n,[])

    def test_bad_article_publication_date_not_reused_for_windows(self):
        n,day=w._arsa_article(comallo_html(published='19 de noviembre de 2026'),COMALLO_URL,NOW)
        self.assertEqual(n,[])
        self.assertEqual(day,date(2026,11,19))

    def test_notice_id_remains_stable_after_adding_metadata(self):
        note=self.parse()
        orig=w.mk_notice('Aguas Rionegrinas','Río Negro','Comallo',COMALLO_URL,
                         'water_service_bulletin','publication_only_not_live','texto',
                         published_on='2026-11-26',scheduled_start=None,scheduled_end=None)
        self.assertEqual(note['id'],orig['id'])

    def test_schema_and_metadata_revision_compatibility(self):
        r=w.collect_one('aguas_rionegrinas_arsa','2026-11-27T03:04:32Z',
                        lambda u:'<html></html>')
        self.assertEqual(r['parser_revision'],'ARSA-STARTED-WORK-ESTIMATES-v5.70')
        self.assertEqual(r['time_metadata_revision'],'ARSA-ELECTRIC-WINDOW-v5.86')
        self.assertEqual(r['multi_window_metadata_revision'],
                         'ARSA-TWO-DAY-IMPACT-WINDOWS-v5.87')

    def test_other_collectors_and_pilot_flags_unchanged(self):
        report=w.collect_water('2026-11-27T03:04:32Z',fetcher=lambda u:'<html></html>')
        self.assertEqual(len(report['sources']),30)
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertTrue(all(not s['notifications_enabled'] for s in report['sources'].values()))
        self.assertTrue(all(not n.get('notification_allowed') for n in report['notices']))


GENERAL_BELGRANO_URL='https://www.aguasbonaerenses.com.ar/noticias/5133'
GENERAL_BELGRANO=('Esta mañana, como consecuencia de un corte en el suministro de energía '
                  'eléctrica sobre perforaciones, se registra baja presión en toda la localidad '
                  'de General Belgrano hasta aproximadamente las 13:30. Por esta razón, se '
                  'solicita a las personas usuarias cuidar las reservas domiciliarias hasta '
                  'que se restablezca el suministro.')

class V587ABSAEstimatedPressureEnd(unittest.TestCase):
    def test_actual_general_belgrano_published_estimate_not_restoration(self):
        html=('<h1>General Belgrano: Baja presión en el servicio de agua</h1>'
              '<div>26-11-2026</div><p>'+GENERAL_BELGRANO+'</p>')
        notes,published=w._absa_article(html,GENERAL_BELGRANO_URL,NOW)
        self.assertEqual(published,date(2026,11,26))
        self.assertEqual(len(notes),1)
        n=notes[0]
        self.assertEqual(n['reported_low_pressure_end_estimate'],'2026-11-26T13:30-03:00')
        self.assertTrue(n['reported_estimate_does_not_confirm_water_recovery'])
        self.assertIsNone(n['scheduled_end'])
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])

    def test_estimate_remains_historical_on_next_day(self):
        r=w._absa_same_day_pressure_end_estimate([GENERAL_BELGRANO],date(2026,11,26))
        self.assertEqual(r['reported_low_pressure_end_estimate'],'2026-11-26T13:30-03:00')
        self.assertNotIn('scheduled_end',r)

    def test_no_unverified_day_or_approximation(self):
        for p in (GENERAL_BELGRANO.replace('Esta mañana','En la localidad'),
                  GENERAL_BELGRANO.replace('hasta aproximadamente las','hasta las'),
                  GENERAL_BELGRANO.replace('se registra baja presión','se realizan tareas')):
            with self.subTest(p=p):
                self.assertEqual(w._absa_same_day_pressure_end_estimate([p],date(2026,11,26)),{})

    def test_office_schedule_and_negated_low_pressure_rejected(self):
        self.assertEqual(w._absa_same_day_pressure_end_estimate(
            ['En el horario de atención de la oficina, '+GENERAL_BELGRANO],date(2026,11,26)),{})
        self.assertEqual(w._absa_same_day_pressure_end_estimate(
            [GENERAL_BELGRANO.replace('se registra baja presión','no se registra baja presión')],
            date(2026,11,26)),{})

    def test_no_time_from_unrelated_paragraph(self):
        a=GENERAL_BELGRANO.split('hasta aproximadamente las')[0]
        b='Los teléfonos de contacto estarán disponibles hasta aproximadamente las 13:30.'
        self.assertEqual(w._absa_same_day_pressure_end_estimate([a,b],date(2026,11,26)),{})

    def test_out_of_range_clocks_rejected(self):
        for p in (GENERAL_BELGRANO.replace('13:30','24:30'),
                  GENERAL_BELGRANO.replace('13:30','13:60')):
            self.assertEqual(w._absa_same_day_pressure_end_estimate([p],date(2026,11,26)),{})

    def test_multiple_conflicting_estimates_rejected(self):
        p2=GENERAL_BELGRANO.replace('13:30','14:30')
        self.assertEqual(w._absa_same_day_pressure_end_estimate(
            [GENERAL_BELGRANO,p2],date(2026,11,26)),{})

    def test_no_impact_only_electricity(self):
        p=GENERAL_BELGRANO.replace('se registra baja presión','se interrumpe energía eléctrica')
        self.assertEqual(w._absa_same_day_pressure_end_estimate([p],date(2026,11,26)),{})

    def test_absa_old_revision_remains_and_new_metadata_visible(self):
        r=w.collect_one('absa_buenos_aires','2026-11-27T03:04:32Z',
                        lambda u:'<html></html>')
        self.assertEqual(r['parser_revision'],'ABSA-CROSSREF-TIMES-v5.60')
        self.assertEqual(r['time_metadata_revision'],'ABSA-WORK-DURATION-v5.86')
        self.assertEqual(r['pressure_metadata_revision'],
                         'ABSA-SAME-DAY-PRESSURE-ESTIMATE-v5.87')

if __name__=='__main__':
    unittest.main()

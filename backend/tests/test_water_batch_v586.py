"""v5.86: retain official energy-outage windows and estimated work duration without inventing water recovery."""
import unittest
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW=w.checked_instant('2026-11-26T01:52:38Z')
POWER=('Aguas Rionegrinas informa que este jueves 26 de noviembre, entre las 12 y las 16 horas, '
       'se verá afectado el servicio de energía eléctrica en toda la localidad de Valcheta.')
IMPACT=('Debido a que los sistemas de captación y producción de agua potable dependen del suministro '
        'eléctrico, durante ese período podrían registrarse inconvenientes, principalmente baja presión '
        'en los barrios altos. Una vez restablecida la energía, el sistema comenzará a recuperar '
        'progresivamente sus niveles habituales de funcionamiento.')
ARSA_URL='https://aguasrionegrinas.com/valcheta-este-jueves-26-se-registrara-baja-presion-de-agua-por-un-corte-programado-de-energia-electrica/'
ABSA_URL='https://www.aguasbonaerenses.com.ar/noticias/5128'
ABSA_CONTENT=('El próximo jueves 26, se realizarán trabajos de mantenimiento en la batería de pozos '
 'de la localidad cabecera del Acueducto Nueve de Julio Carlos Casares Pehuajó. '
 'Las tareas demandarán detener todas las perforaciones de esa captación a partir de las 6:00 '
 'de la mañana, por un plazo estimado de 18 horas. En consecuencia, podrá registrarse baja presión '
 'en el suministro de agua en Carlos Casares y Pehuajó.')

def arsa_html(power=POWER,impact=IMPACT,published='25 de noviembre de 2026'):
 return ('<html><h1>Valcheta: este jueves 26 se registrará baja presión de agua '
         'por un corte programado de energía eléctrica</h1>'
         f'<span>{published}</span><p>{power}</p><p>{impact}</p></html>')

def absa_html(content=ABSA_CONTENT):
 return ('<html><h1>Acueducto Nueve de Julio: Trabajos programados sobre la red de agua</h1>'
         f'<div>24-11-2026</div><p>{content}</p></html>')

class V586SourceTimeIntegrity(unittest.TestCase):
 def test_actual_arsa_valcheta_preserves_electricity_window_only(self):
  notes,day=w._arsa_article(arsa_html(),ARSA_URL,NOW)
  self.assertEqual(day,date(2026,11,25))
  self.assertEqual(len(notes),1)
  n=notes[0]
  self.assertEqual(n['reported_electricity_outage_start'],'2026-11-26T12:00-03:00')
  self.assertEqual(n['reported_electricity_outage_end'],'2026-11-26T16:00-03:00')
  self.assertTrue(n['reported_electricity_end_does_not_confirm_water_recovery'])
  self.assertEqual(n['status'],'publication_only_not_live')
  self.assertIsNone(n['scheduled_start'])
  self.assertIsNone(n['scheduled_end'])
  self.assertNotIn('scheduled_end_estimate',n)
  self.assertFalse(n['notification_allowed'])
 def test_window_metadata_persists_after_end_without_live_inference(self):
  notes,_=w._arsa_article(arsa_html(),ARSA_URL,w.checked_instant('2026-11-27T00:00:00Z'))
  self.assertEqual(notes[0]['reported_electricity_outage_end'],'2026-11-26T16:00-03:00')
  self.assertEqual(notes[0]['status'],'publication_only_not_live')
 def test_wrong_weekday_does_not_create_window(self):
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   [POWER.replace('jueves 26','viernes 26'),IMPACT],date(2026,11,25)),{})
 def test_no_power_cut_or_just_office_hours_has_no_window(self):
  p=POWER.replace('se verá afectado el servicio de energía eléctrica',
                  'no se verá afectado el servicio de energía eléctrica')
  self.assertEqual(w._arsa_reported_electricity_outage_window([p,IMPACT],date(2026,11,25)),{})
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   ['El jueves 26 de noviembre, entre las 12 y las 16 horas, la oficina atenderá al público.'],
   date(2026,11,25)),{})
 def test_bad_conflicting_and_outside_range_time_rejected(self):
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   [POWER.replace('las 12 y las 16','las 17 y las 16')],date(2026,11,25)),{})
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   [POWER.replace('las 12 y las 16','las 24 y las 26')],date(2026,11,25)),{})
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   [POWER,POWER.replace('las 12 y las 16','las 14 y las 15')],date(2026,11,25)),{})
 def test_arsa_no_water_impact_never_publishes_water_notice(self):
  nonimpact=('La empresa ofrece charlas para reducir el consumo y mejorar la eficiencia '
              'del agua potable sin inconvenientes para usuarios.')
  notes,_=w._arsa_article(arsa_html(impact=nonimpact),ARSA_URL,NOW)
  self.assertEqual(notes,[])
 def test_absa_actual_18_hours_estimates_works_not_recovery(self):
  notices,published=w._absa_article(absa_html(),ABSA_URL,NOW)
  self.assertEqual(published,date(2026,11,24))
  self.assertEqual(len(notices),1)
  n=notices[0]
  self.assertEqual(n['reported_work_duration_estimate_hours'],18)
  self.assertEqual(n['reported_work_end_estimate'],'2026-11-27T00:00-03:00')
  self.assertEqual(n['scheduled_start'],'2026-11-26T06:00-03:00')
  self.assertIsNone(n['scheduled_end'])
  self.assertNotIn('scheduled_end_estimate',n)
  self.assertFalse(n['notification_allowed'])
 def test_absa_clock_must_be_same_as_reported_start(self):
  f=w._absa_work_duration_estimate
  self.assertEqual(f(ABSA_CONTENT,(7,0),date(2026,11,26)),{})
 def test_absa_explicit_duration_not_from_free_floating_claim(self):
  f=w._absa_work_duration_estimate
  bad=ABSA_CONTENT.replace('a partir de las 6:00 de la mañana, por un plazo estimado de 18 horas',
                           'a partir de las 6:00 de la mañana. El proyecto tiene 18 horas disponibles')
  self.assertEqual(f(bad,(6,0),date(2026,11,26)),{})
 def test_absa_wrong_clocks_office_and_bad_durations(self):
  f=w._absa_work_duration_estimate
  self.assertEqual(f(ABSA_CONTENT.replace('18 horas','60 horas'),(6,0),date(2026,11,26)),{})
  self.assertEqual(f(ABSA_CONTENT.replace('18 horas','0 horas'),(6,0),date(2026,11,26)),{})
  self.assertEqual(f(ABSA_CONTENT.replace('a partir de las 6:00','a partir de las 25:00'),(25,0),date(2026,11,26)),{})
  self.assertEqual(f('La oficina realizará tareas en horario de atención al público '
                    'a partir de las 6:00, por un plazo estimado de 18 horas.',(6,0),date(2026,11,26)),{})
 def test_electricity_service_sentence_by_itself_cannot_trigger_water_notice(self):
  self.assertFalse(w._arsa_explicit_service_impact(POWER))
  self.assertFalse(w._arsa_explicit_service_impact(
   'Se interrumpira el suministro electrico de Valcheta por trabajos en instalaciones.'))
  self.assertTrue(w._arsa_explicit_service_impact(POWER+' '+IMPACT))
 def test_explicit_water_effect_in_same_electricity_sentence_is_allowed(self):
  para=('Se vera afectado el servicio de energia electrica, y por ese corte '
        'podria registrarse baja presion del agua potable en barrios altos.')
  self.assertTrue(w._arsa_explicit_service_impact(para))
 def test_work_duration_not_an_assumed_scheduled_end(self):
  data=w._absa_work_duration_estimate(ABSA_CONTENT,(6,0),date(2026,11,26))
  self.assertEqual(sorted(data),['reported_work_duration_estimate_hours',
                                 'reported_work_end_estimate'])
  self.assertNotIn('scheduled_end',data)
 def test_fresh_scpl_schedule_unchanged_before_published_end(self):
  from test_water_batch_v581 import article,URL
  n,p,verdict=w._scpl_article(article(),URL,
                         w.checked_instant('2026-11-25T19:00:00Z'),date(2026,11,24))
  self.assertEqual(verdict,'parsed')
  self.assertEqual(n['status'],'scheduled_not_confirmed')
  self.assertNotIn('published_schedule_window_elapsed',n)
 def test_elapsed_scpl_plan_becomes_history_without_claiming_restoration(self):
  from test_water_batch_v581 import article,URL
  old,p,verdict=w._scpl_article(article(),URL,
                         w.checked_instant('2026-11-26T01:52:38Z'),date(2026,11,24))
  self.assertEqual(verdict,'parsed')
  self.assertEqual(old['status'],'publication_only_not_live')
  self.assertTrue(old['published_schedule_window_elapsed'])
  self.assertEqual(old['scheduled_end'],'2026-11-25T18:00:00-03:00')
  self.assertIn('No confirma',old['message'])
  self.assertFalse(old['notification_allowed'])
 def test_scpl_stable_notice_identity_across_elapsed_boundary(self):
  from test_water_batch_v581 import article,URL
  future,_,_=w._scpl_article(article(),URL,w.checked_instant('2026-11-24T22:00:00Z'),date(2026,11,24))
  elapsed,_,_=w._scpl_article(article(),URL,w.checked_instant('2026-11-26T01:52:38Z'),date(2026,11,24))
  self.assertEqual(future['id'],elapsed['id'])
  self.assertEqual(future['kind'],elapsed['kind'])
 def test_original_source_parser_revisions_retained_and_annotations_visible(self):
  a=w.collect_one('absa_buenos_aires','2026-11-26T01:52:38Z',lambda _:'<html></html>')
  r=w.collect_one('aguas_rionegrinas_arsa','2026-11-26T01:52:38Z',lambda _:'<html></html>')
  self.assertEqual(a['parser_revision'],'ABSA-CROSSREF-TIMES-v5.60')
  self.assertEqual(a['time_metadata_revision'],'ABSA-WORK-DURATION-v5.86')
  self.assertEqual(r['parser_revision'],'ARSA-STARTED-WORK-ESTIMATES-v5.70')
  self.assertEqual(r['time_metadata_revision'],'ARSA-ELECTRIC-WINDOW-v5.86')
 def test_arsa_time_window_only_if_one_consistent_publication_day(self):
  self.assertEqual(w._arsa_reported_electricity_outage_window(
   [POWER,POWER.replace('jueves 26 de noviembre','jueves 3 de diciembre')],
   date(2026,11,25)),{})
 def test_old_mismatched_arsa_article_does_not_generate_metadata_or_notice(self):
  old=w._arsa_article(arsa_html(published='12 de noviembre de 2026'),ARSA_URL,NOW)
  self.assertFalse(old[0])
 def test_synthetic_feed_keep_existing_pilot_flags(self):
  d=w.collect_water('2026-11-26T01:52:38Z',fetcher=lambda u:'<html></html>')
  self.assertEqual(len(d['sources']),30)
  self.assertFalse(d['notifications_enabled'])
  self.assertFalse(d['android_display_enabled'])
  self.assertEqual(d['source_health']['configured_sources'],30)
  self.assertTrue(all(not s['notifications_enabled'] for s in d['sources'].values()))

if __name__=='__main__':unittest.main()

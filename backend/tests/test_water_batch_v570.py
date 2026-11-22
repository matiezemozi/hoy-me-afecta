"""v5.70: source-grounded started repair and predicted pressure recovery are not live cuts."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='aguas_rionegrinas_arsa'
URL='https://aguasrionegrinas.com/el-bolson-aguas-rionegrinas-trabaja-en-la-reparacion-de-una-caneria-este-domingo/'
TITLE='El Bolsón: Aguas Rionegrinas trabaja en la reparación de una cañería este domingo'
NOW=w.checked_instant('2026-11-22T16:37:04Z')
START=('Aguas Rionegrinas informa que personal del servicio local de El Bolsón '
       'trabaja desde las 9 de este domingo 22 de noviembre en la reparación de una '
       'cañería ubicada en la intersección de las calles Rivadavia y Ulieldin.')
IMPACT=('Debido a estas tareas, se encuentra afectada la prestación del servicio '
        'de agua potable en el barrio Centro, en el sector comprendido entre las '
        'calles Balcarce y Güemes, donde se registra baja presión y podría '
        'producirse una falta temporal de suministro.')
NORMAL=('Se prevé que a partir de las 14 hs ya esté normalizada la presión del suministro.')

def article(start=START, impact=IMPACT, normal=NORMAL, pub='22 de noviembre de 2026'):
    return ('<html><h1>'+TITLE+'</h1><span>'+pub+'</span>'+''.join(
        '<p>'+p+'</p>' for p in (start,impact,normal) if p)+'</html>')

class V570StartedWork(unittest.TestCase):
    def test_actual_bolson_is_reported_started_not_future_plan(self):
        notes,pub=w._arsa_article(article(),URL,NOW)
        self.assertEqual(pub,date(2026,11,22))
        self.assertEqual(len(notes),1)
        n=notes[0]
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertEqual(n['locality_hint'],'El Bolsón')
        self.assertEqual(n['reported_work_date'],'2026-11-22')
        self.assertEqual(n['reported_work_started_at'],'2026-11-22T09:00-03:00')
        self.assertEqual(n['reported_pressure_normalization_estimate'],'2026-11-22T14:00-03:00')
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n)
        self.assertNotIn('scheduled_date',n)
        self.assertFalse(n['notification_allowed'])
    def test_after_14_estimate_is_still_not_confirmed(self):
        n,_=w._arsa_article(article(),URL,w.checked_instant('2026-11-22T19:05:00Z'))
        self.assertEqual(n[0]['status'],'publication_only_not_live')
        self.assertEqual(n[0]['reported_pressure_normalization_estimate'],'2026-11-22T14:00-03:00')
        self.assertIn('no acredita',n[0]['message'])
    def test_no_normalization_phrase_does_not_invent_end(self):
        n,_=w._arsa_article(article(normal='ARSA continúa trabajando para reparar la red.'),URL,NOW)
        self.assertEqual(n[0]['reported_work_started_at'],'2026-11-22T09:00-03:00')
        self.assertNotIn('reported_pressure_normalization_estimate',n[0])
    def test_office_hours_are_not_pressure_estimate(self):
        paras=[START,IMPACT,'La oficina atiende al público desde las 14 hs hasta las 19 horas.']
        got=w._arsa_work_already_started(paras,date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',got)
    def test_out_of_range_hour_rejected(self):
        got=w._arsa_work_already_started([START,IMPACT,NORMAL.replace('las 14','las 27')],
                                         date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',got)
    def test_before_start_cannot_be_normalization(self):
        got=w._arsa_work_already_started([START,IMPACT,NORMAL.replace('las 14','las 8')],
                                         date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',got)
    def test_bad_weekday_does_not_transform_into_started(self):
        bad=START.replace('domingo 22','lunes 22')
        self.assertIsNone(w._arsa_work_already_started([bad,IMPACT,NORMAL],date(2026,11,22),date(2026,11,22)))
    def test_started_not_inferred_from_future_tense(self):
        future=START.replace('trabaja desde las','trabajará desde las')
        self.assertIsNone(w._arsa_work_already_started([future,IMPACT,NORMAL],date(2026,11,22),date(2026,11,22)))
    def test_no_dated_work_no_estimate(self):
        self.assertIsNone(w._arsa_work_already_started([START.replace('domingo 22','domingo'),IMPACT,NORMAL],
                                                  date(2026,11,22),date(2026,11,22)))
    def test_alternative_estimate_not_office_info(self):
        res=w._arsa_work_already_started([START,IMPACT,NORMAL.replace('las 14','las 14:30')],
                                                date(2026,11,22),date(2026,11,22))
        self.assertEqual(res['reported_pressure_normalization_estimate'],'2026-11-22T14:30-03:00')
    def test_unrelated_date_boundaries_do_not_borrow_hours(self):
        res=w._arsa_work_already_started([START,IMPACT,'El lunes 23 de noviembre se prevé que a partir de las 14 hs ya esté normalizada la presión.'],
                                         date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',res)
    def test_negative_forecast_does_not_become_estimate(self):
        bad='No se prevé que a partir de las 14 hs ya esté normalizada la presión del suministro.'
        res=w._arsa_work_already_started([START,IMPACT,bad],date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',res)
    def test_unnormalized_forecast_not_estimate(self):
        bad='Se prevé que a partir de las 14 hs no esté normalizada la presión del suministro.'
        res=w._arsa_work_already_started([START,IMPACT,bad],date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',res)
    def test_multiple_conflicting_estimates_are_not_single_prediction(self):
        res=w._arsa_work_already_started([START,IMPACT,NORMAL+' '+NORMAL.replace('las 14','las 15')],
                                         date(2026,11,22),date(2026,11,22))
        self.assertNotIn('reported_pressure_normalization_estimate',res)
    def test_no_live_flags_or_budget_regression(self):
        self.assertEqual(len(w.SOURCES),26)
        result=w.collect_one(KEY,'2026-11-22T16:37:04Z',fetcher=lambda u:'<html></html>')
        self.assertEqual(result['parser_revision'],'ARSA-STARTED-WORK-ESTIMATES-v5.70')
        self.assertEqual(result['max_article_requests_per_run'],2)
        self.assertFalse(result['rate_limited'])
        self.assertFalse(result['notifications_enabled'])
        full=w.collect_water('2026-11-22T16:37:04Z',fetcher=lambda u:'<html></html>')
        self.assertFalse(full['notifications_enabled'])
        self.assertFalse(full['android_display_enabled'])
        self.assertEqual(len(full['sources']),26)

if __name__=='__main__':unittest.main()

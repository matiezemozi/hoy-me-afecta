"""v5.74: reported start and estimate survive the next calendar day."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
URL='https://aguasrionegrinas.com/el-bolson-aguas-rionegrinas-trabaja-en-la-reparacion-de-una-caneria-este-domingo/'
TITLE='El Bolsón: Aguas Rionegrinas trabaja en la reparación de una cañería este domingo'
START=('Aguas Rionegrinas informa que personal del servicio local de El Bolsón '
       'trabaja desde las 9 de este domingo 22 de noviembre en la reparación de una '
       'cañería ubicada en la intersección de las calles Rivadavia y Ulieldin.')
IMPACT=('Debido a estas tareas, se encuentra afectada la prestación del servicio '
        'de agua potable en el barrio Centro, en el sector comprendido entre las '
        'calles Balcarce y Güemes, donde se registra baja presión y podría '
        'producirse una falta temporal de suministro.')
NORMAL='Se prevé que a partir de las 14 hs ya esté normalizada la presión del suministro.'

def article(start=START,impact=IMPACT,normal=NORMAL):
    pub='22 de noviembre de 2026'
    return ('<html><h1>'+TITLE+'</h1><span>'+pub+'</span>'+
            ''.join('<p>'+part+'</p>' for part in (start,impact,normal) if part)+'</html>')


def at(iso):
    return w.checked_instant(iso)


class StartedRepairHistoricalMetadata(unittest.TestCase):
    def test_dated_bulletin_remembers_hours_on_nov23(self):
        notes,published=w._arsa_article(article(),URL,at('2026-11-23T14:47:56Z'))
        self.assertEqual(published,date(2026,11,22))
        self.assertEqual(len(notes),1)
        n=notes[0]
        self.assertEqual(n['reported_work_started_at'],'2026-11-22T09:00-03:00')
        self.assertEqual(n['reported_pressure_normalization_estimate'],'2026-11-22T14:00-03:00')
        self.assertEqual(n['reported_work_date'],'2026-11-22')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertFalse(n['notification_allowed'])

    def test_dated_bulletin_remembers_hours_two_days_later(self):
        notes,_=w._arsa_article(article(),URL,at('2026-11-24T20:00:00Z'))
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['reported_work_started_at'],'2026-11-22T09:00-03:00')
        self.assertEqual(notes[0]['reported_pressure_normalization_estimate'],'2026-11-22T14:00-03:00')

    def test_publication_outside_horizon_not_resurrected(self):
        notes,pub=w._arsa_article(article(),URL,at('2026-11-25T20:00:00Z'))
        self.assertEqual(notes,[])
        self.assertEqual(pub,date(2026,11,22))

    def test_future_date_in_work_body_does_not_claim_started(self):
        future=('Aguas Rionegrinas informa que el lunes 23 de noviembre trabaja desde las '
                '9 de este lunes 23 de noviembre en la reparación de una cañería de agua potable.')
        notes,_=w._arsa_article(article(start=future),URL,at('2026-11-22T16:37:04Z'))
        self.assertTrue(all('reported_work_started_at' not in n for n in notes))

    def test_date_of_work_must_match_publication_for_started(self):
        other_day=START.replace('domingo 22','lunes 23')
        notes,_=w._arsa_article(article(start=other_day),URL,at('2026-11-23T14:47:56Z'))
        self.assertTrue(all('reported_work_started_at' not in n for n in notes))

    def test_missing_confirmation_keeps_restoration_unconfirmed(self):
        notes,_=w._arsa_article(article(normal='Se desconoce cuándo se normalizará la presión.'),
                                URL,at('2026-11-23T14:47:56Z'))
        self.assertEqual(len(notes),1)
        self.assertNotIn('reported_pressure_normalization_estimate',notes[0])
        self.assertIsNone(notes[0]['scheduled_end'])
        self.assertFalse(notes[0]['notification_allowed'])

    def test_live_flags_and_source_count_unchanged(self):
        report=w.collect_water('2026-11-23T14:47:56Z',lambda _: '<html></html>')
        self.assertEqual(len(report['sources']),30)
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertTrue(report['android_read_only_pilot_available'])
        self.assertTrue(all(not x['notifications_enabled'] for x in report['sources'].values()))

    def test_chaco_unreachable_stays_unverified_not_no_outage(self):
        from urllib.error import URLError
        r=w.collect_one('sameep_chaco_prensa_gobierno',
                        '2026-11-23T14:47:56Z',lambda _: (_ for _ in ()).throw(URLError('network')))
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])
        self.assertEqual(len(r['index_attempts']),2)
        self.assertIn('desconocido',r['message'])

if __name__=='__main__':unittest.main()

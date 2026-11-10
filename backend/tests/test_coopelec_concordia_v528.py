"""Deterministic checks for Concordia cooperative planned outages. No live lookup.

Live fetch from GitHub Actions is required before claiming a new source works.
"""
import unittest
from provincial_outages import collect_one, PROVIDERS

NOW = '2026-11-10T20:00:00Z'
URL = 'https://www.coopelec.com.ar/cortes-programados/'


def schedule(date='11/11/2026', hours='07:30 a 08:30 aproximadamente',
             area='Norte: Dr. Fagalde Sur: Scalabrini Ortiz Este: San Miguel Oeste: Pablo VI',
             task='Obras de ampliación en media tensión'):
    return f'''<html><body><h2>Cortes programados</h2><table>
    <thead><tr><th>Fecha</th><th>Horario</th><th>Zona afectada</th><th>Motivo del corte</th></tr></thead>
    <tbody><tr><td>{date}</td><td>{hours}</td><td>{area}</td><td>{task}</td></tr></tbody>
    </table></body></html>'''


class CoopelecV528Tests(unittest.TestCase):
    def test_provider_and_area(self):
        self.assertEqual(PROVIDERS['coopelec_concordia'],
                         ('COOPELEC', 'Entre Ríos', URL))

    def test_planned_cut_not_live_outage(self):
        out = collect_one('coopelec_concordia', NOW, fetcher=lambda _: schedule())
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['parser_revision'], 'COOPELEC-WEB-v5.28')
        self.assertEqual(out['records_checked'], 1)
        self.assertEqual(len(out['notices']), 1)
        notice = out['notices'][0]
        self.assertEqual(notice['locality_hint'], 'Concordia')
        self.assertEqual(notice['province'], 'Entre Ríos')
        self.assertEqual(notice['scheduled_start'], '2026-11-11T07:30-03:00')
        self.assertEqual(notice['scheduled_end'], '2026-11-11T08:30-03:00')
        self.assertEqual(notice['status'], 'scheduled_not_confirmed')
        self.assertEqual(notice['source_url'], URL)
        self.assertIn('Norte: Dr. Fagalde', notice['zone_detail'])
        self.assertIn('Obras de ampliación', notice['task'])

    def test_actual_published_nov6_is_stale(self):
        out = collect_one('coopelec_concordia', NOW,
                          fetcher=lambda _: schedule(date='06/11/2026'))
        self.assertEqual(out['status'], 'stale')
        self.assertEqual(out['notices'], [])
        self.assertEqual(out['latest_published_date'], '2026-11-06')

    def test_current_day_finished_not_notified(self):
        out = collect_one('coopelec_concordia', NOW,
                          fetcher=lambda _: schedule(date='10/11/2026'))
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['notices'], [])

    def test_empty_or_generic_page_not_connected(self):
        html = '<html><h1>Cortes programados</h1><p>Noticias de la Cooperativa</p></html>'
        out = collect_one('coopelec_concordia', NOW, fetcher=lambda _:html)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_wrong_or_missing_time_is_excluded(self):
        for time in ['19:00 a 06:00', '07:30 a 28:00', 'sin horario', '07:30 a 08:30 y de 12:00 a 14:00']:
            with self.subTest(time=time):
                out = collect_one('coopelec_concordia', NOW,
                                  fetcher=lambda _:schedule(hours=time))
                self.assertEqual(out['notices'], [])

    def test_missing_zone_and_cancelled(self):
        for area, task in [('Zona', 'Obras'), ('Norte: Dr Fagalde y zona central', 'Suspendido'),
                           ('Norte: Dr Fagalde y zona central', 'Corte cancelado')]:
            with self.subTest(area=area, task=task):
                out = collect_one('coopelec_concordia', NOW,
                                  fetcher=lambda _:schedule(area=area,task=task))
                self.assertEqual(out['notices'], [])

    def test_bad_calendar_date_rejected(self):
        out = collect_one('coopelec_concordia', NOW,
                          fetcher=lambda _:schedule(date='31/11/2026'))
        self.assertEqual(out['status'], 'unverified')

    def test_old_news_outside_table_is_not_accepted(self):
        out = collect_one('coopelec_concordia', NOW,
                          fetcher=lambda _: '<h2>Cortes programados</h2>'
                          '<p>Fecha 11/11/2026 Horario 7:30 a 8:30 '
                          'Zona afectada Concordia Motivo del corte de energía</p>')
        self.assertEqual(out['status'], 'unverified')

    def test_future_more_than_14_days_not_included(self):
        out = collect_one('coopelec_concordia', NOW,
                          fetcher=lambda _: schedule(date='01/12/2026'))
        self.assertEqual(out['notices'], [])
        self.assertEqual(out['status'], 'ok')

    def test_error_not_reported_as_no_cuts(self):
        def fail(_):
            raise TimeoutError('timeout')
        out = collect_one('coopelec_concordia', NOW, fetcher=fail)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

if __name__ == '__main__':
    unittest.main()

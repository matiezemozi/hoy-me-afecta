"""EDELAP's publicly shown schedule: deterministic tests only, no live fetch.

GitHub Actions must verify the real page before calling the source connected.
"""
import unittest
from provincial_outages import collect_one, _parse_edelap, _instant, PROVIDERS

WHEN = '2026-11-09T18:00:00Z'


def official_schedule():
    return '''<html><body>
      <p>Obras en tu barrio</p>
      <p>Proximamente estaremos trabajando en las redes de los siguientes lugares y horarios:</p>
      <h3>Martes 10 de Noviembre</h3>
      <ul>
        <li>de 9 a 14hs. en la zona de de 115 a 6 y de 514 a 524, Tolosa;</li>
        <li>de 8 a 15:30 hs. en la zona de de 179 de 60 a 72 y por 66 de 177 a 187, Los Hornos;</li>
        <li>de 8 a 16 hs. en la zona de 474 Y 190, y sus adyacencias, Melchor Romero;</li>
      </ul>
      <p>Los trabajos pueden implicar la interrupcion del servicio para que el personal trabaje</p>
      <p>Lunes 16 de Noviembre, de 7 a 13hs. en la zona de calle falsa, Tolosa;</p>
    </body></html>'''


class EdelapV527Tests(unittest.TestCase):
    def test_authoritative_provider(self):
        company, province, url = PROVIDERS['edelap_la_plata']
        self.assertEqual((company, province), ('EDELAP', 'Buenos Aires'))
        self.assertEqual(url, 'https://www.edelap.com.ar/obras-en-tu-barrio/')

    def test_three_realistic_works_from_official_publication(self):
        out = collect_one('edelap_la_plata', WHEN, fetcher=lambda _: official_schedule())
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['parser_revision'], 'EDELAP-WEB-v5.27')
        self.assertEqual(out['coverage_kind'], 'planned_network_work_may_interrupt_only')
        self.assertEqual(out['records_checked'], 3)
        self.assertEqual(len(out['notices']), 3)
        expected = [
            ('Los Hornos', '2026-11-10T08:00-03:00', '2026-11-10T15:30-03:00'),
            ('Melchor Romero', '2026-11-10T08:00-03:00', '2026-11-10T16:00-03:00'),
            ('Tolosa', '2026-11-10T09:00-03:00', '2026-11-10T14:00-03:00'),
        ]
        self.assertEqual([(n['locality_hint'], n['scheduled_start'], n['scheduled_end'])
                          for n in out['notices']], expected)
        for n in out['notices']:
            self.assertEqual(n['status'], 'scheduled_not_confirmed')
            self.assertEqual(n['kind'], 'planned_electricity_work')
            self.assertEqual(n['source_url'], PROVIDERS['edelap_la_plata'][2])
        self.assertIn('PUEDEN requerir', out['message'])
        self.assertNotIn('calle falsa', str(out['notices']))

    def test_wrong_weekday_never_verified(self):
        s = official_schedule().replace('Martes 10', 'Viernes 10')
        out = collect_one('edelap_la_plata', WHEN, fetcher=lambda _: s)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_generic_page_without_schedules_unverified(self):
        out = collect_one('edelap_la_plata', WHEN,
                          fetcher=lambda _: '<h2>Obras en tu barrio</h2><div>Mas novedades</div>')
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_outside_coverage_locality_is_rejected(self):
        s = official_schedule().replace('Tolosa', 'Villa Maria').replace('Los Hornos', 'Villa Maria').replace('Melchor Romero', 'Villa Maria')
        out = collect_one('edelap_la_plata', WHEN, fetcher=lambda _: s)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_invalid_hour_and_no_zone_excluded(self):
        s = official_schedule().replace('de 9 a 14hs.', 'de 19 a 14hs.')
        s = s.replace('de 8 a 15:30 hs.', 'de 8 a 31:30 hs.')
        s = s.replace('474 Y 190, y sus adyacencias, Melchor Romero', '., Melchor Romero')
        out = collect_one('edelap_la_plata', WHEN, fetcher=lambda _: s)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_no_past_works_labelled_as_current(self):
        out = collect_one('edelap_la_plata', '2026-11-11T18:00:00Z',
                          fetcher=lambda _: official_schedule())
        self.assertEqual(out['notices'], [])
        self.assertNotEqual(out['status'], 'unverified')

    def test_new_year_rollover(self):
        html = ('<h2>Obras en tu barrio</h2>'
                '<h3>Viernes 1 de Enero</h3><ul>'
                '<li>de 8 a 11hs. en la zona de calle 10 y calle 50, Tolosa;</li></ul>'
                '<p>Los trabajos pueden implicar la interrupcion del servicio</p>')
        out = collect_one('edelap_la_plata', '2026-12-31T18:00:00Z', fetcher=lambda _:html)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(len(out['notices']), 1)
        self.assertEqual(out['notices'][0]['scheduled_start'][:10], '2027-01-01')

    def test_no_false_locality_from_footer_or_year_in_page_menu(self):
        h = ('<p>Noticias: Sabado 14 de Noviembre</p>' + official_schedule())
        out = collect_one('edelap_la_plata', WHEN, fetcher=lambda _:h)
        self.assertEqual(len(out['notices']), 3)


if __name__ == '__main__':
    unittest.main()

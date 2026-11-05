"""Offline tests: two independent public schedules; no simulated live outages."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buenos_aires_work import extract_works, collect_buenos_aires
from collector import collect

EDEA = '''<html><head><script>Jueves 5 de noviembre - USUARIO PRIVADO</script></head><body>
<nav>Jueves 5 de noviembre MAR DEL PLATA</nav>
<section><h2>Obras en tu barrio</h2><p>Todos los días trabajamos para darte más energía.</p>
<p><b>Jueves 5 de noviembre</b></p>
<ul><li><strong>MAR DEL PLATA</strong></li></ul>
<p>– de Fray Luis Beltran a Zeballos y de Pujia a Bautista en el horario de 10:00 hs a 11:00 hs.</p>
<p>– de Ituzaingo a Rio Negro y de Chaco a Francia en el horario de 08:00 hs a 09:30 hs.</p>
<p><b>SANTA CLARA DEL MAR</b></p><p>– de Av. San Martin a Machado en el horario de 08:30 hs a 10:30 hs.</p>
<p>Los trabajos pueden implicar la interrupción del servicio para que el personal trabaje.</p>
<p>– fuera de sección, de 04:00 a 05:00 hs.</p></section></body></html>'''
EDEN = '''<html><body><h1>Obras en tu barrio</h1><p>Próximamente estaremos trabajando...</p>
<p>Miércoles 4 de Noviembre</p>
<p>GRAL. ARENALES</p><p>– Barrio Estación Arenales, de 12.00 a 15.00 hs.</p>
<p>CAPITAN SARMIENTO</p><p>– Barrio La Loma e Independiente, de 8.00 a 12.00 hs.</p>
<p>Los trabajos pueden implicar la interrupción del servicio.</p></body></html>'''
TIME_NOV4 = '2026-11-04T18:00:00Z'  # Nov 4 at 15:00 Argentina
TIME_NOV4_NIGHT = '2026-11-05T00:00:00Z'  # Nov 4 at 21:00 Argentina


class BuenosAiresWorkTests(unittest.TestCase):
    def test_edea_public_works_dated_and_located(self):
        notices, dates, areas = extract_works(EDEA, 'edea_buenos_aires', TIME_NOV4)
        self.assertEqual((dates, areas), (1, 2))
        self.assertEqual(len(notices), 3)
        self.assertEqual(notices[0]['locality_hint'], 'MAR DEL PLATA')
        self.assertEqual(notices[0]['scheduled_start'], '2026-11-05T08:00-03:00')
        self.assertEqual(notices[0]['scheduled_end'], '2026-11-05T09:30-03:00')
        self.assertTrue(all(n['status'] == 'scheduled_not_confirmed' for n in notices))
        self.assertTrue(all(n['province'] == 'Buenos Aires' for n in notices))
        self.assertTrue(all(n['company'] == 'EDEA' for n in notices))

    def test_eden_today_only_unexpired(self):
        notices, dates, areas = extract_works(EDEN, 'eden_buenos_aires', TIME_NOV4)
        self.assertEqual((dates, areas), (1, 2))
        self.assertEqual(len(notices), 0)  # end time is exactly now, not upcoming

    def test_eden_today_before_start(self):
        notices, _, _ = extract_works(EDEN, 'eden_buenos_aires', '2026-11-04T12:00:00Z')
        self.assertEqual(len(notices), 2)
        self.assertEqual(notices[0]['locality_hint'], 'CAPITAN SARMIENTO')
        self.assertEqual(notices[0]['scheduled_start'], '2026-11-04T08:00-03:00')

    def test_elapsed_today_stale(self):
        r = collect_buenos_aires(TIME_NOV4_NIGHT, fetch=lambda url: EDEN)
        self.assertEqual(r['eden_buenos_aires']['status'], 'stale')
        self.assertEqual(r['eden_buenos_aires']['notices'], [])
        self.assertIn('no significa servicio normal', r['eden_buenos_aires']['message'].lower())

    def test_all_future_works_ok(self):
        r = collect_buenos_aires(TIME_NOV4, fetch=lambda url: EDEA)
        self.assertEqual(r['edea_buenos_aires']['status'], 'ok')
        self.assertEqual(len(r['edea_buenos_aires']['notices']), 3)
        self.assertEqual(r['eden_buenos_aires']['status'], 'ok')

    def test_empty_calendar_unverified(self):
        r = collect_buenos_aires(TIME_NOV4, fetch=lambda url: '<p>Sin información</p>')
        self.assertEqual(r['edea_buenos_aires']['status'], 'unverified')

    def test_network_failure_is_local(self):
        def fetch(url):
            if 'edensa' in url:
                raise TimeoutError('offline')
            return EDEA
        r = collect_buenos_aires(TIME_NOV4, fetch=fetch)
        self.assertEqual(r['eden_buenos_aires']['status'], 'unverified')
        self.assertEqual(r['edea_buenos_aires']['status'], 'ok')

    def test_cancelled_or_reprogrammed_not_published(self):
        page = EDEA.replace('de Fray Luis Beltran a Zeballos', 'Suspendido: de Fray Luis Beltran a Zeballos')
        page = page.replace('de Ituzaingo a Rio Negro', 'Reprogramado: de Ituzaingo a Rio Negro')
        notices, _, _ = extract_works(page, 'edea_buenos_aires', TIME_NOV4)
        self.assertEqual(len(notices), 1)

    def test_spurious_time_range_without_locality_not_published(self):
        page = EDEA.replace('MAR DEL PLATA', 'Mar del Plata').replace('SANTA CLARA DEL MAR', 'Santa Clara del Mar')
        notices, _, areas = extract_works(page, 'edea_buenos_aires', TIME_NOV4)
        self.assertEqual((notices, areas), ([], 0))

    def test_invalid_hours_not_published(self):
        page = EDEA.replace('10:00 hs a 11:00 hs', '11:00 hs a 10:00 hs').replace(
            '08:00 hs a 09:30 hs', '08:00 hs a 23:30 hs')
        notices, _, _ = extract_works(page, 'edea_buenos_aires', TIME_NOV4)
        self.assertEqual(len(notices), 1)

    def test_no_date_no_works(self):
        page = EDEA.replace('Jueves 5 de noviembre', 'Un día futuro')
        self.assertEqual(extract_works(page, 'edea_buenos_aires', TIME_NOV4)[0], [])

    def test_year_rollover(self):
        page = EDEA.replace('Jueves 5 de noviembre', 'Viernes 1 de enero')
        notices, _, _ = extract_works(page, 'edea_buenos_aires', '2026-12-31T14:00:00Z')
        self.assertEqual(len(notices), 3)
        self.assertEqual(notices[0]['scheduled_start'], '2027-01-01T08:00-03:00')

    def test_distant_dates_rejected(self):
        page = EDEA.replace('Jueves 5 de noviembre', 'Viernes 25 de diciembre')
        self.assertEqual(extract_works(page, 'edea_buenos_aires', TIME_NOV4)[0], [])

    def test_html_script_forgery_ignored(self):
        page = '<html><body><script>Obras en tu barrio Jueves 5 de noviembre MAR DEL PLATA de 10:00 hs a 11:00 hs</script><p>Sin datos</p></body></html>'
        self.assertEqual(extract_works(page, 'edea_buenos_aires', TIME_NOV4)[0], [])

    def test_unrecognized_key_throws(self):
        with self.assertRaises(ValueError):
            extract_works(EDEA, '../trick', TIME_NOV4)

    def test_missing_timezone_throws(self):
        with self.assertRaises(ValueError):
            extract_works(EDEA, 'edea_buenos_aires', '2026-11-04T15:00:00')

    def test_oversize_rejected(self):
        with self.assertRaises(ValueError):
            extract_works('x' * 700_000, 'edea_buenos_aires', TIME_NOV4)

    def test_collector_uses_separate_works_not_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            with patch('collector.fetch_js', return_value={'cortes': []}):
                result = collect(d / 'feed.json', d / 'none.json', d / 'none2.json',
                                 fetch_buenos_aires_work=lambda _: collect_buenos_aires(TIME_NOV4, fetch=lambda url: EDEA))
            self.assertEqual(result, None)
            payload = json.loads((d / 'feed.json').read_text(encoding='utf-8'))
            self.assertEqual(payload['alerts'], [])
            self.assertEqual(payload['notification_events']['events'], [])
            self.assertEqual(payload['buenos_aires_work']['edea_buenos_aires']['status'], 'ok')
            self.assertEqual(payload['coverage_argentina']['national_electricity_coverage'], False)


if __name__ == '__main__':
    unittest.main()

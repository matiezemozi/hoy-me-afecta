"""Deterministic parser tests from the published HTML text of two official cooperatives.

No real-time or API access is implied by these tests. GitHub Actions must
confirm whether the public sites remain reachable with the expected format.
"""
import unittest
from provincial_outages import collect_one, _instant, _parse_copelco, _parse_cpe, PROVIDERS

WHEN = '2026-11-09T16:00:00Z'  # 13:00 local time; 10 Nov is tomorrow.


def copelco_html():
    return '''<html><body><h2>Cortes programados</h2><p>Interrupciones previstas
        por tareas de mantenimiento y poda preventiva.</p>
        <div>10 NOV</div><div>Martes 08:00 a 10:00 hs SET 90</div>
        <p>PLAZA HUINCUL - • Asociados ubicados en el Acceso a Ex Almacenes de YPF.</p>
        <p>Usuarios singulares: Trans Tech - Lava Autos</p>
        <div>11 NOV</div><div>Miércoles 07:00 a 12:00 hs SET 82-83-84-92-126</div>
        <p>PLAZA HUINCUL - • B° Norte, desde Acceso a Filli Dei hasta Abel Tapia.
        B° Central, zona encuadrada por las calles Homero Manzi y Pedro Rotter.</p>
        <p>Usuarios singulares: Cablevision - Sanatorio</p>
        <p>Los horarios son estimados y pueden modificarse</p>
        <h2>Nuestros servicios</h2><p>31 DIC Miercoles 12:00 a 13:00 hs</p>
        </body></html>'''


def cpe_html(date_heading='martes 10 de noviembre de 2026', body_date='martes 10 de noviembre',
             incl_archive=True):
    archive = '''<h2>Cortes programados pasados</h2><p>viernes 6 de noviembre de 2026
    CORTE PROGRAMADO desde las 8:00 hasta las 10:00 zona comprendida por Plaza San Martin.
    </p>''' if incl_archive else ''
    return '''<h1>Estado de servicios</h1><h2>Activos</h2><p>No hay avisos activos en este momento.</p>
    <h2>Cortes programados vigentes</h2><h4>''' + date_heading + '''</h4>
    <h3>Este martes en barrio Aeropuerto</h3><b>CORTE PROGRAMADO</b>
    <p>Este ''' + body_date + ''', desde las 8:00 hasta las 10:30 horas, se producirá
    un corte en el suministro de energía eléctrica en la zona comprendida por la avenida Spinetto,
    la avenida Santiago Marzo Este, Castro, Torres, Viniegra y Convención Provincialista,
    del Barrio Aeropuerto. Personal de la CPE remodelará la subestación transformadora.</p>
    ''' + archive


class CooperativeTests(unittest.TestCase):
    def test_expected_source_urls_company_and_schema(self):
        self.assertEqual(PROVIDERS['copelco_neuquen'][0], 'COPELCO')
        self.assertEqual(PROVIDERS['cpe_la_pampa'][1], 'La Pampa')
        self.assertTrue(PROVIDERS['copelco_neuquen'][2].startswith('https://www.copelnet.com.ar/'))

    def test_copelco_two_future_posts(self):
        out = collect_one('copelco_neuquen', WHEN, fetcher=lambda _:copelco_html())
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['parser_revision'], 'COPELCO-WEB-v5.26')
        self.assertEqual(len(out['notices']), 2)
        self.assertEqual(out['notices'][0]['scheduled_start'], '2026-11-10T08:00-03:00')
        self.assertEqual(out['notices'][1]['scheduled_end'], '2026-11-11T12:00-03:00')
        self.assertEqual(out['notices'][0]['locality_hint'], 'PLAZA HUINCUL')
        self.assertEqual(out['notices'][0]['province'], 'Neuquén')
        self.assertNotIn('Trans Tech', out['notices'][0]['zone_detail'])
        self.assertNotIn('Cablevision', out['notices'][1]['zone_detail'])
        self.assertEqual(out['notices'][0]['status'], 'scheduled_not_confirmed')
        self.assertEqual(out['notices'][0]['kind'], 'planned_electricity_work')

    def test_copelco_wrong_weekday_is_not_published(self):
        html = copelco_html().replace('Martes 08:00', 'Viernes 08:00')
        notices, count, newest = _parse_copelco(html, _instant(WHEN))
        self.assertEqual(len(notices), 1)
        self.assertEqual(count, 1)

    def test_copelco_impossible_clock(self):
        html = copelco_html().replace('08:00 a 10:00', '10:00 a 08:00')
        out = collect_one('copelco_neuquen', WHEN, fetcher=lambda _:html)
        self.assertEqual(len(out['notices']), 1)

    def test_copelco_past_window_not_current_outage(self):
        out = collect_one('copelco_neuquen', '2026-11-11T18:00:00Z',
                          fetcher=lambda _:copelco_html())
        self.assertEqual(out['notices'], [])
        self.assertNotIn('corte en curso', out['message'])

    def test_copelco_incomplete_or_missing_page_unverified(self):
        out = collect_one('copelco_neuquen', WHEN,
                          fetcher=lambda _: '<h2>Cortes programados</h2><p>Pronto novedades</p>')
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])

    def test_cpe_valid_dated_corte(self):
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _:cpe_html())
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['parser_revision'], 'CPE-WEB-v5.26')
        self.assertEqual(len(out['notices']), 1)
        n=out['notices'][0]
        self.assertEqual(n['scheduled_start'], '2026-11-10T08:00-03:00')
        self.assertEqual(n['scheduled_end'], '2026-11-10T10:30-03:00')
        self.assertEqual(n['locality_hint'], 'SANTA ROSA')
        self.assertEqual(n['province'], 'La Pampa')
        self.assertIn('Spinetto', n['zone_detail'])
        self.assertNotIn('Personal de la CPE', n['zone_detail'])
        self.assertEqual(n['source_url'], PROVIDERS['cpe_la_pampa'][2])

    def test_cpe_stale_headings_are_not_current(self):
        html = cpe_html('jueves 29 de octubre de 2026', 'jueves 29 de octubre')
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _:html)
        self.assertEqual(out['status'], 'stale')
        self.assertEqual(out['notices'], [])

    def test_cpe_falsified_weekday_skipped(self):
        html = cpe_html('lunes 10 de noviembre de 2026')
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _:html)
        self.assertEqual(out['status'], 'unverified')

    def test_cpe_explicit_no_programmed_but_not_normal_supply(self):
        html = ('<h2>Estado de servicios</h2><h2>Cortes programados vigentes</h2>'
                '<p>No hay cortes programados vigentes.</p>'
                '<h2>Cortes programados pasados</h2><p>06/11/2026</p>')
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _:html)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['notices'], [])
        self.assertIn('NO confirma servicio normal', out['message'])

    def test_cpe_empty_shell_unverified(self):
        out = collect_one('cpe_la_pampa', WHEN,
                          fetcher=lambda _:'<h2>Cortes programados vigentes</h2>')
        self.assertEqual(out['status'], 'unverified')

    def test_cpe_deduplication(self):
        html = cpe_html(incl_archive=False)
        head = '<h4>martes 10 de noviembre de 2026</h4>'
        # Repeat exactly the same card, with the same source and window.
        copied = html[html.find(head):]
        html = html.replace(head, head+copied)
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _:html)
        self.assertLessEqual(len(out['notices']), 1)

if __name__ == '__main__':
    unittest.main()

"""CPE host fallback tests; tests are local, not live requests."""
import unittest
from urllib.error import HTTPError
from provincial_outages import collect_one, PROVIDERS, CPE_ALTERNATE

WHEN = '2026-11-09T16:00:00Z'


def no_current_html():
    return ('<html><h2>Estado de servicios</h2><h2>Cortes programados vigentes</h2>'
            '<div>No hay cortes programados vigentes.</div>'
            '<h2>Cortes programados pasados</h2><div>06/11/2026</div></html>')


def stale_html():
    return ('<h1>Estado de servicios</h1><h2>Cortes programados vigentes</h2>'
            '<h3>viernes 06 de noviembre de 2026</h3>'
            '<h4>Este viernes en Inti Hue y Las Camelias</h4><b>CORTE PROGRAMADO</b>'
            '<p>Este viernes 6 de noviembre, desde las 14:00 hasta las 17:00 horas, '
            'se producirá un corte en el suministro en la zona comprendida por la avenida Perón, '
            'Hernández, Colonia Santa María, Juana Azurduy y Clavelinas de Villa Las Camelias. '
            'Personal de la CPE remodelará una subestación transformadora.</p>'
            '<h2>Cortes programados pasados</h2>')


class CpeFallbackV5261(unittest.TestCase):
    def test_primary_official_host_and_old_host_fallback(self):
        self.assertEqual(PROVIDERS['cpe_la_pampa'][2], 'https://cpe.coop.ar/estado-servicios')
        self.assertEqual(CPE_ALTERNATE, 'https://sitionuevo.cpe.coop.ar/estado-servicios')

    def test_canonical_no_future_program_is_verified_not_power_status(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return no_current_html()
        out = collect_one('cpe_la_pampa', WHEN, fetcher=fetch)
        self.assertEqual(calls, [PROVIDERS['cpe_la_pampa'][2]])
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['notices'], [])
        self.assertIn('NO confirma servicio normal', out['message'])
        self.assertEqual(out['parser_revision'], 'CPE-WEB-v5.26.1')

    def test_fallback_after_primary_http_error(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if url == PROVIDERS['cpe_la_pampa'][2]:
                raise HTTPError(url, 403, 'Forbidden', None, None)
            return no_current_html()
        out = collect_one('cpe_la_pampa', WHEN, fetcher=fetch)
        self.assertEqual(calls, [PROVIDERS['cpe_la_pampa'][2], CPE_ALTERNATE])
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['source_url'], CPE_ALTERNATE)
        self.assertEqual(out['source_attempts'][0]['error_type'], 'HTTPError')
        self.assertEqual(out['source_attempts'][1]['result'], 'verified')
        self.assertEqual(out['notices'], [])

    def test_both_http_errors_cannot_silently_pass(self):
        calls = []
        def fetch(url):
            calls.append(url)
            raise HTTPError(url, 503, 'Service unavailable', None, None)
        out = collect_one('cpe_la_pampa', WHEN, fetcher=fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(out['status'], 'unverified')
        self.assertEqual(out['notices'], [])
        self.assertEqual(len(out['source_attempts']), 2)

    def test_past_only_records_do_not_cause_false_alarm(self):
        out = collect_one('cpe_la_pampa', WHEN, fetcher=lambda _: stale_html())
        self.assertEqual(out['status'], 'stale')
        self.assertEqual(out['notices'], [])
        self.assertEqual(len(out['source_attempts']), 2)

    def test_fallback_bulletin_has_real_source_url(self):
        future = ('<h2>Cortes programados vigentes</h2>'
                  '<h4>martes 10 de noviembre de 2026</h4>'
                  '<h3>Este martes en barrio Aeropuerto</h3><b>CORTE PROGRAMADO</b>'
                  '<p>Este martes, desde las 8:00 hasta las 10:30 horas, '
                  'se producira un corte en la zona comprendida por Avenida Spinetto, '
                  'Santiago Marzo, Torres y Viniegra, barrio Aeropuerto. '
                  'Personal de la CPE renovara una subestacion.</p>'
                  '<h2>Cortes programados pasados</h2>')
        def fetch(url):
            if url == PROVIDERS['cpe_la_pampa'][2]:
                raise HTTPError(url, 403, 'Forbidden', None, None)
            return future
        out = collect_one('cpe_la_pampa', WHEN, fetcher=fetch)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(len(out['notices']), 1)
        self.assertEqual(out['notices'][0]['source_url'], CPE_ALTERNATE)

    def test_primary_empty_shell_second_verified(self):
        def fetch(url):
            if url == PROVIDERS['cpe_la_pampa'][2]:
                return '<h2>Cortes programados vigentes</h2><div>Cargando...</div>'
            return no_current_html()
        out = collect_one('cpe_la_pampa', WHEN, fetcher=fetch)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['source_attempts'][0]['result'], 'no_complete_records')

if __name__ == '__main__':
    unittest.main()

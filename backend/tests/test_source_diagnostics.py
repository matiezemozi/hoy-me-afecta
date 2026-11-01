"""Test only public-source diagnostic metadata, not live pages."""
import unittest
from provincial_outages import (
    PROVIDERS, EPE_LEGACY, EPE_LEGACY_ALT, EPEC_ALTERNATE,
    collect_one, _diagnose_html,
)

NOW = '2026-11-01T18:00:00Z'


class Diagnostics(unittest.TestCase):
    def test_epe_dynamic_page_is_not_marked_as_ok(self):
        shell = ('<html><script src="/js/cortes.js?v=private_token"></script>'
                 '<h1>Trabajos programados</h1><p>Acá se cargan los cortes</p></html>')
        def fetch(url):
            if url == PROVIDERS['epe_santa_fe'][2]:
                return shell
            raise ConnectionError('no disponible')
        result = collect_one('epe_santa_fe', NOW, fetcher=fetch)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])
        self.assertEqual(len(result['source_attempts']), 3)
        first = result['source_attempts'][0]
        self.assertEqual(first['result'], 'dynamic_shell')
        self.assertEqual(first['same_origin_script_paths'], ['/js/cortes.js'])
        self.assertNotIn('private_token', str(first))
        self.assertEqual(result['source_attempts'][-1]['error_type'], 'ConnectionError')

    def test_epec_second_official_url_can_succeed(self):
        page = ('<h3>02/11/2026</h3><p>De 08:00 a 10:00 Motivo: Poda '
                'Localidad: CORDOBA Zona afectada: Barrio Centro</p>')
        calls = []
        def fetch(url):
            calls.append(url)
            if url == EPEC_ALTERNATE:
                return page
            return '<h1>Trabajos programados</h1>'
        result = collect_one('epec_cordoba', NOW, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['source_url'], EPEC_ALTERNATE)
        self.assertEqual(len(result['notices']), 1)
        self.assertEqual(len(result['source_attempts']), 2)
        self.assertEqual(result['source_attempts'][0]['result'], 'no_complete_records')
        self.assertEqual(result['source_attempts'][1]['result'], 'verified')

    def test_epe_legacy_current_is_used_if_available(self):
        card = ('<p>Localidad: Rosario Inicio: 02-11-2026 08:00 hs. '
                'Fin: 10:00 hs. Zona: Barrio Centro Causa: Poda Corte programado</p>')
        def fetch(url):
            return card if url == EPE_LEGACY_ALT else '<h1>Acá se cargan los cortes</h1>'
        result = collect_one('epe_santa_fe', NOW, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['source_url'], EPE_LEGACY_ALT)
        self.assertEqual(result['source_attempts'][2]['records_checked'], 1)

    def test_stale_does_not_pretend_current_coverage(self):
        old = ('<h3>12/10/2026</h3>De 08:00 a 10:00 Motivo: Poda '
               'Localidad: CORDOBA Zona afectada: Alberdi')
        result = collect_one('epec_cordoba', NOW, fetcher=lambda _: old)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['notices'], [])
        self.assertEqual(result['source_attempts'][0]['latest_published_date'], '2026-10-12')

    def test_diagnostics_do_not_expose_external_scripts(self):
        page = ('<html><script src="https://third.example/abc?token=secret"></script>'
                '<script src="/js/main.js?api_key=secret"></script></html>')
        found = _diagnose_html(page, PROVIDERS['epec_cordoba'][2], 'epec_cordoba')
        self.assertEqual(found['same_origin_script_paths'], ['/js/main.js'])
        self.assertNotIn('secret', str(found))

if __name__ == '__main__':
    unittest.main()

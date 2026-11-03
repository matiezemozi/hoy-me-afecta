"""No remote data is fetched by tests."""
import unittest
from unittest.mock import patch
from source_javascript_diagnostics import (
    _trusted_script_url, _safely_extract_hints, probe_official_scripts,
)
from provincial_outages import collect_one, PROVIDERS

NOW = '2026-11-01T23:00:00Z'

class OfficialJavaScriptDiagnostics(unittest.TestCase):
    def test_allow_one_bundled_script_only_from_official_domains(self):
        page = PROVIDERS['epec_cordoba'][2]
        self.assertIsNotNone(_trusted_script_url(page, '/actualidad/main.7408cd4426f1ac179abd.js', 'epec_cordoba'))
        self.assertIsNone(_trusted_script_url(page, 'https://evil.example/actualidad/main.1.js', 'epec_cordoba'))
        self.assertIsNone(_trusted_script_url(page, '/actualidad/main.1.js?token=abc', 'epec_cordoba'))
        self.assertIsNone(_trusted_script_url(page, '/actualidad/scripts.1.js', 'epec_cordoba'))

    def test_epe_official_astro_bundle_recognized(self):
        page = PROVIDERS['epe_santa_fe'][2]
        path = '/institucional/_astro/TrabajosProgramados.astro_astro_type_script_index_0_lang.C1JoA2Kk.js'
        self.assertIsNotNone(_trusted_script_url(page, path, 'epe_santa_fe'))

    def test_probe_is_bounded_and_never_emits_query_or_source_code(self):
        js = '''const a="https://api.epec.com.ar/api/cortes?token=SECRET123";
               const b="/api/trabajos-programados"; const c="https://evil.test/api/cortes";
               fetch(a); const password = "superSecret";'''
        result = _safely_extract_hints(js, 'epec_cordoba')
        self.assertIn('/api/trabajos-programados', result['candidate_public_paths'])
        self.assertIn('api.epec.com.ar', result['official_hosts_seen'])
        self.assertNotIn('SECRET123', str(result))
        self.assertNotIn('superSecret', str(result))
        self.assertNotIn('evil.test', str(result))
        self.assertEqual(result['javascript_requests_found']['fetch'], 1)

    def test_probe_no_remote_script_for_different_origin(self):
        calls = []
        result = probe_official_scripts(PROVIDERS['epec_cordoba'][2], 'epec_cordoba',
                                        ['https://example.com/actualidad/main.1.js'],
                                        fetcher=lambda url: calls.append(url))
        self.assertEqual(calls, [])
        self.assertEqual(result[0]['status'], 'no_target_bundle_found')

    def test_epec_collect_includes_diag_but_stays_unverified(self):
        page = ('<script src="/actualidad/main.7408cd4426f1ac179abd.js"></script>'
                '<h1>Mantenimiento y mejoras</h1>')
        script = 'fetch("/api/cortes-programados");'
        calls = []
        result = collect_one('epec_cordoba', NOW, fetcher=lambda _: page,
                             script_fetcher=lambda u: (calls.append(u) or script))
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['source_attempts'][0]['javascript_diagnostics'][0]['status'], 'scanned')
        self.assertIn('/api/cortes-programados', result['source_attempts'][0]['javascript_diagnostics'][0]['candidate_public_paths'])
        self.assertNotIn('javascript_diagnostics', result['source_attempts'][1])

    def test_mock_web_fetch_does_not_implicitly_fetch_js(self):
        page = ('<script src="/actualidad/main.7408cd4426f1ac179abd.js"></script>'
                '<h1>Mantenimiento</h1>')
        result = collect_one('epec_cordoba', NOW, fetcher=lambda u: page)
        self.assertFalse(any('javascript_diagnostics' in a for a in result['source_attempts']))

    def test_manual_workflow_probes_but_schedule_does_not(self):
        page = ('<script src="/actualidad/main.7408cd4426f1ac179abd.js"></script>'
                '<h1>Mantenimiento</h1>')
        with patch('provincial_outages.fetch_html', return_value=page), \
             patch('source_javascript_diagnostics.fetch_public_script', return_value='fetch("/api/cortes")') as read:
            with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'schedule'}):
                scheduled = collect_one('epec_cordoba', NOW)
            self.assertFalse(any('javascript_diagnostics' in x for x in scheduled['source_attempts']))
            self.assertEqual(read.call_count, 0)
            with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'workflow_dispatch'}):
                manual = collect_one('epec_cordoba', NOW)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(manual['source_attempts'][0]['javascript_diagnostics'][0]['status'], 'scanned')

    def test_fetch_fail_does_not_erase_original_problem(self):
        page = ('<script src="/institucional/_astro/TrabajosProgramados.astro_astro_type_script_index_0_lang.C1JoA2Kk.js"></script>'
                '<p>Acá se cargan los cortes</p>')
        def html(u):
            if 'reclamosweb' in u: raise OSError('unavailable')
            return page
        def fail(u): raise TimeoutError('network')
        result = collect_one('epe_santa_fe', NOW, fetcher=html, script_fetcher=fail)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['source_attempts'][0]['javascript_diagnostics'][0]['error_type'], 'TimeoutError')
        self.assertEqual(result['source_attempts'][1]['error_type'], 'OSError')

if __name__ == '__main__':
    unittest.main()

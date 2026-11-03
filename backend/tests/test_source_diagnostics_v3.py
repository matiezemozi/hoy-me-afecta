"""Offline safety and diagnostic checks for a bounded JS investigation."""
import unittest
from unittest.mock import patch
from source_javascript_diagnostics import (
    MAX_JS_BYTES, ScriptSample, ScriptProbeError, fetch_public_script,
    _safely_extract_hints, probe_official_scripts,
)
from provincial_outages import PROVIDERS

class _Response:
    def __init__(self, data, url, content_type='application/javascript'):
        self.data = data
        self.url = url
        self.headers = {'Content-Type': content_type}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def geturl(self): return self.url
    def read(self, n): return self.data[:n]

class SourceDiagnosticsV3(unittest.TestCase):
    def test_large_asset_is_scanned_only_as_a_labeled_partial_sample(self):
        url = 'https://www.epec.com.ar/actualidad/main.123.js'
        data = b'fetch("/api/cortes")' + b' ' * MAX_JS_BYTES
        with patch('source_javascript_diagnostics.urlopen', return_value=_Response(data,url)):
            sample = fetch_public_script(url)
        self.assertTrue(sample.truncated)
        self.assertTrue(len(sample.encode('utf-8')) <= MAX_JS_BYTES)
        result = probe_official_scripts(PROVIDERS['epec_cordoba'][2], 'epec_cordoba',
                                        ['/actualidad/main.123.js'], fetcher=lambda _:sample)[0]
        self.assertEqual(result['status'], 'scanned_partial')
        self.assertTrue(result['asset_sample_truncated'])
        self.assertIn('/api/cortes', result['candidate_public_paths'])

    def test_non_js_response_has_fixed_error_reason(self):
        url = 'https://www.epec.com.ar/actualidad/main.123.js'
        with patch('source_javascript_diagnostics.urlopen',return_value=_Response(b'<html></html>',url,'text/html')):
            result = probe_official_scripts(PROVIDERS['epec_cordoba'][2], 'epec_cordoba',
                                            ['/actualidad/main.123.js'])[0]
        self.assertEqual(result['error_code'],'returned_html_instead_of_js')
        self.assertNotIn('html>', str(result))

    def test_redirected_host_rejected_without_disclosing_url(self):
        url = 'https://www.epec.com.ar/actualidad/main.123.js'
        with patch('source_javascript_diagnostics.urlopen',return_value=_Response(b'x', 'https://other.example/path?secret=xxx')):
            result = probe_official_scripts(PROVIDERS['epec_cordoba'][2], 'epec_cordoba',
                                            ['/actualidad/main.123.js'])[0]
        self.assertEqual(result['error_code'], 'redirect_to_other_host')
        self.assertNotIn('xxx',str(result))

    def test_httpclient_import_is_not_endpoint_call(self):
        hint = _safely_extract_hints('class HttpClient{}; const s="/images/home.png";', 'epe_santa_fe')
        self.assertEqual(hint['javascript_requests_found']['httpclient_mentions'],1)
        self.assertEqual(hint['javascript_requests_found']['httpclient_method_calls'],0)
        self.assertEqual(hint['candidate_public_paths'],[])

    def test_httpclient_limited_static_route_is_a_hint_only(self):
        raw = '''HttpClient.get("/institucional/trabajos-lista");
                 HttpClient.post("https://epe.santafe.gov.ar/api/cortes?token=TOPSECRET");
                 const password="ABCDEFsecret";'''
        hint = _safely_extract_hints(raw,'epe_santa_fe')
        self.assertIn('/institucional/trabajos-lista',hint['candidate_public_paths'])
        self.assertNotIn('TOPSECRET',str(hint))
        self.assertNotIn('ABCDEFsecret',str(hint))
        self.assertIn('NO API',hint['note'])

    def test_unrelated_network_and_invalid_provider_fail_closed(self):
        url = PROVIDERS['epec_cordoba'][2]
        self.assertEqual(probe_official_scripts(url,'other',['/actualidad/main.123.js']),[])
        self.assertRaises(ScriptProbeError,_safely_extract_hints,'','other')

if __name__ == '__main__': unittest.main()

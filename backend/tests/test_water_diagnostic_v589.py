import socket
import ssl
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnosticar_agua_v589 as d

URL = 'https://example.invalid/noticias'
NOW = '2026-11-28T16:00:00+00:00'


def http(code):
    return HTTPError(URL, code, 'test', None, None)


def result(**kwargs):
    return dict({'status': 'unverified', 'notices': [], 'notifications_enabled': False}, **kwargs)


class Documents(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(d.inspect_document('  ')['document_kind'], 'empty')
    def test_feed(self):
        a = d.inspect_document('<?xml version="1.0"?><rss><channel><item/><item/></channel></rss>')
        self.assertEqual((a['document_kind'], a['feed_items']), ('xml_feed', 2))
    def test_atom(self):
        a = d.inspect_document('<feed xmlns="http://www.w3.org/2005/Atom"><entry/></feed>')
        self.assertEqual(a['feed_items'], 1)
    def test_bad_feed(self):
        self.assertEqual(d.inspect_document('<rss><item>')['document_kind'], 'invalid_xml_feed')
    def test_html(self):
        a = d.inspect_document('<h4>Comunicados</h4><a href="/aviso">Noticia</a>')
        self.assertEqual((a['document_kind'], a['anchors'], a['headings']), ('html_with_links', 1, 1))
    def test_interstitial(self):
        self.assertEqual(d.inspect_document('<title>Just a moment</title><script>test()</script>')['document_kind'], 'possible_access_interstitial')
    def test_script_shell(self):
        self.assertEqual(d.inspect_document('<div id="app"></div><script src="app.js"></script>')['document_kind'], 'possible_script_shell_or_interstitial')
    def test_no_false_interstitial(self):
        body = '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><p>Access denied in a report</p>'
        self.assertEqual(d.inspect_document(body)['document_kind'], 'html_with_links')
    def test_script_ignored(self):
        a = d.inspect_document('<script>"Access denied"</script><p>Hola</p>')
        self.assertEqual(a['visible_characters'], 4)
    def test_little_content(self):
        self.assertEqual(d.inspect_document('<p>Sin datos</p>')['document_kind'], 'little_visible_content')
    def test_text_without_links(self):
        self.assertEqual(d.inspect_document('<p>'+'abc '*100+'</p>')['document_kind'], 'html_text_without_links')
    def test_fingerprint(self):
        a, b, c = map(d.inspect_document, ['a', 'a', 'b'])
        self.assertEqual(a['sha256'], b['sha256'])
        self.assertNotEqual(a['sha256'], c['sha256'])


class Fetch(unittest.TestCase):
    def test_pass_through(self):
        f = d.TracedFetcher(lambda _: '<p>Noticia</p>')
        self.assertEqual(f(URL), '<p>Noticia</p>')
        self.assertEqual(f.attempts[0]['result'], 'document_received')
    def test_inspection_never_alters_fetch(self):
        f = d.TracedFetcher(lambda _: 'original')
        with patch.object(d, 'inspect_document', side_effect=ValueError):
            self.assertEqual(f(URL), 'original')
        self.assertEqual(f.attempts[0]['inspection_error'], 'ValueError')
    def test_redact_query(self):
        f = d.TracedFetcher(lambda _: 'ok')
        f(URL + '?private=secret')
        self.assertEqual(f.attempts[0]['url'], URL)
        self.assertTrue(f.attempts[0]['query_present'])
        self.assertNotIn('secret', str(f.attempts))
    def test_https_only(self):
        m = Mock()
        with self.assertRaises(ValueError):
            d.TracedFetcher(m)('http://example.invalid/')
        m.assert_not_called()
    def test_429_no_retry(self):
        m = Mock(side_effect=http(429))
        f = d.TracedFetcher(m)
        with self.assertRaises(HTTPError): f(URL)
        with self.assertRaises(RuntimeError): f(URL)
        self.assertEqual(m.call_count, 1)
        self.assertTrue(f.rate_limited)
    def test_403_preserved(self):
        f = d.TracedFetcher(Mock(side_effect=http(403)))
        with self.assertRaises(HTTPError): f(URL)
        self.assertEqual(f.attempts[0]['http_status'], 403)
        self.assertEqual(d.disposition(result(), f), 'all_requests_forbidden')
    def test_request_limit(self):
        m = Mock(return_value='ok')
        f = d.TracedFetcher(m, max_requests=1)
        f(URL)
        with self.assertRaises(RuntimeError): f(URL)
        self.assertTrue(f.budget_exhausted)
        self.assertEqual(m.call_count, 1)
    def test_time_limit(self):
        clock = Mock(side_effect=[0, 91])
        m = Mock()
        f = d.TracedFetcher(m, clock=clock, max_seconds=90)
        with self.assertRaises(RuntimeError): f(URL)
        m.assert_not_called()
    def test_dns_tls_timeout_connection(self):
        for exc, expected in [(socket.gaierror('test'), 'dns'), (ssl.SSLError('test'), 'tls'), (TimeoutError(), 'timeout'), (ConnectionError(), 'connection')]:
            with self.subTest(kind=expected):
                self.assertEqual(d.error_details(URLError(exc))['reason_kind'], expected)
    def test_no_error_message_leak(self):
        self.assertNotIn('secret', str(d.error_details(URLError('secret'))))


class Batch(unittest.TestCase):
    def test_batches(self):
        keys = tuple('extra'+str(i) for i in range(22)) + d.PRIORITY
        batches = d.ordered_batches(keys)
        self.assertEqual([len(b) for b in batches], [8,8,8,6])
        self.assertEqual(batches[0], d.PRIORITY)
        self.assertEqual(set(sum(batches, ())), set(keys))
    def test_no_duplicates(self):
        with self.assertRaises(ValueError): d.ordered_batches(d.PRIORITY + d.PRIORITY)
    def test_missing_source(self):
        with self.assertRaises(ValueError): d.ordered_batches(d.PRIORITY[:-1])
    def test_no_normality(self):
        f = d.TracedFetcher(lambda _: '<a href="/a">test</a>')
        f(URL)
        self.assertEqual(d.disposition(result(), f), 'html_links_received_collector_no_accepted_bulletin')
    def test_account_only(self):
        self.assertEqual(d.disposition(result(coverage_kind='address_account_lookup_only'), d.TracedFetcher(Mock())), 'account_only_not_public_status')
    def test_accepted(self):
        self.assertEqual(d.disposition(result(notices=[{}]), d.TracedFetcher(Mock())), 'public_bulletins_accepted_not_live')
    def test_stale(self):
        self.assertEqual(d.disposition(result(status='stale'), d.TracedFetcher(Mock())), 'old_bulletins_not_live')
    def test_rate_limit_label(self):
        f = d.TracedFetcher(Mock()); f.rate_limited = True
        self.assertEqual(d.disposition(result(), f), 'rate_limited')
    def test_budget_label(self):
        f = d.TracedFetcher(Mock()); f.budget_exhausted = True
        self.assertEqual(d.disposition(result(), f), 'query_budget_exhausted')
    def module(self, collect):
        return SimpleNamespace(SOURCES=dict.fromkeys(d.PRIORITY), fetch_html=Mock(return_value='ok'),
            collect_one=collect, _safe_source_result=lambda k,r,t:r)
    def test_isolated_failure(self):
        m = self.module(Mock(side_effect=ValueError))
        a = d.run_one(m, d.PRIORITY[0], NOW)
        self.assertEqual(a['collector_result']['status'], 'unverified')
        self.assertEqual(a['collector_result']['notices'], [])
    def test_notification_safety(self):
        m = self.module(Mock(return_value=result(notices=[{'notification_allowed': True}])))
        a = d.run_one(m, d.PRIORITY[0], NOW)
        self.assertTrue(a['safety_errors']); self.assertEqual(a['collector_result']['notices'], [])
    def test_account_never_emits(self):
        m = self.module(Mock(return_value=result(notices=[{'notification_allowed': False}])))
        a = d.run_one(m, 'aysa_amba', NOW)
        self.assertIn('account_only_source_emitted_notices', a['safety_errors'])
    def test_all_8_once(self):
        def collect(k,t,fetcher):
            fetcher(URL)
            return result()
        m = self.module(collect)
        a = d.run_batch(m, 1)
        self.assertEqual(a['sources_checked'], 8)
        self.assertFalse(a['production_feed_changed'])
        self.assertFalse(a['notifications_enabled'])
        self.assertEqual([i['source'] for i in a['results']], list(d.PRIORITY))
        self.assertEqual(m.fetch_html.call_count, 8)
    def test_invalid_batch(self):
        m = self.module(Mock())
        with self.assertRaises(ValueError): d.run_batch(m, 2)


if __name__ == '__main__':
    unittest.main()

"""v5.83: nonblocking batch checks, budgets, security and source isolation."""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-24T21:50:16Z'
JURL = ('https://prensa.jujuy.gob.ar/agua-potable/'
        'agua-potable-informa-corte-emergencia-y-puesta-marcha-obra-definitiva-alto-comedero-y-los-alisos-n126093')
JTITLE = 'Agua Potable informa corte de emergencia y puesta en marcha de obra definitiva en Alto Comedero y Los Alisos'


class TestProductionBatchV583(unittest.TestCase):
    def test_all_30_configured_sources_preserved(self):
        self.assertEqual(len(w.SOURCES),30)
        self.assertEqual(len(set(w.SOURCES)),30)
        for key,(name,province,url) in w.SOURCES.items():
            with self.subTest(key=key):
                self.assertTrue(name and province)
                self.assertTrue(url.startswith('https://'))

    def test_safe_max_parallelism(self):
        self.assertGreaterEqual(w.MAX_PARALLEL_SOURCES,2)
        self.assertLessEqual(w.MAX_PARALLEL_SOURCES,4)

    def test_source_request_cap_above_existing_absa_11_calls(self):
        self.assertGreaterEqual(w.MAX_NETWORK_FETCHES_PER_SOURCE,11)
        self.assertLessEqual(w.MAX_NETWORK_FETCHES_PER_SOURCE,20)

    def test_elapsed_budget_exceeds_one_socket_timeout(self):
        self.assertGreaterEqual(w.MAX_SOURCE_NETWORK_SECONDS,26)
        self.assertLessEqual(w.MAX_SOURCE_NETWORK_SECONDS,120)

    def test_network_fetch_budget_stops_future_calls(self):
        seen=[]
        f=w._budgeted_fetcher(lambda url:seen.append(url) or 'ok',max_fetches=2,max_seconds=90)
        self.assertEqual(f('https://site.test/a'),'ok')
        self.assertEqual(f('https://site.test/b'),'ok')
        with self.assertRaises(w.SourceFetchBudgetExceeded): f('https://site.test/c')
        self.assertEqual(len(seen),2)

    def test_elapsed_budget_stops_next_request(self):
        times=iter([0,1,10])
        seen=[]
        f=w._budgeted_fetcher(lambda url:seen.append(url) or 'ok',
                              max_fetches=5,max_seconds=5,clock=lambda:next(times))
        self.assertEqual(f('https://site.test/a'),'ok')
        with self.assertRaises(w.SourceFetchBudgetExceeded): f('https://site.test/b')
        self.assertEqual(len(seen),1)

    def test_max_fetches_zero_blocks_all(self):
        f=w._budgeted_fetcher(lambda _:self.fail('should never execute'),max_fetches=0)
        with self.assertRaises(w.SourceFetchBudgetExceeded):f('https://site.test')

    def test_bad_source_does_not_abort_thirty_source_report(self):
        def offline(url):
            raise ConnectionError('network unavailable')
        report=w.collect_water(STAMP,fetcher=offline)
        self.assertEqual(len(report['sources']),30)
        self.assertEqual(list(report['sources']),list(w.SOURCES))
        self.assertEqual(report['source_health']['configured_sources'],30)
        self.assertEqual(report['notices'],[])
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])

    def test_production_concurrent_workers_are_bounded_and_order_preserved(self):
        lock=threading.Lock()
        count={'active':0,'peak':0}
        names=[]
        def one(key,stamp,fetcher=None):
            with lock:
                count['active']+=1
                count['peak']=max(count['peak'],count['active'])
                names.append(threading.current_thread().name)
            try:
                time.sleep(0.014)
                result=w._result(key,stamp)
                return result
            finally:
                with lock:count['active']-=1
        with patch.object(w,'collect_one',side_effect=one):
            report=w.collect_water(STAMP)
        self.assertGreaterEqual(count['peak'],2)
        self.assertLessEqual(count['peak'],w.MAX_PARALLEL_SOURCES)
        self.assertTrue(all('water-source' in n for n in names))
        self.assertEqual(list(report['sources']),list(w.SOURCES))

    def test_arsa_production_fetch_is_tagged_for_rate_limit_pause(self):
        tags={}
        def one(key,stamp,fetcher=None):
            tags[key]=bool(getattr(fetcher,'_production_network_fetch',False))
            return w._result(key,stamp)
        with patch.object(w,'collect_one',side_effect=one):
            w.collect_water(STAMP)
        self.assertTrue(tags['aguas_rionegrinas_arsa'])
        self.assertEqual(len(tags),30)

    def test_injected_fetcher_remains_sequential_for_unit_tests(self):
        names=[]
        def one(key,stamp,fetcher=None):
            names.append(threading.current_thread().name)
            return w._result(key,stamp)
        with patch.object(w,'collect_one',side_effect=one):
            r=w.collect_water(STAMP,fetcher=lambda _: '')
        self.assertEqual(len(set(names)),1)
        self.assertEqual(list(r['sources']),list(w.SOURCES))

    def test_one_collector_crash_isolated_in_parallel(self):
        def one(key,stamp,fetcher=None):
            if key=='agua_potable_jujuy_prensa':raise ValueError('bad remote HTML')
            return w._result(key,stamp)
        with patch.object(w,'collect_one',side_effect=one):
            result=w.collect_water(STAMP)
        self.assertIn('Fallo aislado: ValueError',result['sources']['agua_potable_jujuy_prensa']['message'])
        self.assertEqual(len(result['sources']),30)
        self.assertFalse(result['notifications_enabled'])

    def test_budget_exhaustion_is_reported_but_not_taken_as_service_normal(self):
        r=w.source_health_summary({'blocked':{'status':'unverified','notices':[],
            'message':'Fallo aislado: SourceFetchBudgetExceeded'},
            'blocked2':{'status':'unverified','notices':[],
            'index_attempts':[{'result':'fetch_or_parse_error',
                               'error_type':'SourceFetchBudgetExceeded'}]},
            'good':{'status':'ok','notices':[]}})
        self.assertEqual(r['source_query_budget_exhausted'],['blocked','blocked2'])
        self.assertEqual(r['status_counts']['unverified'],2)

    def test_no_budget_exception_when_sources_are_fast_and_empty(self):
        f=w._budgeted_fetcher(lambda _: '<html><body>No hay anuncios</body></html>')
        self.assertIn('<html>',f('https://example.test'))

    def test_no_http_url_allowed(self):
        with self.assertRaises(ValueError):w.fetch_html('http://example.test')

    def test_redirect_to_http_is_not_accepted(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return 'http://unsafe.test/index'
            def read(self,*args):self_read_called.append(True);return b'unsafe'
        self_read_called=[]
        with patch.object(w,'urlopen',return_value=Response()):
            with self.assertRaisesRegex(ValueError,'HTTPS'):
                w.fetch_html('https://official.test/page')
        self.assertEqual(self_read_called,[])

    def test_https_redirect_allowed(self):
        class Headers:
            def get_content_charset(self):return 'utf-8'
        class Response:
            headers=Headers()
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return 'https://official.test/new-index'
            def read(self,*args):return b'Official index'
        with patch.object(w,'urlopen',return_value=Response()):
            self.assertEqual(w.fetch_html('https://official.test/page'),'Official index')

    def test_generated_report_keeps_readonly_flags_with_empty_sources(self):
        report=w.collect_water(STAMP,fetcher=lambda url:'<html><body>Sin datos</body></html>')
        self.assertTrue(report['android_read_only_pilot_available'])
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertTrue(all(x.get('notification_allowed') is not True for x in report['notices']))


class TestJujuyPreciseDiagnosticsV583(unittest.TestCase):
    def _collect(self,body):
        index=f'<h2><a href="{JURL}">{JTITLE}</a></h2>'
        html=(f'<html><head><meta property="article:published_time" '
              'content="2026-11-24T11:00:00-03:00"></head><body>'
              f'<h1>{JTITLE}</h1><div>24 de noviembre de 2026 - 11:00</div>'
              f'<p>{body}</p><h2>Las más leídas</h2></body></html>')
        return w.collect_one('agua_potable_jujuy_prensa',STAMP,
                             fetcher=lambda u:index if u==w.SOURCES['agua_potable_jujuy_prensa'][2] else html)

    def test_insufficient_body_is_diagnostic_not_notice(self):
        r=self._collect('Agua Potable comunicó un informe sin afectación del agua de red.')
        # The text is intentionally too short and does not identify a positive impact.
        self.assertEqual(r['notices'],[])

    def test_html_shape_diagnostic_no_article_text_stored(self):
        r=self._collect('Reunión y actividades de gestión que no anuncian afectación del servicio.')
        attempt=r['source_attempts'][0]
        self.assertEqual(attempt['result'],'no_verifiable_water_article_body')
        self.assertGreater(attempt['article_html_bytes'],0)
        self.assertGreater(attempt['article_visible_characters'],0)
        self.assertGreaterEqual(attempt['article_paragraphs_seen'],1)
        self.assertGreaterEqual(attempt['matching_headings_seen'],1)
        self.assertNotIn('body',attempt)
        self.assertNotIn('text',attempt)

    def test_emergency_with_impact_still_validated(self):
        r=self._collect('Agua Potable de Jujuy informa que un corte de emergencia del servicio '
                         'de agua potable afectará Alto Comedero y Los Alisos. ') 
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        self.assertFalse(r['notices'][0]['notification_allowed'])


if __name__=='__main__':unittest.main()

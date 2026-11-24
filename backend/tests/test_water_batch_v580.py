"""v5.80: transparent source-reachability diagnostics, no outage inference."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

T='2026-11-24T02:46:08Z'
SANTA='santa_rosa_municipal_lp'


def denied(url):
    raise HTTPError(url,403,'Forbidden',{},None)


class SourceHealthV580(unittest.TestCase):
    def test_santa_rosa_403_all_four_diagnosed_not_javascript(self):
        r=w.collect_one(SANTA,T,denied)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['http_status'],403)
        self.assertEqual(r['access_mode'],'official_site_rejected_automated_request')
        self.assertIn('HTTP 403',r['message'])
        self.assertNotIn('JavaScript',r['index_warning'])
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(len(r['fallback_index_attempts']),2)
        self.assertEqual(r['notices'],[])

    def test_mixed_failure_does_not_claim_all_four_blocked(self):
        def mixed(url):
            if 'rss.xml' in url or url.endswith('/noticias/'):
                return denied(url)
            return '<html><body>Sin titulares municipales</body></html>'
        r=w.collect_one(SANTA,T,mixed)
        self.assertNotIn('access_mode',r)
        self.assertNotIn('http_status',r)
        self.assertEqual(r['status'],'unverified')
        h=w.source_health_summary({SANTA:r})
        self.assertEqual(h['all_index_requests_rejected_http_403'],[])
        self.assertEqual(h['readable_sources_without_accepted_bulletins'],[SANTA])

    def test_blocked_403_with_source_errors_does_not_pollute_notices(self):
        report=w.collect_water(T,denied)
        self.assertEqual(report['status'],'pilot_read_only_in_android')
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertEqual(report['notices'],[])
        self.assertEqual(report['source_health']['configured_sources'],30)
        self.assertIn(SANTA,report['source_health']['all_index_requests_rejected_http_403'])

    def test_unreachable_url_error_not_mistaken_for_http_403(self):
        r={'status':'unverified','notices':[], 'index_attempts':[{'result':'fetch_or_parse_error',
                'error_type':'URLError'}, {'result':'fetch_or_parse_error','error_type':'URLError'}]}
        d=w.source_health_summary({'chaco':r})
        self.assertEqual(d['all_index_requests_failed_url_error'],['chaco'])
        self.assertEqual(d['all_index_requests_rejected_http_403'],[])
        self.assertEqual(d['unverified_without_readable_index'],['chaco'])

    def test_one_readable_index_suppresses_all_failed_flag(self):
        r={'status':'unverified','notices':[], 'index_attempts':[
            {'result':'fetch_or_parse_error','error_type':'HTTPError','http_status':403},
            {'result':'official_index_read'}]}
        d=w.source_health_summary({'cba':r})
        self.assertEqual(d['all_index_requests_rejected_http_403'],[])
        self.assertEqual(d['readable_sources_without_accepted_bulletins'],['cba'])
        self.assertEqual(d['unverified_without_readable_index'],[])

    def test_readable_does_not_claim_publication_or_normal_service(self):
        r={'status':'unverified','notices':[], 'index_attempts':[{'result':'official_index_read'}]}
        d=w.source_health_summary({'cba':r})
        self.assertEqual(d['accepted_public_bulletins'],0)
        self.assertEqual(d['sources_with_accepted_bulletins'],[])
        self.assertIn('does not confirm live water service',d['interpretation'])

    def test_ok_without_notices_not_counted_as_accepted_bulletins(self):
        d=w.source_health_summary({'salta':{'status':'ok','notices':[]}})
        self.assertEqual(d['status_counts']['ok'],1)
        self.assertEqual(d['readable_sources_without_accepted_bulletins'],['salta'])
        self.assertEqual(d['accepted_public_bulletins'],0)

    def test_stale_is_not_coverage_proof(self):
        d=w.source_health_summary({'absa':{'status':'stale','notices':[]}})
        self.assertEqual(d['status_counts']['stale'],1)
        self.assertEqual(d['accepted_public_bulletins'],0)
        self.assertEqual(d['unverified_without_readable_index'],[])

    def test_accepted_bulletins_counted_once_no_duplicate_between_status_groups(self):
        r={'status':'ok','notices':[{'id':'one','notification_allowed':False},
                                    {'id':'two','notification_allowed':False}],
           'index_attempts':[{'result':'article_links_found'}]}
        d=w.source_health_summary({'arsa':r})
        self.assertEqual(d['accepted_public_bulletins'],2)
        self.assertEqual(d['sources_with_accepted_bulletins'],['arsa'])
        self.assertEqual(d['readable_sources_without_accepted_bulletins'],[])

    def test_article_403_only_not_all_indexes_blocked(self):
        r={'status':'unverified','notices':[], 'index_attempts':[{'result':'official_index_read'}],
           'source_attempts':[{'result':'fetch_or_parse_error','error_type':'HTTPError','http_status':403}]}
        d=w.source_health_summary({'key':r})
        self.assertEqual(d['all_index_requests_rejected_http_403'],[])
        self.assertEqual(d['readable_sources_without_accepted_bulletins'],['key'])

    def test_empty_source_set_still_explicit(self):
        r=w.source_health_summary({})
        self.assertEqual(r['configured_sources'],0)
        self.assertEqual(r['accepted_public_bulletins'],0)
        self.assertEqual(r['status_counts'],{'ok':0,'stale':0,'unverified':0})

    def test_source_health_rejects_non_mapping(self):
        with self.assertRaises(TypeError):w.source_health_summary([])

    def test_output_schema_additive_not_mutating(self):
        sources={'A':{'status':'unverified','notices':[], 'index_attempts':[{'result':'official_index_read'}]}}
        original=str(sources)
        w.source_health_summary(sources)
        self.assertEqual(str(sources),original)

    def test_all_sources_are_local_our_app_does_not_query_credentials(self):
        d=w.collect_water(T,lambda _: '<html><body>Sin novedades</body></html>')
        self.assertEqual(len(d['sources']),30)
        self.assertEqual(d['source_health']['configured_sources'],30)
        self.assertFalse(d['notifications_enabled'])
        self.assertEqual(d['source_health']['accepted_public_bulletins'],len(d['notices']))
        self.assertTrue(all(n['notification_allowed'] is False for n in d['notices']))

    def test_real_v579_santa_rosa_fixture(self):
        # Fixture reproduces exactly the four access failures observed in GitHub.
        d=w.source_health_summary({SANTA:w.collect_one(SANTA,T,denied)})
        self.assertEqual(d['all_index_requests_rejected_http_403'],[SANTA])
        self.assertEqual(d['accepted_public_bulletins'],0)
        self.assertEqual(d['unverified_without_readable_index'],[SANTA])

if __name__=='__main__':unittest.main()

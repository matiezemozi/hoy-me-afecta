import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from change_tracking import compare_feeds
import collector


def outage(locality='PILAR', users='6', company='Edenor', estimated=None):
    return {'category':'electricidad', 'company':company, 'partido':'PILAR',
            'localidad':locality, 'title':'Interrupción de baja tensión',
            'zone_detail':None, 'users_affected':users, 'expected_restoration':estimated,
            'id':'an-id-that-changes-with-users', 'source_url':'https://www.enre.gov.ar/test'}


def feed(time, events, edn='ok', eds='ok'):
    return {'generated_at':time, 'alerts':events,
            'sources':{'edenor':{'status':edn}, 'edesur':{'status':eds}}}


OLD = '2026-10-25T15:00:00Z'
NEW = '2026-10-25T16:00:00Z'


class DiffTests(unittest.TestCase):
    def test_initial_snapshot_does_not_claim_everything_is_new(self):
        result=compare_feeds(None,feed(NEW,[outage()]))
        self.assertEqual(result['status'],'no_recent_baseline')
        self.assertEqual(result['new_in_publication_count'],0)

    def test_count_change_is_not_new_incident(self):
        diff=compare_feeds(feed(OLD,[outage(users='3')]),feed(NEW,[outage(users='7')]))
        self.assertEqual(diff['status'],'ok')
        self.assertEqual(diff['new_in_publication_count'],0)
        self.assertEqual(diff['no_longer_listed_count'],0)

    def test_new_locality_is_newly_listed(self):
        diff=compare_feeds(feed(OLD,[outage()]),feed(NEW,[outage(),outage('RECOLETA')]))
        self.assertEqual(diff['new_in_publication_count'],1)
        self.assertEqual(diff['new_in_publication'][0]['localidad'],'RECOLETA')
        self.assertIn('inicio real desconocido',diff['new_in_publication'][0]['meaning'])

    def test_no_longer_listed_does_not_claim_restoration(self):
        diff=compare_feeds(feed(OLD,[outage()]),feed(NEW,[]))
        self.assertEqual(diff['no_longer_listed_count'],1)
        self.assertNotIn('resuelto',str(diff['no_longer_listed_count']))

    def test_source_failure_prevents_comparison(self):
        diff=compare_feeds(feed(OLD,[outage()]),feed(NEW,[],edn='error'))
        self.assertEqual(diff['status'],'partial')
        self.assertEqual(diff['new_in_publication_count'],0)
        self.assertEqual(diff['no_longer_listed_count'],0)

    def test_stale_or_future_baseline_not_accepted(self):
        self.assertEqual(compare_feeds(feed('2026-10-24T01:00:00Z',[outage()]),feed(NEW,[]))['status'],'no_recent_baseline')
        self.assertEqual(compare_feeds(feed('2026-10-26T01:00:00Z',[outage()]),feed(NEW,[]))['status'],'no_recent_baseline')

    def test_earlier_local_estimate_flagged_but_not_resolved(self):
        data=feed(NEW,[outage(estimated='2026-10-25 12:30')]) # 16:00 UTC = 13:00 AR
        diff=compare_feeds(None,data)
        self.assertEqual(diff['past_estimated_restoration_count'],1)
        self.assertIn('aún publica',diff['past_estimated_restoration'][0]['message'])
        data['alerts'][0]['expected_restoration']='2026-10-25 14:00'
        self.assertEqual(compare_feeds(None,data)['past_estimated_restoration_count'],0)

    def test_bad_estimate_does_not_crash(self):
        result=compare_feeds(None,feed(NEW,[outage(estimated='Sin datos')]))
        self.assertEqual(result['past_estimated_restoration_count'],0)

    def test_same_place_multiple_outages_counted_conservatively(self):
        diff=compare_feeds(feed(OLD,[outage()]),feed(NEW,[outage(),outage(users='200')]))
        self.assertEqual(diff['new_in_publication_count'],1)

    def test_collector_reads_previous_snapshot_and_writes_comparison(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            target=root/'feed.json'
            prior=feed(OLD,[outage()])
            target.write_text(json.dumps(prior), encoding='utf-8')
            manual=root/'manual.json'
            manual.write_text('[]',encoding='utf-8')
            with patch.object(collector, 'now_utc', return_value=NEW), \
                 patch.object(collector,'fetch_js',return_value={'cortesServicioBaja':[{'partido':'PILAR','localidad':'RECOLETA','usuarios':10}]}):
                collector.collect(target, manual, fetch_banking=lambda t: {})
            generated=json.loads(target.read_text(encoding='utf-8'))
            self.assertIn('change_tracking',generated)
            self.assertEqual(generated['change_tracking']['status'],'ok')
            self.assertEqual(generated['change_tracking']['new_in_publication_count'],2)

if __name__ == '__main__':
    unittest.main()

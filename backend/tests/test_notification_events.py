import sys
from pathlib import Path
import unittest
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notification_events import journal
import collector

NOW = '2026-10-25T17:00:00Z'
ITEM = {'company':'Edesur','title':'Corte programado','partido':'PILAR','localidad':'VILLA ROSA', 'source_url':'https://www.enre.gov.ar/'}

def data(ts=NOW, status='ok', added=None):
    return {'generated_at':ts, 'sources':{'edesur':{'status':'ok'},'edenor':{'status':'ok'}},
            'change_tracking':{'status':status, 'new_in_publication':added if added is not None else []}}

class TestJournal(unittest.TestCase):
    def test_first_new_item(self):
        result = journal(None, data(added=[ITEM]))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['kind'], 'electricity_publication_added')
        self.assertEqual(result['events'][0]['country'],'Argentina')

    def test_replay_from_previous(self):
        old = data(added=[ITEM]); old['notification_events'] = journal(None,old)
        fresh = data('2026-10-25T17:30:00Z')
        self.assertEqual(len(journal(old,fresh)['events']),1)

    def test_does_not_reemit_when_count_changes(self):
        old = data(added=[ITEM]); old['notification_events'] = journal(None,old)
        new = dict(ITEM, users_affected='100', expected_restoration='2026-10-25 20:00')
        self.assertEqual(len(journal(old,data('2026-10-25T17:30:00Z',added=[new]))['events']),1)

    def test_expired_removed(self):
        old = data(added=[ITEM]); old['notification_events'] = journal(None,old)
        self.assertEqual(len(journal(old,data('2026-10-25T20:30:00Z'))['events']),0)

    def test_no_events_on_unverified_comparison(self):
        self.assertEqual(journal(None,data(status='no_recent_baseline',added=[ITEM]))['events'], [])

    def test_skip_failed_provider(self):
        d = data(added=[ITEM]); d['sources']['edesur']['status'] = 'error'
        self.assertEqual(len(journal(None,d)['events']),0)

    def test_invalid_missing_fields(self):
        self.assertEqual(len(journal(None,data(added=[{'company':'Edesur','title':'x'}]))['events']),0)

    def test_multiple_separate_places(self):
        second = dict(ITEM, localidad='RECOLETA')
        self.assertEqual(len(journal(None,data(added=[ITEM,second]))['events']),2)

    def test_invalid_time(self):
        self.assertEqual(journal(None,data(ts='invalid'))['status'], 'invalid_timestamp')

    def test_collector_publishes_journal_from_previous_feed(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'feed.json'
            previous = data('2026-10-25T16:30:00Z')
            previous['alerts'] = []
            dest.write_text(json.dumps(previous), encoding='utf-8')
            alert = dict(ITEM, category='electricidad', id='arbitrary')
            def parse(doc, provider, when):
                return [alert] if provider == 'edesur' else []
            with patch.object(collector, 'now_utc', return_value=NOW), \
                 patch.object(collector, 'fetch_js', return_value={}), \
                 patch.object(collector, 'parse_enre', side_effect=parse):
                collector.collect(dest, Path(tmp)/'nonexistent.json',
                                  Path(tmp)/'no_public.json',
                                  fetch_banking=lambda ts: {})
            built = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(built['notification_events']['status'], 'ready')
            self.assertEqual(len(built['notification_events']['events']), 1)
            self.assertEqual(built['notification_events']['events'][0]['localidad'], 'VILLA ROSA')

    def test_no_false_notification_on_missing_baseline(self):
        previous = data('2026-10-25T01:00:00Z')
        previous['alerts'] = []
        current = data(added=[ITEM],status='no_recent_baseline')
        self.assertEqual(journal(previous,current)['events'], [])

    def test_immutable_source(self):
        value = data(added=[ITEM]); copy = str(value)
        journal(None,value)
        self.assertEqual(str(value),copy)

if __name__ == '__main__': unittest.main()

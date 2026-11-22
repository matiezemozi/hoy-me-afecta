"""v5.54: offline ARSA two-article budget, rotation and conservative status.

Fixtures do not contact external sites. No push notification is enabled.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

INDEX=w.SOURCES['aguas_rionegrinas_arsa'][2]
BASE='https://aguasrionegrinas.com/'

def url(n):
    return BASE+f'bariloche-corte-de-agua-en-sector-localidad-{n}/'

def index(n=4):
    return '<h1>Interrupciones</h1>'+''.join(
        f'<p>16 de noviembre de 2026</p><a href="{url(i)}">Bariloche: interrupción del servicio de agua sector {i}</a>'
        for i in range(n))

ARTICLE=('''<meta property="article:published_time" content="2026-11-16T11:10:00-03:00">
<h1>Bariloche: interrupción del servicio de agua potable en sector</h1>
<p>Aguas Rionegrinas informa que el suministro de agua potable presenta baja presión en sector
Pilar de la localidad de Bariloche por una falla imprevista del sistema de bombeo.</p>''')


def run(stamp,n=4,fail=None):
    calls=[]
    def fetch(u):
        calls.append(u)
        if u==INDEX: return index(n)
        if u==fail:raise HTTPError(u,429,'Too many requests',None,None)
        return ARTICLE
    return w.collect_one('aguas_rionegrinas_arsa',stamp,fetcher=fetch),calls


class RotatingBudget554(unittest.TestCase):
    STAMP='2026-11-16T21:19:46Z'

    def test_budget_never_exceeds_two_article_requests(self):
        r,calls=run(self.STAMP,8)
        self.assertEqual(r['parser_revision'],'ARSA-STARTED-WORK-ESTIMATES-v5.70')
        self.assertEqual(r['max_article_requests_per_run'],2)
        self.assertEqual(r['article_links_seen'],8)
        self.assertEqual(r['articles_checked'],2)
        self.assertEqual(r['articles_deferred_by_budget'],6)
        self.assertEqual(calls[0],INDEX)
        self.assertEqual(len(calls),3)
        self.assertEqual(r['article_fetch_completeness'],'partial')

    def test_newest_always_selected(self):
        for hour in range(24):
            stamp=(datetime(2026,11,16,10,tzinfo=timezone.utc)+timedelta(hours=hour)).isoformat()
            r,calls=run(stamp,4)
            self.assertEqual(calls[1],url(0))
            self.assertEqual(len(r['article_links_selected']),2)

    def test_secondary_rotates_over_successive_utc_hours(self):
        secondary=[]
        for hour in range(3):
            stamp=(datetime(2026,11,16,19,tzinfo=timezone.utc)+timedelta(hours=hour)).isoformat()
            r,calls=run(stamp,4)
            secondary.append(calls[2])
        self.assertEqual(set(secondary),{url(1),url(2),url(3)})

    def test_repeated_run_same_hour_uses_same_sample(self):
        r1, calls1=run('2026-11-16T21:01:00Z',4)
        r2, calls2=run('2026-11-16T21:59:00Z',4)
        self.assertEqual(calls1,calls2)
        self.assertEqual(r1['sampling_rotation_utc_hour'],r2['sampling_rotation_utc_hour'])

    def test_one_article_stays_single_request(self):
        r,calls=run(self.STAMP,1)
        self.assertEqual(calls,[INDEX,url(0)])
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(r['articles_deferred_by_budget'],0)
        self.assertIsNone(r['sampling_secondary_index'])

    def test_429_on_second_request_is_reported_as_partial(self):
        original,_=run(self.STAMP,4)
        blocked=original['article_links_selected'][1]
        r,calls=run(self.STAMP,4,fail=blocked)
        self.assertTrue(r['rate_limited'])
        self.assertEqual(len(calls),3)
        self.assertEqual(r['articles_checked'],2)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['article_fetch_completeness'],'partial')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_429_on_newest_aborts_remaining_requests(self):
        r,calls=run(self.STAMP,4,fail=url(0))
        self.assertEqual(calls,[INDEX,url(0)])
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(r['article_links_skipped_after_rate_limit'],1)
        self.assertEqual(r['notices'],[])
        self.assertTrue(r['rate_limited'])
        self.assertEqual(r['article_fetch_completeness'],'partial')

    def test_only_empty_index_never_means_normal_service(self):
        r=w.collect_one('aguas_rionegrinas_arsa',self.STAMP,fetcher=lambda u:'<h1>Noticias</h1>')
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['notices'],[])

    def test_collection_all_sources_keep_notifications_off(self):
        r=w.collect_water(self.STAMP,fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertGreaterEqual(len(r['sources']),18)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(r['android_read_only_pilot_available'])

if __name__=='__main__':
    unittest.main()

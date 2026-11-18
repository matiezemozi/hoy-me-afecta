"""v5.55: prefer recent indexed ARSA bulletins, but retain safety controls."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

INDEX=w.SOURCES['aguas_rionegrinas_arsa'][2]
URL='https://aguasrionegrinas.com/bariloche-agua-potable-sector-noticia-'

def uri(i):
    return URL+str(i)+'/'

def listing(dates):
    # Publication date immediately preceding each title, like the official
    # archive. None models a source whose article date was not recognized.
    entries=['<h1>Interrupciones de servicio</h1>']
    for i,day in enumerate(dates):
        if day:
            entries.append('<p>'+day+'</p>')
        entries.append(f'<a href="{uri(i)}">Bariloche: servicio de agua potable en zona sector {i}</a>')
    return ''.join(entries)

ARTICLE=('''<meta property="article:published_time" content="2026-11-16T12:00:00-03:00">
<h1>Bariloche: corte de agua potable en zona sector Pilar</h1>
<p>Aguas Rionegrinas informa que la provisión de agua potable presenta baja presión
 en el barrio Pilar de la ciudad de Bariloche por tareas urgentes en el sistema de bombeo.</p>''')

def simulate(stamp,days,blocked=None):
    calls=[]
    def fetch(url):
        calls.append(url)
        if url==INDEX:return listing(days)
        if url==blocked:raise HTTPError(url,429,'Too many requests',None,None)
        return ARTICLE
    r=w.collect_one('aguas_rionegrinas_arsa',stamp,fetcher=fetch)
    return r,calls

class FreshRotation555(unittest.TestCase):
    def test_old_article_is_deprioritized_when_newer_articles_exist(self):
        days=['16 de noviembre de 2026']*3+['14 de noviembre de 2026']
        seen=[]
        for hour in range(6):
            stamp=(datetime(2026,11,16,18,tzinfo=timezone.utc)+timedelta(hours=hour)).isoformat()
            r,calls=simulate(stamp,days)
            self.assertEqual(r['parser_revision'],'ARSA-FRESH-ROTATION-v5.55')
            self.assertEqual(r['article_links_seen'],4)
            self.assertEqual(r['article_links_skipped_old'],0)
            self.assertEqual(r['sampling_secondary_pool_size'],2)
            self.assertEqual(r['sampling_older_secondary_deprioritized'],1)
            self.assertEqual(r['max_article_requests_per_run'],2)
            self.assertEqual(r['articles_checked'],2)
            self.assertEqual(r['articles_deferred_by_budget'],2)
            self.assertEqual(calls[1],uri(0))
            self.assertIn(calls[2],(uri(1),uri(2)))
            self.assertNotIn(uri(3),calls)
            seen.append(calls[2])
        self.assertEqual(set(seen),{uri(1),uri(2)})

    def test_older_secondary_is_fallback_when_only_newer_is_primary(self):
        r,calls=simulate('2026-11-16T21:00:00Z',
                         ['16 de noviembre de 2026','14 de noviembre de 2026'])
        self.assertEqual(calls,[INDEX,uri(0),uri(1)])
        self.assertEqual(r['sampling_older_secondary_deprioritized'],0)

    def test_undated_secondary_not_assumed_to_be_old(self):
        r,calls=simulate('2026-11-16T21:00:00Z',
                         ['16 de noviembre de 2026',None,'14 de noviembre de 2026'])
        self.assertEqual(calls,[INDEX,uri(0),uri(1)])
        self.assertEqual(r['sampling_older_secondary_deprioritized'],1)
        self.assertFalse(r['rate_limited'])

    def test_index_dates_not_borrowed_from_previous_article(self):
        content=listing(['16 de noviembre de 2026',None])
        dom,visible=w.page(content)
        self.assertEqual(w._arsa_index_date(visible,dom.anchors[0][1]),
                         datetime(2026,11,16).date())
        self.assertIsNone(w._arsa_index_date(visible,dom.anchors[1][1]))

    def test_all_same_day_rotate_without_starvation(self):
        days=['16 de noviembre de 2026']*4
        secondaries=[]
        for hour in range(3):
            stamp=(datetime(2026,11,16,19,tzinfo=timezone.utc)+timedelta(hours=hour)).isoformat()
            r,calls=simulate(stamp,days)
            secondaries.append(calls[2])
            self.assertEqual(r['sampling_older_secondary_deprioritized'],0)
        self.assertEqual(set(secondaries),{uri(1),uri(2),uri(3)})

    def test_http_429_stops_and_preserves_partial_diagnostics(self):
        stamp='2026-11-16T21:00:00Z'
        days=['16 de noviembre de 2026']*3+['14 de noviembre de 2026']
        normal,_=simulate(stamp,days)
        blocked=normal['article_links_selected'][1]
        r,calls=simulate(stamp,days,blocked=blocked)
        self.assertTrue(r['rate_limited'])
        self.assertEqual(r['article_fetch_completeness'],'partial')
        self.assertEqual(len(calls),3)
        self.assertEqual(r['articles_checked'],2)
        self.assertEqual(r['articles_deferred_by_budget'],2)
        self.assertTrue(all(x['notification_allowed'] is False for x in r['notices']))

    def test_all_sources_and_pilot_flags_unchanged(self):
        out=w.collect_water('2026-11-16T21:00:00Z',fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertGreaterEqual(len(out['sources']),18)
        self.assertFalse(out['notifications_enabled'])
        self.assertFalse(out['android_display_enabled'])
        self.assertTrue(out['android_read_only_pilot_available'])
        self.assertEqual(out['category'],'agua')

if __name__=='__main__':
    unittest.main()

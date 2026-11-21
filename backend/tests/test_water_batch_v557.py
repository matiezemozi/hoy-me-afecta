"""v5.57 conservative official municipality RSS collectors (offline only)."""
import sys, unittest
from pathlib import Path
from datetime import date,datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-17T22:27:23Z'
SL='san_luis_serba_municipal'
SR='santa_rosa_municipal_lp'
SL_URL='https://sanluislaciudad.gob.ar/serba-repara-acueducto-del-barrio-sur-con-posible-baja-presion/'
SR_URL='https://www.santarosa.gob.ar/noticias/reparacion-de-acueducto-anguil-santa-rosa/'
SL_TITLE='SerBa informa baja presion de agua potable en la ciudad de San Luis'
SR_TITLE='Santa Rosa anuncia posible baja presion de agua por tareas en el acueducto'


def feed(items):
    blocks=[]
    for title,link,pub in items:
        blocks.append('<item><title>'+title+'</title><link>'+link+'</link>'+
                     (('<pubDate>'+pub+'</pubDate>') if pub is not None else '')+'</item>')
    return '<?xml version="1.0"?><rss version="2.0"><channel>'+''.join(blocks)+'</channel></rss>'

DAY='Tue, 17 Nov 2026 21:00:00 +0000'
OLD='Fri, 06 Nov 2026 12:00:00 GMT'
FUTURE='Wed, 18 Nov 2026 15:00:00 GMT'

SL_ARTICLE=('''<html><meta property="article:published_time" content="2026-11-17T16:00:00-03:00"/>
    <h1>SerBa informa baja presion de agua potable en la ciudad de San Luis</h1>
    <p>SerBa informó que el suministro de agua potable registra baja presión en la zona sur de San Luis
    debido a tareas de reparación del acueducto. El trabajo afecta a barrios de la ciudad.
    </p></html>''')
SR_ARTICLE=('''<html><meta property="article:published_time" content="2026-11-17T10:00:00-03:00"/>
    <h1>Santa Rosa anuncia posible baja presion de agua por tareas en el acueducto</h1>
    <p>La Municipalidad de Santa Rosa informa que una falla en el acueducto Anguil Santa Rosa
    provocará baja presión en el suministro de agua potable en los barrios del norte.</p></html>''')

class TestMunicipalRss557(unittest.TestCase):
    def test_registry_20_sources(self):
        self.assertGreaterEqual(len(w.SOURCES),21)
        self.assertTrue(all(k in w.SOURCES for k in (SL,SR)))

    def test_san_luis_official_recent_impact(self):
        calls=[]
        f=feed([(SL_TITLE,SL_URL,DAY)])
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES[SL][2]:return f
            if url==SL_URL:return SL_ARTICLE
            raise AssertionError(url)
        result=w.collect_one(SL,STAMP,fetcher=fetch)
        self.assertEqual(calls,[w.SOURCES[SL][2], SL_URL])
        self.assertEqual(result['status'],'ok')
        self.assertIn(result['parser_revision'], ('MUNICIPAL-RSS-v5.57', 'MUNICIPAL-RSS-DIAGNOSTIC-v5.58'))
        self.assertEqual(result['rss_items_seen'],1)
        notice=result['notices'][0]
        self.assertEqual(notice['province'],'San Luis')
        self.assertEqual(notice['locality_hint'],'San Luis')
        self.assertEqual(notice['published_on'],'2026-11-17')
        self.assertFalse(notice['notification_allowed'])
        self.assertEqual(notice['status'],'publication_only_not_live')

    def test_santa_rosa_official_recent_impact(self):
        f=feed([(SR_TITLE,SR_URL,DAY)])
        def fetch(url):return f if url==w.SOURCES[SR][2] else SR_ARTICLE
        r=w.collect_one(SR,STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['province'],'La Pampa')
        self.assertEqual(r['notices'][0]['locality_hint'],'Santa Rosa')
        self.assertEqual(r['notices'][0]['scheduled_start'],None)

    def test_undated_no_article_fetched(self):
        r=w.collect_one(SL,STAMP,fetcher=lambda url:feed([(SL_TITLE,SL_URL,None)]))
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['articles_undated'],1)
        self.assertEqual(r['articles_checked'],0)

    def test_official_host_required_and_no_query_urls(self):
        f=feed([(SL_TITLE,'https://other.example/'+SL_URL.split('/')[-2]+'/',DAY),
                (SL_TITLE,SL_URL+'?utm_source=abc',DAY),
                (SL_TITLE,'http://sanluislaciudad.gob.ar/some-long-news-title-about-water/',DAY),
                (SL_TITLE,SL_URL,DAY)])
        entries,count=w._municipal_rss_index(f,SL)
        self.assertEqual(count,4)
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0][0],SL_URL)

    def test_invalid_feed_is_unverified(self):
        for feedtext in ('not xml','<rss><channel></channel></rss>','<!DOCTYPE rss><rss/>'):
            with self.subTest(feedtext=feedtext):
                r=w.collect_one(SL,STAMP,fetcher=lambda _:feedtext)
                self.assertEqual(r['status'],'unverified')
                self.assertFalse(r['notices'])

    def test_old_and_future_are_not_fetched(self):
        f=feed([(SL_TITLE,SL_URL,OLD), (SL_TITLE,'https://sanluislaciudad.gob.ar/agua-potable-futura-de-san-luis/',FUTURE)])
        r=w.collect_one(SL,STAMP,fetcher=lambda u:f)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['articles_skipped_old'],1)
        self.assertFalse(r['notices'])

    def test_finished_announcements_skipped_before_fetch(self):
        finished='SerBa finalizó la reparación y se restableció el agua en San Luis'
        f=feed([(finished,SL_URL,DAY)])
        r=w.collect_one(SL,STAMP,fetcher=lambda u:f)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['source_attempts'][0]['result'],'restoration_or_finished_title')
        self.assertFalse(r['notices'])

    def test_works_without_impact_no_notice(self):
        body=SL_ARTICLE.replace('registra baja presión', 'mantiene la presión habitual')
        r=w.collect_one(SL,STAMP,fetcher=lambda u:feed([(SL_TITLE,SL_URL,DAY)]) if u.endswith('/feed/') else body)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['source_attempts'][0]['result'],'no_current_or_planned_service_impact')

    def test_mismatched_article_date_rejected(self):
        html=SR_ARTICLE.replace('2026-11-17T10:00:00','2026-10-17T10:00:00')
        r=w.collect_one(SR,STAMP,fetcher=lambda u:feed([(SR_TITLE,SR_URL,DAY)]) if u.endswith('rss.xml') else html)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_mismatch')

    def test_mismatched_title_rejected(self):
        html=SR_ARTICLE.replace(SR_TITLE,'Una reunión de trabajadores del municipio por un parque nuevo')
        r=w.collect_one(SR,STAMP,fetcher=lambda u:feed([(SR_TITLE,SR_URL,DAY)]) if u.endswith('rss.xml') else html)
        self.assertEqual(r['source_attempts'][0]['result'],'rss_article_title_mismatch')

    def test_unrelated_article_does_not_trigger_notice(self):
        unrelated='La Municipalidad inauguró una nueva plaza en la ciudad'
        f=feed([(unrelated,SR_URL,DAY)])
        r=w.collect_one(SR,STAMP,fetcher=lambda u:f)
        self.assertEqual(r['relevant_titles_seen'],0)
        self.assertEqual(r['articles_checked'],0)

    def test_limited_to_three_article_requests(self):
        items=[]
        for i in range(7):
            items.append((SL_TITLE, SL_URL[:-1]+str(i)+'/', DAY))
        f=feed(items)
        r=w.collect_one(SL,STAMP,fetcher=lambda u:f if u.endswith('/feed/') else SL_ARTICLE)
        self.assertEqual(r['article_links_seen'],7)
        self.assertEqual(r['articles_checked'],3)

    def test_rss_only_failed_doesnt_break_other_sources(self):
        def f(u):
            if u==w.SOURCES[SL][2]:return feed([(SL_TITLE,SL_URL,DAY)])
            if u==SL_URL:return SL_ARTICLE
            raise RuntimeError('offline')
        all_sources=w.collect_water(STAMP,fetcher=f)
        self.assertGreaterEqual(len(all_sources['sources']),21)
        self.assertEqual(len(all_sources['notices']),1)
        self.assertFalse(all_sources['notifications_enabled'])
        self.assertFalse(all_sources['android_display_enabled'])
        self.assertFalse(all_sources['notices'][0]['notification_allowed'])

if __name__=='__main__':unittest.main()

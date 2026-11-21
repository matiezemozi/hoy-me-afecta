"""v5.67: protect article publication dates on numeric Aguas de Corrientes URLs.

Offline contract tests. No live outage inference, account lookup or push.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T18:32:31Z'
INDEX='https://www.aguasdecorrientes.com/noticias'
ARTICLE='https://www.aguasdecorrientes.com/5470'
TITLE='Corte programado del suministro de agua en Goya'
PARA='Se registrara baja presion en el suministro de agua potable en Goya durante los trabajos.'

def index_html():
    return '<html><a href="/5470">'+TITLE+'</a></html>'

def article_html(before='',after='',body=PARA,meta=''):
    return '<html>'+meta+before+'<h1>'+TITLE+'</h1>'+after+'<p>'+body+'</p></html>'

def collect(article):
    return w.collect_one('aguas_corrientes_prestador',NOW,
                         lambda u:index_html() if u==INDEX else article)

class TestWaterV567(unittest.TestCase):
    def test_explicit_numeric_published_day_after_heading(self):
        r=collect(article_html(after='<div>Publicado el 21/11/2026</div>'))
        self.assertEqual(r['parser_revision'],'ADC-HEADING-PUBLISHED-DATE-v5.67')
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-21')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_explicit_numeric_date_with_dash_before_heading(self):
        r=collect(article_html(before='<div>Fecha de publicación: 20-11-2026</div>'))
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-20')

    def test_numeric_event_date_is_not_publication_date(self):
        r=collect(article_html(after='<div>Trabajos: 22/11/2026</div>'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')
        self.assertEqual(r['source_attempts'][0]['publication_date_check'],
                         'no_explicit_date_in_article_metadata_or_heading')

    def test_old_explicit_published_date_rejected(self):
        r=collect(article_html(after='<div>Publicado el 10/11/2026</div>'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'outside_publication_window')

    def test_future_explicit_published_date_rejected(self):
        r=collect(article_html(after='<div>Publicado el 24/11/2026</div>'))
        self.assertEqual(r['notices'],[])

    def test_invalid_calendar_day_not_accepted(self):
        r=collect(article_html(after='<div>Publicado el 32/11/2026</div>'))
        self.assertEqual(r['notices'],[])

    def test_unlabelled_dd_mm_yyyy_is_not_accepted(self):
        r=collect(article_html(after='<div>21/11/2026</div>'))
        self.assertEqual(r['notices'],[])

    def test_labelled_full_month_publication_is_supported(self):
        r=collect(article_html(after='<div>Publicado el 21 de noviembre de 2026</div>'))
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-21')

    def test_unlabelled_full_month_work_date_is_not_publication(self):
        r=collect(article_html(after='<p>Se realizaran reparaciones el 21 de noviembre de 2026.</p>'))
        self.assertEqual(r['notices'],[])

    def test_metadata_date_remains_supported(self):
        r=collect(article_html(meta='<meta property="article:published_time" content="2026-11-21T09:00:00-03:00">'))
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-21')

    def test_no_date_does_not_infer_from_numeric_url(self):
        r=collect(article_html())
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])

    def test_date_only_does_not_override_negated_impact(self):
        r=collect(article_html(after='<div>Publicado el 21/11/2026</div>',
                               body='No se afectara el servicio de agua potable.'))
        self.assertEqual(r['notices'],[])

    def test_publication_day_is_not_a_scheduled_or_live_cut(self):
        r=collect(article_html(after='<div>Publicado el 21/11/2026</div>'))
        n=r['notices'][0]
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])

    def test_global_safety_flags_and_existing_24_sources(self):
        r=w.collect_water(NOW,lambda _: '<html></html>')
        self.assertEqual(len(r['sources']),24)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(all(not x['notification_allowed'] for x in r['notices']))

if __name__=='__main__':unittest.main()

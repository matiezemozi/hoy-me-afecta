"""v5.84: robust repeated official news headings; no cross-story evidence."""
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW = w.checked_instant('2026-11-24T22:11:14Z')
INDEX = w.SOURCES['agua_potable_jujuy_prensa'][2]
URL = ('https://prensa.jujuy.gob.ar/agua-potable/'
       'agua-potable-informa-corte-emergencia-y-puesta-marcha-obra-definitiva-alto-comedero-y-los-alisos-n126093')
TITLE = 'Agua Potable informa corte de emergencia y puesta en marcha de obra definitiva en Alto Comedero y Los Alisos'
IMPACT = ('Agua Potable de Jujuy S.E. informa que un corte de emergencia '
          'del suministro de agua potable afectara sectores de Alto Comedero '
          'y Los Alisos por reparaciones en el acueducto principal.')
NO_IMPACT = ('Agua Potable de Jujuy S.E. informa que las obras en la red de agua '
             'potable de Alto Comedero y Los Alisos no interrumpiran el suministro.')
META = '<meta property="article:published_time" content="2026-11-24T12:45:00-03:00">'
DATE = '24 de noviembre de 2026 - 12:45'


def html_doc(*, first_text='Panel de Ministerios, tramites y servicios.',
             body=IMPACT, meta=META, date=DATE, first_date=False,
             appendix='', title=TITLE):
    date_first = '<div>'+DATE+'</div>' if first_date else ''
    return ('<html><head>'+meta+'</head><body>'
            '<header><h2>'+title+'</h2>'+date_first+
            '<div>'+first_text+'</div></header>'
            '<main><article><h1>'+title+'</h1><div>'+date+'</div>'
            '<p>'+body+'</p></article></main>'
            '<aside><h2>Las mas leidas</h2>'+appendix+'</aside>'
            '</body></html>')


class TestJujuyRepeatedArticleTitleV584(unittest.TestCase):
    def check_article(self,html):
        return w._jujuy_article(html,URL,NOW,TITLE)

    def test_two_matching_article_headings_select_body_not_header(self):
        notice, pub, verdict = self.check_article(html_doc())
        self.assertEqual(verdict,'parsed')
        self.assertEqual(pub,date(2026,11,24))
        self.assertEqual(notice['locality_hint'],'Alto Comedero / Los Alisos')
        self.assertFalse(notice['notification_allowed'])
        self.assertEqual(notice['status'],'publication_only_not_live')

    def test_first_title_and_date_in_navigation_cannot_steal_article(self):
        html=html_doc(first_date=True)
        n,p,result=self.check_article(html)
        self.assertEqual(result,'parsed')
        self.assertTrue(n and p)
        self.assertIn('acueducto',n['zone_detail'])
        self.assertNotIn('Ministerios',n['zone_detail'])

    def test_second_title_without_date_can_use_matching_official_meta(self):
        n,p,result=self.check_article(html_doc(date='Comunicado del organismo'))
        self.assertEqual(result,'parsed')
        self.assertEqual(p,date(2026,11,24))

    def test_second_article_without_water_impact_cannot_inherit_first_teaser(self):
        first=(IMPACT+' Ministerios y noticias relacionadas.')
        n,p,result=self.check_article(html_doc(first_text=first,body=NO_IMPACT))
        self.assertIsNone(n)
        self.assertNotEqual(result,'parsed')

    def test_website_footer_water_cuts_do_not_become_body(self):
        aside='<p>'+IMPACT+'</p>'
        n,p,result=self.check_article(html_doc(body=NO_IMPACT,appendix=aside))
        self.assertIsNone(n)
        self.assertNotEqual(result,'parsed')

    def test_first_heading_unrelated_stories_do_not_contaminate_article(self):
        n,p,result=self.check_article(html_doc(first_text=(
            'Ultimas noticias de obras y electricidad en el municipio. ')*3))
        self.assertEqual(result,'parsed')
        self.assertNotIn('electricidad',n['zone_detail'])

    def test_second_article_provider_attribution_still_required(self):
        neutral_title='Interrupcion del suministro en Alto Comedero y Los Alisos'
        n,p,result=w._jujuy_article(html_doc(
            body=('Una empresa informa corte total del servicio de agua potable '
                  'en sectores de Alto Comedero y Los Alisos.'),
            title=neutral_title), URL, NOW, neutral_title)
        self.assertIsNone(n)
        self.assertEqual(result,'water_provider_not_attributed')

    def test_publication_conflict_keeps_rejecting(self):
        n,p,result=self.check_article(html_doc(date='25 de noviembre de 2026 - 12:45'))
        self.assertIsNone(n)
        self.assertEqual(result,'publication_date_conflict')

    def test_date_only_inside_paragraph_without_meta_is_not_publication(self):
        n,p,result=self.check_article(html_doc(meta='', date='COMUNICADO',
            body='El 24 de noviembre de 2026, '+IMPACT))
        self.assertIsNone(n)
        self.assertEqual(result,'publication_date_not_verified')

    def test_old_press_article_cannot_be_marked_as_current(self):
        n,p,result=self.check_article(html_doc(
            meta='<meta property="article:published_time" content="2026-09-24T10:00:00-03:00">',
            date='24 de septiembre de 2026 - 10:00'))
        self.assertIsNone(n)
        self.assertEqual(result,'outside_publication_window')

    def test_negative_article_does_not_create_water_notice(self):
        n,p,result=self.check_article(html_doc(body=NO_IMPACT))
        self.assertIsNone(n)
        self.assertNotEqual(result,'parsed')

    def test_rejection_reports_structural_counters_not_article_body(self):
        def fetch(u):
            if u==INDEX:return '<h2><a href="'+URL+'">'+TITLE+'</a></h2>'
            return html_doc(body='El municipio informa obras de veredas y pintura de edificios publicos.',
                            first_text='Ministerios y portal de gobierno.')
        r=w.collect_one('agua_potable_jujuy_prensa','2026-11-24T22:11:14Z',fetcher=fetch)
        a=r['source_attempts'][0]
        self.assertEqual(a['result'],'no_verifiable_water_article_body')
        self.assertEqual(a['repeated_title_occurrences_in_visible'],2)
        self.assertEqual(a['water_context_paragraphs_seen'],0)
        self.assertEqual(a['impact_like_paragraphs_seen'],0)
        self.assertNotIn('article_text',a)
        self.assertNotIn('article_body',a)

    def test_both_titles_in_real_collector_no_extra_requests(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==INDEX:return '<h2><a href="'+URL+'">'+TITLE+'</a></h2>'
            self.assertEqual(url,URL)
            return html_doc()
        r=w.collect_one('agua_potable_jujuy_prensa','2026-11-24T22:11:14Z',fetcher=fetch)
        self.assertEqual(calls,[INDEX,URL])
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['status'],'ok')
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_all_30_sources_read_only_contract_preserved(self):
        self.assertEqual(len(w.SOURCES),30)
        self.assertEqual(w.MAX_PARALLEL_SOURCES,4)
        r=w.collect_water('2026-11-24T22:11:14Z',fetcher=lambda _: '<h1>Sin comunicados</h1>')
        self.assertEqual(len(r['sources']),30)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertEqual(r['notices'],[])


if __name__=='__main__':unittest.main()

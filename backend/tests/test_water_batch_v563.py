"""Offline regression: municipal radio current news and public portal refusal v5.63.

Fixtures are mock public articles, not real service notices.
"""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T13:34:59Z'
PNA_INDEX='https://costa.parana.gob.ar/noticias/'
PNA_OLD='https://costa.parana.gob.ar/category/locales/'
PNA_ART='https://costa.parana.gob.ar/corte-de-suministro-de-agua-en-parana-por-reparaciones/'
TITLE='Corte de suministro de agua en Parana por reparaciones'
ARTICLE=(f'<html><h1>{TITLE}</h1><div>Viernes 20 de noviembre de 2026</div>'
         '<p>La interrupcion del suministro de agua potable afecta a los vecinos '
         'de la zona sur de Parana a causa de reparaciones de canerias municipales.</p></html>')

def tagged(title=TITLE,day='20/11/2026',url=PNA_ART):
    return f'<a href="{url}">{day} | Locales | (1) {title}</a>'

class PublicOfficialNews563(unittest.TestCase):
    def test_23_sources_and_pilot_no_notifications(self):
        self.assertEqual(len(w.SOURCES),23)
        self.assertEqual(w.SOURCES['parana_radio_municipal_agua'][2],PNA_INDEX)
        for key in ('parana_radio_municipal_agua','aosc_corrientes_regulador'):
            r=w.collect_one(key,NOW,lambda _:'<html></html>')
            self.assertFalse(r['notifications_enabled'])
            self.assertFalse(r['notices'])

    def test_parana_realistic_dated_index_prefix_matches_h1(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return '<html>'+tagged()+'</html>' if url==PNA_INDEX else ARTICLE
        r=w.collect_one('parana_radio_municipal_agua',NOW,fetch)
        self.assertEqual(r['parser_revision'],'PUBLIC-OFFICIAL-NEWS-v5.63')
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-20')
        self.assertEqual(r['index_mode'],'current_news_index')
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(calls,[PNA_INDEX,PNA_ART])
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_older_water_headline_is_not_fetched(self):
        def fetch(url):
            self.assertEqual(url,PNA_INDEX)
            return '<html>'+tagged(day='09/10/2026')+'</html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,fetch)
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['older_headlines_skipped'],1)
        self.assertEqual(r['index_status'],'no_recent_water_headlines')
        self.assertEqual(r['status'],'unverified')

    def test_flood_articles_do_not_turn_into_water_outages(self):
        html='<html>'+tagged('El rio Parana sigue creciendo e inunda viviendas')+'</html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,lambda u:html)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['valid_article_links_seen'],1)
        self.assertEqual(r['relevant_titles_seen'],0)
        self.assertEqual(r['articles_checked'],0)

    def test_fresh_and_old_headlines_select_only_fresh(self):
        html='<html>'+tagged(day='20/11/2026')+tagged(day='09/10/2026',
              url='https://costa.parana.gob.ar/corte-agua-en-barrios-viejo-septiembre/')+'</html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:html if u==PNA_INDEX else ARTICLE)
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['older_headlines_skipped'],1)
        self.assertEqual(len(r['notices']),1)

    def test_future_dated_listing_not_fetched(self):
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:'<html>'+tagged(day='25/11/2026')+'</html>')
        self.assertEqual(r['future_headlines_skipped'],1)
        self.assertEqual(r['articles_checked'],0)

    def test_undated_headline_requires_article_date(self):
        html='<html><a href="'+PNA_ART+'">'+TITLE+'</a></html>'
        art='<html><h1>'+TITLE+'</h1><p>La interrupcion del suministro de agua potable afecta la zona sur de Parana.</p></html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:html if u==PNA_INDEX else art)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_news_index_network_failure_falls_back_once_to_same_domain_archive(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==PNA_INDEX:raise URLError('temporary connection failure')
            if url==PNA_OLD:return '<html>'+tagged(day='21/11/2026')+'</html>'
            if url==PNA_ART:return ARTICLE
            raise AssertionError(url)
        r=w.collect_one('parana_radio_municipal_agua',NOW,fetch)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['index_mode'],'official_category_fallback')
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(calls,[PNA_INDEX,PNA_OLD,PNA_ART])

    def test_explicit_403_does_not_retry_other_parana_index(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one('parana_radio_municipal_agua',NOW,fetch)
        self.assertEqual(calls,[PNA_INDEX])
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['http_status'],403)
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['access_mode'],'official_site_rejected_automated_request')

    def test_aosc_403_has_explicit_diagnostics_and_no_retry(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one('aosc_corrientes_regulador',NOW,fetch)
        self.assertEqual(calls,['https://aosc.gob.ar/noticias'])
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertIn('rechaz',r['message'])
        self.assertFalse(r['notices'])

    def test_third_party_or_http_url_is_never_fetched(self):
        html='<html>'+tagged(url='https://other.example/corte-de-suministro-de-agua-en-parana/')
        html+=tagged(url='http://costa.parana.gob.ar/corte-de-suministro-de-agua-en-parana/')+'</html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,lambda u:html)
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['articles_checked'],0)

    def test_negative_article_body_rejected_even_with_dated_title(self):
        article='<html><h1>'+TITLE+'</h1><div>20 de noviembre de 2026</div>'
        article+='<p>No se interrumpira el suministro de agua potable durante los trabajos.</p></html>'
        r=w.collect_one('parana_radio_municipal_agua',NOW,
                        lambda u:'<html>'+tagged()+'</html>' if u==PNA_INDEX else article)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['articles_checked'],1)

if __name__=='__main__':unittest.main()

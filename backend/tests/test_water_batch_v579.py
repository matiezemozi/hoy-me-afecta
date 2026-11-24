"""v5.79: Santa Rosa official news fallback after blocked municipal RSS."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-23T23:59:00Z'
KEY='santa_rosa_municipal_lp'
ROOT='https://www.santarosa.gob.ar/'
NEWS=ROOT+'noticias/'
URL=NEWS+'santa-rosa-se-registra-baja-presion-de-agua-potable-en-barrio-villa-parque'
ROAD=NEWS+'santa-rosa-por-reparacion-red-de-agua-corte-total-de-transito-yapeyu'
TITLE='Santa Rosa: se registra baja presion de agua potable en barrio Villa Parque'
ROAD_TITLE='Santa Rosa: por reparacion de la red de agua habra corte total de transito en Yapeyu'
IMPACT='La Municipalidad de Santa Rosa informa que se registra baja presion de agua potable en barrio Villa Parque por una averia en el acueducto.'
ROAD_BODY=('La Municipalidad de Santa Rosa informa un corte total de transito en la calle Yapeyu. '
           'Las cuadrillas realizan trabajos de reparacion de una perdida en la red de agua potable. '
           'El corte de transito estara vigente de 8 a 15 horas y se ruega circular por otras calles.')


def html_index(extra=''):
    return ('<html><body><h1>Noticias de Santa Rosa</h1>'
            '<article><a href="/noticias/santa-rosa-por-reparacion-red-de-agua-corte-total-de-transito-yapeyu">'+ROAD_TITLE+'</a></article>'
            '<article><a href="/noticias/santa-rosa-se-registra-baja-presion-de-agua-potable-en-barrio-villa-parque">'+TITLE+'</a></article>'
            +extra+'</body></html>')


def article(title=TITLE,body=IMPACT,day='23 de noviembre de 2026',header=True,extra=''):
    pub=('Noticias '+day+' ') if header else 'Noticias '
    return '<html><head><title>'+title+'</title></head><body><div>'+pub+'</div><h1>'+title+'</h1><p>'+body+'</p>'+extra+'</body></html>'


def blocked(url):
    if url.endswith('/rss.xml'):
        raise HTTPError(url,403,'Forbidden',{},None)
    return html_index() if url==NEWS else article(ROAD_TITLE,ROAD_BODY) if url==ROAD else article() if url==URL else ''


class SantaRosaFallbackV579(unittest.TestCase):
    def test_source_count_remains_thirty(self):
        self.assertEqual(len(w.SOURCES),30)

    def test_only_same_site_canonical_story_routes(self):
        tests='''<a href="https://evil.com/noticias/noticia-falsa-corte-de-agua">Falsa</a>
        <a href="https://www.santarosa.gob.ar@evil.com/noticias/agua-corte-real-falso">Falsa</a>
        <a href="http://www.santarosa.gob.ar/noticias/agua-corte-inseguro">HTTP</a>
        <a href="//other.example/noticias/agua-corte-inseguro">Otro</a>
        <a href="/noticias/../admin">Traversal</a>
        <a href="/noticias/corte-agua-potable-validado?secret=1">Query</a>
        <a href="/noticias/corte-agua-potable-validado#detalle">Fragment</a>
        <a href="/noticias/corte-agua-potable-validado">Validado</a>'''
        links,_=w._santa_rosa_public_links(tests,ROOT)
        self.assertEqual(len(links),1)
        self.assertEqual(links[0][0],NEWS+'corte-agua-potable-validado')

    def test_invalid_port_in_one_anchor_does_not_abort_index(self):
        html='<a href="https://www.santarosa.gob.ar:abc/noticias/corte-agua-potable-validado">Bad</a>'+html_index()
        links,_=w._santa_rosa_public_links(html,ROOT)
        self.assertEqual(len(links),2)

    def test_duplicate_cards_only_one_article(self):
        links,_=w._santa_rosa_public_links(html_index('<a href="'+URL+'">'+TITLE+'</a>'),ROOT)
        self.assertEqual(len(links),2)

    def test_header_publication_day_from_official_title(self):
        self.assertEqual(w._santa_rosa_publication_day(article()).isoformat(),'2026-11-23')

    def test_event_body_date_is_not_publication(self):
        a=article(day=' ',header=False,body=IMPACT+' El trabajo sera 23 de noviembre de 2026.')
        self.assertIsNone(w._santa_rosa_publication_day(a))

    def test_metadata_valid_publication_without_header(self):
        a=article(header=False,day=' ',extra='')
        a=a.replace('</head>','<meta property="article:published_time" content="2026-11-23T14:03:00-03:00" /></head>')
        self.assertEqual(w._santa_rosa_publication_day(a).isoformat(),'2026-11-23')

    def test_conflicting_metadata_and_header_rejected(self):
        a=article()
        a=a.replace('</head>','<meta property="article:published_time" content="2026-11-02" /></head>')
        self.assertIsNone(w._santa_rosa_publication_day(a))

    def test_blocked_rss_html_fallback_extracts_only_real_service_impact(self):
        r=w.collect_one(KEY,NOW,blocked)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['index_mode'],'official_html_news_fallback')
        self.assertEqual(r['index_status'],'official_html_article_links_found')
        self.assertEqual(r['source_url'],NEWS)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-23')
        self.assertIsNone(r['notices'][0]['scheduled_start'])
        self.assertIsNone(r['notices'][0]['scheduled_end'])
        self.assertFalse(r['notices'][0]['notification_allowed'])
        self.assertEqual(r['articles_checked'],2)
        self.assertTrue(any('transito' in x['url'] and x['result']!='parsed' for x in r['source_attempts']))

    def test_road_closure_alone_not_water_outage(self):
        r=w.collect_one(KEY,NOW,lambda url: html_index() if url==NEWS else article(ROAD_TITLE,ROAD_BODY) if url==ROAD else article(TITLE,'Se amplia la red de agua potable en la ciudad.') if url==URL else blocked(url))
        self.assertEqual(r['notices'],[])

    def test_old_articles_not_promoted(self):
        def fetch(url):
            if url==NEWS:return html_index()
            if url in (ROAD,URL):return article(TITLE,IMPACT,'10 de noviembre de 2026')
            return blocked(url)
        r=w.collect_one(KEY,NOW,fetch)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'stale')
        self.assertEqual(r['latest_published_date'],'2026-11-10')

    def test_future_publication_not_promoted(self):
        def fetch(url):
            if url==NEWS:return html_index()
            if url in (ROAD,URL):return article(TITLE,IMPACT,'25 de noviembre de 2026')
            return blocked(url)
        r=w.collect_one(KEY,NOW,fetch)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'unverified')

    def test_index_js_shell_then_public_homepage(self):
        def fetch(url):
            if url==NEWS:return '<html><body><p>Cargando noticias...</p><script>/* JS */</script></body></html>'
            if url==ROOT:return html_index()
            if url in (ROAD,URL):return article(ROAD_TITLE,ROAD_BODY) if url==ROAD else article()
            return blocked(url)
        r=w.collect_one(KEY,NOW,fetch)
        self.assertEqual(r['index_mode'],'official_homepage_sample_fallback')
        self.assertEqual(len(r['notices']),1)

    def test_all_html_fallbacks_fail_stays_unverified(self):
        def fail(url):raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one(KEY,NOW,fail)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(len(r['fallback_index_attempts']),2)

    def test_rss_still_primary_when_available(self):
        rss='<?xml version="1.0"?><rss><channel><item><title>Santa Rosa anuncia actividades para el agua potable</title><link>'+URL+'</link><pubDate>Mon, 23 Nov 2026 13:30:00 -0300</pubDate></item></channel></rss>'
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith('rss.xml'):return rss
            if url==URL:return article()
            raise AssertionError(url)
        r=w.collect_one(KEY,NOW,fetch)
        self.assertEqual(r['index_mode'],'primary_rss')
        self.assertNotIn('fallback_index_attempts',r)
        self.assertFalse(any(url==NEWS for url in calls))

    def test_no_credentials_no_push_and_no_electricity_import(self):
        r=w.collect_one(KEY,NOW,blocked)
        self.assertFalse(r['notifications_enabled'])
        self.assertTrue(all(n['notification_allowed'] is False for n in r['notices']))


if __name__=='__main__':unittest.main()

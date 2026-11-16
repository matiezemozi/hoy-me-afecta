"""v5.52 SAT index route diagnostics and safe public homepage fallback."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-16T21:43:06Z'
INDEX=w.SOURCES['sat_tucuman_noticias'][2]
HOME='https://aguasdeltucuman.com.ar/'
ROUTE='/noticias/Q29ydGUgZGUgYWd1YQ=='
ARTICLE=HOME.rstrip('/')+ROUTE


def article(date='2026-11-16', impact=True):
    body=('Se interrumpirá el suministro de agua potable en San Miguel de Tucumán '
          'debido a una reparación programada de cañerías y afectará únicamente '
          'a los usuarios del sector indicado.' if impact else
          'La SAT completó una campaña educativa sobre uso responsable del agua.')
    return (f'<meta property="article:published_time" content="{date}T11:00:00-03:00">'
            '<h1>Corte de agua informado en San Miguel de Tucumán</h1>'
            f'<p>{body}</p>')


class TestRegionalSat552(unittest.TestCase):
    def test_sat_angular_router_link_no_href(self):
        html=f'<h1>Noticias</h1><button routerLink="{ROUTE}">Leer más</button>'
        result=w._regional_index(html,INDEX,'sat_tucuman_noticias')
        self.assertEqual(result,[(ARTICLE,'',None)])

    def test_sat_javascript_onclick_literal(self):
        html=f'<button onclick="goTo(\'{ROUTE}\')">Abrir</button>'
        self.assertEqual(len(w._regional_index(html,INDEX,'sat_tucuman_noticias')),1)

    def test_sat_serialized_route_escaped(self):
        html='<script>window.__data={"path":"\\/noticias\\/Q29ydGUgZGUgYWd1YQ=="}</script>'
        self.assertEqual(w._sat_embedded_article_routes(html,INDEX),[ARTICLE])

    def test_sat_no_external_rebasing_or_injection(self):
        html=('''<a href="https://evil.example/noticias/Q29ydGUgZGUgYWd1YQ==">Fake</a>'''
              '''<script>const x="https://bad.example/noticias/Q29ydGUgZGUgYWd1YQ=="</script>'''
              '''<a href="http://aguasdeltucuman.com.ar/noticias/Q29ydGUgZGUgYWd1YQ==">HTTP</a>''')
        self.assertEqual(w._regional_index(html,INDEX,'sat_tucuman_noticias'),[])

    def test_sat_index_fallback_homepage_finds_news(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==INDEX:return '<h1>Noticias</h1><p>Noticias y novedades</p>'
            if url==HOME:return f'<div data-href="{ROUTE}">Comunicados</div>'
            if url==ARTICLE:return article()
            raise AssertionError(url)
        result=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=fetch)
        self.assertEqual(result['parser_revision'],'SAT-ROUTE-DIAGNOSTIC-v5.52')
        self.assertEqual(result['index_mode'],'homepage_fallback')
        self.assertEqual(result['article_links_seen'],1)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['notices'][0]['locality_hint'],'San Miguel de Tucumán')
        self.assertFalse(result['notices'][0]['notification_allowed'])
        self.assertEqual(calls,[INDEX,HOME,ARTICLE])

    def test_sat_empty_both_pages_is_unverified_with_diagnostics(self):
        result=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda _: '<h1>Noticias</h1>')
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['article_links_seen'],0)
        self.assertEqual(result['articles_checked'],0)
        self.assertEqual(len(result['index_attempts']),2)
        self.assertIn('no expone rutas',result['index_warning'])
        self.assertEqual(result['notices'],[])

    def test_sat_fallback_fetch_error_keeps_initial_diagnostics(self):
        def fetch(url):
            if url==INDEX:return '<h1>Noticias</h1>'
            raise OSError('site unavailable')
        result=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['index_attempts'][1]['error_type'],'OSError')
        self.assertEqual(result['notices'],[])

    def test_sat_no_date_never_makes_alert(self):
        def fetch(url):
            if url==INDEX:return f'<span data-href="{ROUTE}">Leer más</span>'
            if url==ARTICLE:return '<h1>Corte de agua en San Miguel de Tucumán</h1><p>Se interrumpirá el suministro de agua potable en San Miguel de Tucumán por trabajos.</p>'
            raise AssertionError(url)
        result=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=fetch)
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_duplicate_route_and_anchor_is_one(self):
        html=(f'<a href="{ROUTE}">Interrupción</a>'
              f'<script>const p="{ROUTE}"</script>')
        entries=w._regional_index(html,INDEX,'sat_tucuman_noticias')
        self.assertEqual(len(entries),1)

    def test_other_provider_original_routes_unchanged(self):
        santiago='https://aguasdesantiago.com.ar/nota/39/interrupcion-temporal-en-la-banda'
        html=f'<a href="{santiago}">La Banda: corte programado</a>'
        entries=w._regional_index(html,w.SOURCES['aguas_santiago_novedades'][2],'aguas_santiago_novedades')
        self.assertEqual(len(entries),1)

if __name__=='__main__':unittest.main()

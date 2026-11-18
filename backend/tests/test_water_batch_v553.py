"""v5.53: conservative diagnostics and official fallbacks for failed indexes.

Offline fixtures only: no real endpoint access, notifications stay disabled.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-16T23:11:26Z'
ARSA=w.SOURCES['aguas_rionegrinas_arsa'][2]
ARSA_HOME='https://aguasrionegrinas.com/'
EPAS=w.SOURCES['epas_neuquen_noticias'][2]
EPAS_ALT='https://www.epas.gov.ar/category/noticias/'
SAT=w.SOURCES['sat_tucuman_noticias'][2]
SAT_HOME='https://aguasdeltucuman.com.ar/'
ARSA_ART='https://aguasrionegrinas.com/bariloche-arsa-problemas-por-turbiedad-en-la-planta-pilar/'
EPAS_ART='https://www.epas.gov.ar/2026/11/16/chos-malal-corte-temporal-de-agua/'

ARSA_ARTICLE=('<meta property="article:published_time" content="2026-11-16T11:10:00-03:00">'
 '<h1>Bariloche: interrupción del servicio de agua potable en barrio Pilar</h1>'
 '<p>La empresa Aguas Rionegrinas informa que por un inconveniente en el sistema de bombeo '
 'el suministro de agua potable presenta baja presión en barrio Pilar, de la ciudad '
 'de Bariloche, desde esta mañana.</p>')

EPAS_ARTICLE=('<meta property="article:published_time" content="2026-11-16T09:10:00-03:00">'
 '<h1>Chos Malal: interrupción temporal del servicio de agua potable</h1>'
 '<p>Este lunes se interrumpirá el suministro de agua potable en Chos Malal '
 'por mantenimiento de una cisterna. Los sectores afectados se enumeran en '
 'el comunicado oficial del EPAS.</p>')

class TestRegionalFallbacks553(unittest.TestCase):
    def test_arsa_official_homepage_fallback_and_partial(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==ARSA: return '<h1>Interrupciones</h1><div>Sin listado de hoy</div>'
            if url==ARSA_HOME: return (f'<a href="{ARSA_ART}">Bariloche: ARSA comunica interrupción del servicio de agua potable</a>'
                                       '<p>16 de noviembre de 2026</p>')
            if url==ARSA_ART: return ARSA_ARTICLE
            raise AssertionError(url)
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(calls,[ARSA,ARSA_HOME,ARSA_ART])
        self.assertEqual(r['index_mode'],'homepage_fallback')
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['article_fetch_completeness'],'partial')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_arsa_two_empty_indexes_are_not_a_success(self):
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=lambda u:'<h1>Noticias</h1>')
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['article_fetch_completeness'],'unverified')
        self.assertEqual(len(r['index_attempts']),2)
        self.assertTrue(r['index_warning'])
        self.assertFalse(r['notices'])

    def test_arsa_primary_error_does_not_break_result(self):
        def fetch(url): raise OSError('HTTP problem')
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['article_fetch_completeness'],'unverified')
        self.assertEqual(r['source_attempts'][0]['error_type'],'OSError')
        self.assertFalse(r['notices'])

    def test_arsa_fallback_does_not_fetch_unofficial_or_undated_nonwater_links(self):
        called=[]
        def fetch(url):
            called.append(url)
            if url==ARSA:return '<h2>Interrupciones</h2>'
            if url==ARSA_HOME:return ('<a href="https://other.example/bariloche-corte-de-agua">Bariloche: corte de agua en la ciudad</a>'
                 '<a href="/bariloche-visita-a-la-plaza-central-con-los-vecinos/">Bariloche: visita institucional con vecinos</a>')
            raise AssertionError('Should not fetch article')
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(called,[ARSA,ARSA_HOME])
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['notices'],[])

    def test_epas_alternate_official_index(self):
        called=[]
        def fetch(url):
            called.append(url)
            if url==EPAS:return '<h1>Novedades</h1>'
            if url==EPAS_ALT:return (f'<h3><a href="{EPAS_ART}">Chos Malal: interrupcion temporal del servicio de agua potable</a></h3>'
                                    '<p>16 noviembre, 2026</p>')
            if url==EPAS_ART:return EPAS_ARTICLE
            raise AssertionError(url)
        r=w.collect_one('epas_neuquen_noticias',STAMP,fetcher=fetch)
        self.assertEqual(called,[EPAS,EPAS_ALT,EPAS_ART])
        self.assertEqual(r['parser_revision'],'EPAS-INDEX-FALLBACK-v5.53')
        self.assertEqual(r['index_mode'],'official_category_fallback')
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(len(r['notices']),1)
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_epas_two_empty_indexes_have_warning(self):
        r=w.collect_one('epas_neuquen_noticias',STAMP,fetcher=lambda u:'<h1>Novedades</h1>')
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['articles_checked'],0)
        self.assertTrue(r['index_warning'])
        self.assertEqual(r['notices'],[])

    def test_epas_does_not_fetch_from_external_host(self):
        def fetch(url):
            if url==EPAS:return '<h1>Novedades</h1>'
            if url==EPAS_ALT:
                return '<a href="https://other.example/2026/11/16/chos-malal-corte-agua/">Chos Malal: corte temporal de agua potable</a>'
            raise AssertionError(url)
        r=w.collect_one('epas_neuquen_noticias',STAMP,fetcher=fetch)
        self.assertEqual(r['article_links_seen'],0)
        self.assertFalse(r['notices'])

    def test_sat_identifies_small_javascript_shell_as_unverified(self):
        shell=('<html><head><script src="/assets/index.js"></script></head>'
               '<body><div id="app">Cargando los servicios de noticias</div></body></html>')
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:shell)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['access_mode'],'client_rendered_shell_suspected')
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['notices'],[])
        self.assertIn('JavaScript',r['index_warning'])
        self.assertEqual(len(r['index_attempts']),2)

    def test_sat_larger_html_needs_manual_diagnostic_not_false_shell(self):
        html='<h1>Noticias</h1><p>'+('Noticias institucionales. '*100)+'</p>'
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:html)
        self.assertNotIn('access_mode',r)
        self.assertIn('no expone rutas',r['index_warning'])

    def test_all_18_sources_and_notifications_remain_unchanged(self):
        self.assertGreaterEqual(len(w.SOURCES),18)
        r=w.collect_water(STAMP,fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertGreaterEqual(len(r['sources']),18)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(r['android_read_only_pilot_available'])
        self.assertEqual(r['notices'],[])

if __name__=='__main__':unittest.main()

"""Regression tests for ARSA category/metadata/date consistency & AYSAM fallback."""
import unittest
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
from test_water_batch_v533 import STAMP,NOW,BELISLE,BARILOCHE,CIPOLLETTI

URL='https://aguasrionegrinas.com/coronel-belisle-arsa-realizara-trabajos-para-fortalecer-el-sistema-de-abastecimiento-de-agua/'
LABEL='Coronel Belisle: ARSA realizará trabajos para fortalecer el sistema de abastecimiento de agua'
INDEX=f'''<html><body><div class="article-card"><span>11 noviembre, 2026</span><h4><a href="{URL}">{LABEL}</a></h4></div></body></html>'''

class FixTests(unittest.TestCase):
    def test_date_near_label(self):
        self.assertEqual(w._arsa_index_date(w.page(INDEX)[1],LABEL),date(2026,11,11))

    def test_index_date_ignores_other_entry(self):
        raw=f'<p>11 noviembre, 2026</p><h3>Bariloche: otra noticia</h3><a href="{URL}">{LABEL}</a>'
        self.assertIsNone(w._arsa_index_date(w.page(raw)[1],LABEL))

    def test_old_index_date_makes_article_stale(self):
        raw=INDEX.replace('11 noviembre, 2026','10 octubre, 2026')
        self.assertEqual(w._arsa_index_date(w.page(raw)[1],LABEL),date(2026,10,10))

    def test_date_embedded_time_tag(self):
        html=BELISLE.replace('11 noviembre, 2026','<time datetime="2026-11-11T11:00:00-03:00">Hoy</time>')
        n,d=w._arsa_article(html,URL,NOW)
        self.assertEqual(d,date(2026,11,11))
        self.assertEqual(len(n),1)

    def test_date_embedded_article_meta(self):
        html=BELISLE.replace('11 noviembre, 2026','<meta property="article:published_time" content="2026-11-11T11:00:00-03:00">')
        n,d=w._arsa_article(html,URL,NOW)
        self.assertEqual(len(n),1)

    def test_date_embedded_jsonld(self):
        html=BELISLE.replace('11 noviembre, 2026','<script type="application/ld+json">{"datePublished":"2026-11-11T10:00:00-03:00"}</script>')
        n,d=w._arsa_article(html,URL,NOW)
        self.assertEqual(len(n),1)

    def test_article_date_provided_by_matching_category(self):
        html=BELISLE.replace('11 noviembre, 2026','')
        n,d=w._arsa_article(html,URL,NOW,index_published=date(2026,11,11))
        self.assertEqual(len(n),1)
        self.assertEqual(d,date(2026,11,11))

    def test_conflicting_article_category_dates_rejected(self):
        n,d=w._arsa_article(BELISLE,URL,NOW,index_published=date(2026,11,10))
        self.assertEqual(n,[])
        self.assertIsNone(d)

    def test_no_category_date_no_article_date_rejected(self):
        n,d=w._arsa_article(BELISLE.replace('11 noviembre, 2026',''),URL,NOW)
        self.assertEqual(n,[])
        self.assertIsNone(d)

    def test_article_repeated_title_before_heading(self):
        html=f'<p>Noticia relacionada: {LABEL} será publicada</p>'+BELISLE
        n,d=w._arsa_article(html,URL,NOW)
        self.assertEqual(len(n),1)

    def test_arsa_index_category_fallback_end_to_end(self):
        html=BELISLE.replace('11 noviembre, 2026','')
        def fetch(url):
            return INDEX if url==w.SOURCES['aguas_rionegrinas_arsa'][2] else html
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(result['source_attempts'][0]['category_published_on'],'2026-11-11')

    def test_office_no_future_alert_even_with_category_date(self):
        html='<h1>Cinco Saltos: la oficina de ARSA permanecerá cerrada</h1><p>El servicio de agua potable se presta con normalidad. Se cierra la oficina de atención al público.</p>'
        n,_=w._arsa_article(html,'https://aguasrionegrinas.com/cinco-saltos-la-oficina/',NOW,index_published=date(2026,11,11))
        self.assertEqual(n,[])

    def test_aysam_empty_explicit_on_legacy_link(self):
        def fetch(url):
            if url=='https://aysam.com.ar/cortes/':raise ConnectionError()
            return '<h1>Cortes de servicio</h1><div>No hay cortes</div>'
        result=w.collect_one('aysam_mendoza',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['notices'],[])
        self.assertIn('No hay cortes',result['message'])

if __name__=='__main__':unittest.main()

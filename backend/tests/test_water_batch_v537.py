"""v5.37: bounded rate-limit handling and independent water merge safety."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
import build_water_feed as merge

STAMP='2026-11-14T02:33:20Z'
BASE=w.SOURCES['aguas_rionegrinas_arsa'][2]
ONE='https://aguasrionegrinas.com/el-bolson-arsa-trabaja-para-recuperar-los-niveles-de-cisterna-y-normalizar-el-servicio-en-barrio-buena-vista/'
TWO='https://aguasrionegrinas.com/playas-doradas-arsa-y-dpa-trabajan-en-el-acueducto-los-berros-para-restablecer-la-presion/'
THREE='https://aguasrionegrinas.com/el-condor-arsa-realizo-un-operativo-nocturno-de-limpieza-de-cisterna-para-fortalecer-el-abastecimiento-de-agua-de-cara-al-verano/'
LABEL_ONE='El Bolsón: ARSA trabaja para recuperar los niveles de cisterna y normalizar el servicio en barrio Buena Vista'
LABEL_TWO='Playas Doradas: ARSA y DPA trabajan en el acueducto Los Berros para restablecer la presión'
LABEL_THREE='El Cóndor: ARSA realizó un operativo nocturno de limpieza de cisterna para fortalecer el abastecimiento de agua de cara al verano'
INDEX='<html><body>'+''.join('<div>13 noviembre, 2026 <a href="{}">{}</a></div>'.format(u,l) for u,l in [(ONE,LABEL_ONE),(TWO,LABEL_TWO),(THREE,LABEL_THREE)])+'</body></html>'
BOLSON=('<html><h1>'+LABEL_ONE+'</h1>13 noviembre, 2026'
        '<p>Aguas Rionegrinas informa que este viernes 13 de noviembre se dio inicio una intervención técnica sobre el sistema de bombeo y cisterna para recuperar niveles de reserva.</p>'
        '<p>La medida afecta a los barrios Buena Vista 1 y Buena Vista 2.</p></html>')


def err(url,code):
    return HTTPError(url,code,'HTTP failure',None,None)


class RateLimitTests(unittest.TestCase):
    def test_429_stops_later_pages_but_keeps_one_verified_notice(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return INDEX
            if url==ONE:return BOLSON
            if url==TWO:raise err(url,429)
            raise AssertionError('No se debe consultar tercer articulo tras 429')
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['parser_revision'],'ARSA-ARTICLES-v5.37')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),1)
        self.assertTrue(result['rate_limited'])
        self.assertEqual(result['article_fetch_completeness'],'partial')
        self.assertEqual(result['article_links_skipped_after_rate_limit'],1)
        self.assertEqual(result['source_attempts'][-1]['http_status'],429)
        self.assertEqual(calls.count(TWO),1)
        self.assertNotIn(THREE,calls)
        self.assertIn('PARCIAL',result['message'])
        self.assertFalse(result['notices'][0]['notification_allowed'])

    def test_429_on_first_article_does_not_report_normal_service(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return INDEX
            raise err(url,429)
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['articles_checked'],1)
        self.assertEqual(result['article_links_skipped_after_rate_limit'],2)
        self.assertEqual(len(calls),2)
        self.assertIn('No significa suministro normal',result['message'])

    def test_429_on_category_index_is_diagnosed(self):
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=lambda url: (_ for _ in ()).throw(err(url,429)))
        self.assertEqual(result['status'],'unverified')
        self.assertTrue(result['rate_limited'])
        self.assertEqual(result['article_fetch_completeness'],'partial')
        self.assertEqual(result['source_attempts'][0]['http_status'],429)
        self.assertIn('límite HTTP 429',result['message'])

    def test_503_gets_one_retry_and_can_recover(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return INDEX
            if url==ONE and calls.count(ONE)==1:raise err(url,503)
            if url==ONE:return BOLSON
            if url==TWO or url==THREE:raise err(url,404)
            raise AssertionError(url)
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(calls.count(ONE),2)
        self.assertTrue(result['source_attempts'][0]['transient_http_retry_succeeded'])
        self.assertEqual(result['status'],'ok')
        self.assertFalse(result['rate_limited'])
        self.assertEqual(result['article_fetch_completeness'],'partial')
        self.assertIn('Consulta PARCIAL',result['message'])

    def test_404_does_not_stop_subsequent_articles(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return INDEX
            if url==TWO:return BOLSON.replace(LABEL_ONE,LABEL_TWO).replace('Buena Vista 1 y Buena Vista 2','Playas Doradas')
            raise err(url,404)
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(calls.count(ONE),1)
        self.assertEqual(calls.count(THREE),1)
        self.assertFalse(result['rate_limited'])
        self.assertEqual(result['article_links_skipped_after_rate_limit'],0)

    def test_all_articles_read_and_rejected_still_no_live_claim(self):
        def fetch(url):
            if url==BASE:return INDEX
            return '<html><h1>Una noticia sin cortes</h1><p>Muchas noticias de la ciudad sin impacto del agua potable.</p></html>'
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertFalse(r['rate_limited'])
        self.assertEqual(r['article_fetch_completeness'],'selected_articles_checked')
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['status'],'unverified')


class WaterMergeTests(unittest.TestCase):
    def test_merging_water_keeps_power_alerts_and_base_time(self):
        power={'schema_version':1,'generated_at':'2026-11-13T21:00:00Z',
               'alerts':[{'id':'original-event','category':'electricidad'}],
               'sources':{'edenor':{'status':'ok'}},
               'coverage':{'water':'manual_notices_only'},
               'provincial_electricity':{'test':{'status':'ok'}}}
        water={'schema_version':1,'category':'agua','sources':{},'notices':[],
               'notifications_enabled':False,'android_display_enabled':False}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            base=root/'feed.json'; out=root/'water_feed.json'
            base.write_text(json.dumps(power,ensure_ascii=False),encoding='utf-8')
            result=merge.main(['--out',str(out),'--merge',str(base)],collector=lambda checked:water)
            self.assertEqual(result,water)
            final=json.loads(base.read_text(encoding='utf-8'))
            self.assertEqual(final['water_services'],water)
            self.assertEqual(final['generated_at'],power['generated_at'])
            for field in ('alerts','sources','coverage','provincial_electricity'):
                self.assertEqual(final[field],power[field])
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')),water)

    def test_merge_rejects_invalid_power_feed_without_output_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'feed.json';out=root/'water_feed.json'
            base.write_text('{"schema_version":2,"alerts":[]}',encoding='utf-8')
            with self.assertRaises(ValueError):
                merge.main(['--out',str(out),'--merge',str(base)],collector=lambda _: {'category':'agua'})
            self.assertFalse(out.exists())

if __name__=='__main__':unittest.main()

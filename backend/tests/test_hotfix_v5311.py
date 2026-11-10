import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import provincial_outages as p
STAMP='2026-11-10T22:46:29Z'
class TestHotfixUPC(unittest.TestCase):
    def test_official_empty_list_gives_ok_not_outage_free(self):
        text='<main><h3>Cortes programados y avisos</h3><p>No se encontraron cortes programados ni avisos.</p></main>'
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:text)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(r['source_attempts'][0]['result'],'explicit_no_listed_notices')
        self.assertEqual(r['coverage_horizon'],'current_listings_only')
        self.assertEqual(r['notices'],[])
        self.assertIn('No acredita suministro normal',r['message'])
        self.assertEqual(r['parser_revision'],'UPC-NECOCHEA-v5.31.1')
    def test_unknown_blank_page_is_unverified(self):
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:'<main>Próximamente</main>')
        self.assertEqual(r['status'],'unverified')
    def test_generic_no_cuts_without_official_exact_phrase_unverified(self):
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:'<p>No hay noticias</p>')
        self.assertEqual(r['status'],'unverified')
    def test_not_interpret_menu_or_html_attribute_as_message(self):
        raw='<main data-info="No se encontraron cortes programados ni avisos">Actualizando</main>'
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:raw)
        self.assertEqual(r['status'],'unverified')
    def test_future_article_still_verified(self):
        url='https://www.upcnecochea.com.ar/10-11-26-corte-programado-de-servicio-electrico/'
        home=f'<a href="{url}">10/11/26 - corte programado</a>'
        article='<article><h2>corte programado de servicio eléctrico</h2><p>El día 11/11/2026 en el horario de 8 a 11 hs realizará un corte en el suministro de energía eléctrica, zona comprendida entre Av. 42 a calle 66 entre calles 95 y 123.</p></article>'
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:article if u==url else home)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1)

class TestSharedHostCircuitBreaker(unittest.TestCase):
    def test_one_oceba_timeout_skips_other_three_only(self):
        calls=[]
        def simulated(url):
            calls.append(url)
            if url.startswith('https://oceba.gba.gov.ar/'):
                raise TimeoutError('private detail should not appear')
            return '<main>Sin datos verificables</main>'
        with patch.object(p,'fetch_html',side_effect=simulated):
            results=p.collect_provincial(STAMP)
        oceba_calls=[u for u in calls if u.startswith('https://oceba.gba.gov.ar/')]
        self.assertEqual(len(oceba_calls),1)
        for k in p._OCEBA_GROUP:
            self.assertEqual(results[k]['status'],'unverified')
            self.assertFalse(results[k]['notices'])
            self.assertFalse(results[k]['notifications_enabled'])
        for k in ('oceba_edea_outages','oceba_edes_outages','oceba_edelap_outages'):
            self.assertEqual(results[k]['source_attempts'][0]['result'],'skipped_shared_host_failure')
        self.assertIn('www.upcnecochea.com.ar', ' '.join(calls))
        self.assertNotIn('private detail',str(results))
    def test_custom_fetcher_does_not_break_all_sources_after_failure(self):
        calls=[]
        def fail_all(url):
            calls.append(url)
            if 'oceba.gba.gov.ar' in url:raise TimeoutError('custom')
            return '<main>Sin datos</main>'
        r=p.collect_provincial(STAMP,fetcher=fail_all)
        self.assertEqual(len([u for u in calls if 'oceba.gba.gov.ar' in u]),4)
        self.assertEqual(r['oceba_edelap_outages']['source_attempts'][0]['result'],'fetch_or_parse_error')
    def test_bad_oceba_html_does_not_trigger_host_backoff(self):
        calls=[]
        def bad_html(url):
            calls.append(url)
            return '<main>Sin datos completos</main>'
        with patch.object(p,'fetch_html',side_effect=bad_html):
            r=p.collect_provincial(STAMP)
        self.assertEqual(len([u for u in calls if 'oceba.gba.gov.ar' in u]),4)
        self.assertEqual(r['oceba_eden_outages']['status'],'unverified')
if __name__=='__main__':unittest.main()

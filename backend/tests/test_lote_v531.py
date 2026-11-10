import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provincial_outages as p

STAMP='2026-11-10T22:20:00Z'  # 19:20 in Argentina
NOW=p._instant(STAMP)

def oceba_html(provider='EDEN', header='19:10', predicted='2026-11-11 01:30:00', users='27', area='San Nicolas'):
    return f'''<h1>Interrupciones del servicio</h1>
    <p>Informacion brindada por {provider} S.A.</p>
    <p>Ultima actualizacion: {header}</p>
    <h3>Interrupciones Programadas por Mantenimiento y Obras</h3>
    <table><tr><td>Partido de Lujan</td><td>Lujan</td><td>ET NORTE</td><td>2026-11-11 05:15:00</td><td>500</td></tr></table>
    <h3>Interrupciones en el Servicio de Media Tension</h3>
    <table><tr><th>Partido</th><th>Area</th><th>Subestacion</th><th>Hora estimada de normalizacion</th><th>Usuarios afectados</th></tr>
    <tr><td>Partido de San Nicolas</td><td>{area}</td><td>ET Central / Alimentador 8</td><td>{predicted}</td><td>{users}</td></tr></table>
    <h3>Interrupciones en el Servicio de Baja Tension</h3>
    <table><tr><td>Sin datos previstos por la distribuidora</td></tr></table>'''


class TestOCEBA(unittest.TestCase):
    def test_all_four_sources_correct_distributor(self):
        for key,provider in [('oceba_eden_outages','EDEN'),('oceba_edea_outages','EDEA'),
                             ('oceba_edes_outages','EDES'),('oceba_edelap_outages','EDELAP')]:
            with self.subTest(key=key):
                r=p.collect_one(key,STAMP,fetcher=lambda u:oceba_html(provider=provider))
                self.assertEqual(r['status'],'ok',r)
                self.assertEqual(len(r['notices']),1,r)
                self.assertEqual(r['notices'][0]['company'],provider)
                self.assertEqual(r['notices'][0]['users_affected'],27)
                self.assertEqual(r['notices'][0]['voltage_level'],'media')
                self.assertEqual(r['notices'][0]['locality_hint'],'San Nicolas')
                self.assertNotIn('scheduled_start',r['notices'][0])
                self.assertFalse(r['notifications_enabled'])
                self.assertEqual(r['parser_revision'],'OCEBA-REPORT-v5.31')

    def test_old_restoration_rejected(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html(predicted='2026-11-01 06:30:00'))
        self.assertEqual(r['status'],'stale');self.assertFalse(r['notices'])

    def test_old_refresh_clock_rejected_even_if_restoration_future(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html(header='02:30'))
        self.assertEqual(r['status'],'stale');self.assertFalse(r['notices'])

    def test_wrong_distributor_rejected(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html(provider='EDEA'))
        self.assertEqual(r['status'],'unverified');self.assertFalse(r['notices'])

    def test_no_date_empty_cannot_pretend_service_normal(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html(predicted='NO') )
        self.assertEqual(r['status'],'unverified');self.assertFalse(r['notices'])

    def test_reject_bad_user_count(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html(users='NaN'))
        self.assertEqual(r['status'],'unverified');self.assertFalse(r['notices'])

    def test_does_not_count_planned_table_as_current_outage(self):
        r=p.collect_one('oceba_eden_outages',STAMP,fetcher=lambda u:oceba_html())
        self.assertEqual(r['notices'][0]['locality_hint'],'San Nicolas')
        self.assertNotIn('Lujan',str(r['notices']))

    def test_remote_failure_isolated(self):
        def bad(u): raise OSError('private details')
        r=p.collect_one('oceba_edes_outages',STAMP,fetcher=bad)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['source_attempts'][0]['error_type'],'OSError')
        self.assertNotIn('private details',str(r))

    def test_midnight_time_wrap(self):
        at='2026-11-11T02:05:00Z'  # 23:05 Argentina
        s=oceba_html(header='00:10',predicted='2026-11-11 01:30:00')
        r=p.collect_one('oceba_eden_outages',at,fetcher=lambda u:s)
        self.assertEqual(r['status'],'ok',r)

class TestUPC(unittest.TestCase):
    URL='https://www.upcnecochea.com.ar/28-10-26-corte-programado-de-servicio-electrico/'
    def article(self, date='28/10/2026', hours='8 a 11 Hs.', zone='Av. 42 a calle 66 entre calles 95 y 123'):
        return f'''<article><h1>28/10/26 - CORTE PROGRAMADO DE SERVICIO ELECTRICO</h1>
          <p>La Usina Popular Cooperativa comunica que el día {date} en el horario de {hours},
          siempre y cuando las condiciones del tiempo lo permitan, realizará un corte en el suministro
          de energía eléctrica que afectará a los usuarios de la zona comprendida {zone};
          así como también de otras zonas aledañas. El mismo tiene por finalidad las tareas.</p></article>'''

    def test_parses_old_official_bulletin_as_stale(self):
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:self.article() if '28-10-' in u else
             f'<a href="{self.URL}">28/10/26 - CORTE PROGRAMADO DE SERVICIO ELECTRICO</a>')
        self.assertEqual(r['status'],'stale',r)
        self.assertFalse(r['notices'])
        self.assertEqual(r['records_checked'],1)

    def test_future_date_from_dated_article(self):
        url='https://www.upcnecochea.com.ar/10-11-26-corte-programado-de-servicio-electrico/'
        home=f'<a href="{url}">10/11/26 - CORTE PROGRAMADO DE SERVICIO ELECTRICO</a>'
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:self.article(date='11/11/2026') if '10-11-' in u else home)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['scheduled_start'],'2026-11-11T08:00-03:00')
        self.assertIn('calle 66',r['notices'][0]['zone_detail'])

    def test_reject_conflicting_old_article_future_body(self):
        self.assertFalse(p._parse_upc_necochea_v531(self.article(date='30/11/2026'),NOW,self.URL)[0])

    def test_reject_missing_zone(self):
        self.assertEqual(p._parse_upc_necochea_v531(self.article(zone='el municipio'),NOW,self.URL)[1],0)

    def test_reject_suspended(self):
        self.assertEqual(p._parse_upc_necochea_v531(self.article().replace('</article>','<p>Corte suspendido</p></article>'),NOW,self.URL)[1],0)

    def test_no_links_unverified(self):
        r=p.collect_one('upc_necochea',STAMP,fetcher=lambda u:'<h1>Cortes y avisos</h1>')
        self.assertEqual(r['status'],'unverified')

class TestSCPLRegression(unittest.TestCase):
    def test_apex_fallback_article_attempt_no_keyerror(self):
        home='<a href="/index.php/site/ver-nota?id=2930">CORTE PROGRAMADO DE ENERGIA</a>'
        article='<h1>CORTE PROGRAMADO DE ENERGIA</h1><p>Una ficha sin los campos necesarios</p>'
        def fake(url):
            if url=='https://www.scpl.coop/':raise OSError('blocked')
            if 'id=2930' in url:return article
            return home
        r=p.collect_one('scpl_comodoro',STAMP,fetcher=fake)
        self.assertEqual(r['source_url'],'https://scpl.coop/')
        self.assertEqual(r['status'],'unverified',r)
        self.assertEqual(r['articles_checked'],1,r)
        self.assertNotIn('KeyError',str(r))
        self.assertEqual(r['parser_revision'],'SCPL-ARTICLES-v5.31')

    def test_scpl_incident_not_a_future_schedule(self):
        home='<a href="/index.php/site/ver-nota?id=2919">HECHO VANDALICO PROVOCO UN CORTE DE ENERGIA</a>'
        article='<h1>HECHO VANDALICO PROVOCO UN CORTE DE ENERGIA</h1>Hoy, 10-11-2026 se interrumpio la energia de 01:21 a 06:06'
        def fake(url):
            if url=='https://www.scpl.coop/':raise OSError('blocked')
            if 'id=2919' in url:return article
            return home
        r=p.collect_one('scpl_comodoro',STAMP,fetcher=fake)
        self.assertFalse(r['notices'])
        self.assertNotIn('KeyError',str(r))

if __name__=='__main__':unittest.main()

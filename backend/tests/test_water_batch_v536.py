"""v5.36: official November 13 incident and bounded transient HTTP retries."""
import sys, unittest
from pathlib import Path
from datetime import date
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-14T01:16:30Z'
NOW=w.checked_instant(STAMP)
BASE='https://aguasrionegrinas.com/category/interrupciones/'
BOLSON_URL=('https://aguasrionegrinas.com/el-bolson-arsa-trabaja-para-recuperar-'
            'los-niveles-de-cisterna-y-normalizar-el-servicio-en-barrio-buena-vista/')
DORADAS_URL=('https://aguasrionegrinas.com/playas-doradas-arsa-y-dpa-trabajan-en-'
             'el-acueducto-los-berros-para-restablecer-la-presion/')
CONDOR_URL=('https://aguasrionegrinas.com/el-condor-arsa-realizo-un-operativo-'
            'nocturno-de-limpieza-de-cisterna-para-fortalecer-el-abastecimiento-'
            'de-agua-de-cara-al-verano/')
BOLSON_LABEL='El Bolsón: ARSA trabaja para recuperar los niveles de cisterna y normalizar el servicio en barrio Buena Vista'
DORADAS_LABEL='Playas Doradas: ARSA y DPA trabajan en el acueducto Los Berros para restablecer la presión'
CONDOR_LABEL='El Cóndor: ARSA realizó un operativo nocturno de limpieza de cisterna para fortalecer el abastecimiento de agua de cara al verano'

def listing(*entries):
    return ('<html>' + ''.join(f'<div>{day} noviembre, 2026 <a href="{url}">{title}</a></div>'
                              for day,url,title in entries) + '</html>')

def article(title,day,*paragraphs):
    return ('<html><body><h1>'+title+'</h1>'+str(day)+' noviembre, 2026'
            +''.join('<p>'+p+'</p>' for p in paragraphs)+'</body></html>')

BOLSON=article(BOLSON_LABEL,13,
    'Aguas Rionegrinas informa que este viernes 13 de noviembre se dio inicio una intervención técnica para solucionar una variación en el sistema de bombeo, lo que requirió interrumpir preventivamente la salida del recurso de cisterna con el objetivo de recuperar los niveles de reserva.',
    'La medida afecta a los barrios Buena Vista 1 y Buena Vista 2.',
    'Las tareas comenzaron a las 8 y se estima que a partir de las 14 horas empiece la normalización progresiva del servicio.',
    'Una vez recuperados los niveles de la cisterna, el suministro se restablecerá paulatinamente hasta alcanzar las condiciones habituales de prestación.')
DORADAS=article(DORADAS_LABEL,12,
    'Aguas Rionegrinas desarrolla tareas sobre el acueducto Los Berros, tras detectar una disminución de presión en la conducción.',
    'Como consecuencia de esta situación, la localidad de Playas Doradas registra baja presión en el servicio. Las cuadrillas continúan en el lugar con las tareas necesarias para revertir esta situación.')
CONDOR=article(CONDOR_LABEL,12,
    'Aguas Rionegrinas inició este jueves a las 4 de la mañana un operativo nocturno de limpieza de cisterna en el balneario El Cóndor.',
    'La intervención fue programada durante la madrugada con el objetivo de reducir las afectaciones a los vecinos de la villa balnearia, concentrando las tareas en una franja de menor demanda.',
    'Se estima que hacia el mediodía del jueves 12 comience a normalizarse progresivamente la prestación del servicio.')

class V536(unittest.TestCase):
    def test_bolson_is_reported_but_not_live(self):
        notes,published=w._arsa_article(BOLSON,BOLSON_URL,NOW)
        self.assertEqual(published,date(2026,11,13))
        self.assertEqual(len(notes),1)
        n=notes[0]
        self.assertEqual(n['locality_hint'],'El Bolsón')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertIsNone(n['scheduled_start'])
        self.assertFalse(n['notification_allowed'])

    def test_bolson_official_index_end_to_end(self):
        def fetch(url):
            return listing((13,BOLSON_URL,BOLSON_LABEL)) if url==BASE else BOLSON
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(r['parser_revision'],'ARSA-ARTICLES-v5.36')
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)

    def test_doradas_is_official_bulletin_when_retrievable(self):
        n,d=w._arsa_article(DORADAS,DORADAS_URL,NOW)
        self.assertEqual(len(n),1)
        self.assertEqual(n[0]['kind'],'water_service_bulletin')
        self.assertFalse(n[0]['notification_allowed'])

    def test_condor_past_maintenance_not_current_water_incident(self):
        n,d=w._arsa_article(CONDOR,CONDOR_URL,NOW)
        self.assertEqual(n,[])

    def test_cistern_maintenance_alone_does_not_raise_alert(self):
        html=article('El Bolsón: mantenimiento preventivo de cisterna',13,
            'Aguas Rionegrinas completó un mantenimiento preventivo de la cisterna y mejoró su funcionamiento sin registrar problemas en la prestación del servicio.')
        n,d=w._arsa_article(html,BOLSON_URL,NOW)
        self.assertEqual(n,[])

    def test_retry_only_transient_503_then_success(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return listing((13,BOLSON_URL,BOLSON_LABEL))
            if calls.count(BOLSON_URL)==1:raise HTTPError(url,503,'Service Unavailable',None,None)
            return BOLSON
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(calls.count(BOLSON_URL),2)
        self.assertTrue(r['source_attempts'][0]['transient_http_retry_succeeded'])

    def test_no_retry_permanent_404_and_http_code_recorded(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return listing((13,BOLSON_URL,BOLSON_LABEL))
            raise HTTPError(url,404,'Not Found',None,None)
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(calls.count(BOLSON_URL),1)
        self.assertEqual(r['source_attempts'][0]['http_status'],404)
        self.assertIn('no pudieron consultarse',r['message'])

    def test_second_http_503_stops(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==BASE:return listing((13,BOLSON_URL,BOLSON_LABEL))
            raise HTTPError(url,503,'Service Unavailable',None,None)
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(calls.count(BOLSON_URL),2)
        self.assertEqual(r['source_attempts'][0]['http_status'],503)

    def test_no_cross_domain_links(self):
        def fetch(url):
            if url==BASE:
                return listing((13,'https://evil.test/some-long-fake-announcement/',BOLSON_LABEL),
                               (13,BOLSON_URL,BOLSON_LABEL))
            if url==BOLSON_URL:return BOLSON
            raise AssertionError(url)
        r=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(len(r['notices']),1)

    def test_notice_never_enabled_for_android(self):
        r=w.collect_water(STAMP,fetcher=lambda _: '<html><h1>Sin datos</h1></html>')
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])

if __name__=='__main__':unittest.main()

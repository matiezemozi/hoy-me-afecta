"""v5.65: production-led URL diagnostics and guarded ARSA water-topic language.

Tests are deterministic and offline: they cannot verify the live supply.
"""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T14:09:08Z'
ADC='https://www.aguasdecorrientes.com/noticias'
TITLE='Corte programado de agua en Goya por reparaciones'
IMPACT='Se registrara baja presion en el suministro de agua potable en Goya durante las tareas.'

def adc_article(title=TITLE, paragraph=IMPACT):
    return ('<html><meta property="article:published_time" content="2026-11-21T09:15:00-03:00">'
            '<h1>'+title+'</h1><p>'+paragraph+'</p></html>')

def adc_index(url,title=TITLE):
    return '<html><a href="'+url+'">'+title+'</a></html>'

ARSA_URL='https://aguasrionegrinas.com/el-bolson-arsa-realiza-trabajos-de-purgado-de-red-para-normalizar-el-servicio-en-villa-turismo/'
ARSA_TITLE='El Bolsón: ARSA realiza trabajos de purgado de red para normalizar el servicio en Villa Turismo'

def arsa_article(*paras):
    return '<html><h1>'+ARSA_TITLE+'</h1><span>21 de noviembre de 2026</span>'+''.join('<p>'+p+'</p>' for p in paras)+'</html>'

class TestV565(unittest.TestCase):
    def test_source_count_and_safety_flags(self):
        r=w.collect_water(NOW,lambda _: '<html></html>')
        self.assertGreaterEqual(len(r['sources']),24)
        self.assertFalse(r['notifications_enabled'])
        self.assertFalse(r['android_display_enabled'])
        self.assertTrue(all(not n['notification_allowed'] for n in r['notices']))

    def test_adc_accepts_apex_domain_for_public_article(self):
        u='https://aguasdecorrientes.com/noticias/corte-programado-de-agua-en-goya'
        self.assertTrue(w._adc_article_url(u))
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda x: adc_index(u) if x==ADC else adc_article())
        self.assertEqual(r['valid_article_links_seen'],1)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['notices'][0]['locality_hint'],'Goya')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_adc_preserves_previous_numeric_public_route(self):
        self.assertTrue(w._adc_article_url('https://www.aguasdecorrientes.com/5555/corte-programado-de-agua-en-goya-por-reparaciones'))

    def test_adc_more_scoped_news_routes(self):
        self.assertTrue(w._adc_article_url('https://www.aguasdecorrientes.com/noticia/corte-programado-de-agua-en-goya'))
        self.assertTrue(w._adc_article_url('https://www.aguasdecorrientes.com/noticias/5555'))
        self.assertFalse(w._adc_article_url('https://www.aguasdecorrientes.com/noticias'))
        self.assertFalse(w._adc_article_url('https://www.aguasdecorrientes.com/'))

    def test_adc_still_rejects_unsafe_external_query_or_login(self):
        urls=['http://aguasdecorrientes.com/noticias/corte-programado-de-agua-en-goya',
              'https://evil.example/noticias/corte-programado-de-agua-en-goya',
              'https://aguasdecorrientes.com@evil.example/noticias/corte-programado-de-agua-en-goya',
              'https://aguasdecorrientes.com/noticias/corte-programado-de-agua-en-goya?token=secret',
              'https://aguasdecorrientes.com/noticias/corte-programado-de-agua-en-goya#fragment',
              'https://aguasdecorrientes.com/login',
              'https://aguasdecorrientes.com:8443/noticia/corte-programado-de-agua-en-goya']
        for u in urls:
            with self.subTest(url=u):self.assertFalse(w._adc_article_url(u))

    def test_adc_unmatched_path_diagnostics_never_include_query(self):
        h='<html><a href="/actualidad/cortes-en-goya-2026?token=PRIVATE">Cortes de suministro en Goya</a>'
        h+='<a href="/actualidad/otro-comunicado-2026">Comunicado de corte de suministro en Goya</a>'
        h+='<a href="https://other.example/actualidad/otro">Corte en otras ciudades</a></html>'
        r=w.collect_one('aguas_corrientes_prestador',NOW,lambda _:h)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['valid_article_links_seen'],0)
        self.assertEqual(r['same_site_unmatched_paths_seen'],1)
        self.assertEqual(r['same_site_unmatched_path_samples'],[
            {'path':'/actualidad/otro-comunicado-2026','title':'Comunicado de corte de suministro en Goya'}])
        self.assertNotIn('PRIVATE',str(r))

    def test_adc_104_navigation_links_do_not_trigger_fetch(self):
        h='<html>'+''.join('<a href="/seccion-%d">Pagina municipal de noticias y empresas</a>'%i for i in range(104))+'</html>'
        calls=[]
        def fetch(u):calls.append(u);return h
        r=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(calls,[ADC])
        self.assertEqual(r['html_anchors_seen'],104)
        self.assertEqual(r['valid_article_links_seen'],0)
        self.assertEqual(r['notices'],[])
        self.assertIn('no ofrece enlaces',r['message'])
        self.assertLessEqual(len(r['same_site_unmatched_path_samples']),8)

    def test_adc_article_without_impact_is_not_a_notice(self):
        u='https://aguasdecorrientes.com/noticias/corte-programado-de-agua-en-goya'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda x:adc_index(u) if x==ADC else adc_article(paragraph='Se amplió la red, sin afectar el suministro de agua potable.'))
        self.assertEqual(r['notices'],[])

    def test_adc_403_stays_unverified(self):
        def refuse(url):raise HTTPError(url,403,'forbidden',{},None)
        r=w.collect_one('aguas_corrientes_prestador',NOW,refuse)
        self.assertFalse(r['notifications_enabled'])
        self.assertEqual(r['http_status'],403)
        self.assertEqual(r['notices'],[])

    def test_arsa_purging_topic_requires_explicit_impact(self):
        html=arsa_article('El personal realiza tareas de mantenimiento y purgado en Villa Turismo.',
                          'Durante las tareas podria registrarse baja presion en el barrio Villa Turismo.')
        n,pub=w._arsa_article(html,ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(pub.isoformat(),'2026-11-21')
        self.assertEqual(len(n),1)
        self.assertFalse(n[0]['notification_allowed'])
        self.assertEqual(n[0]['status'],'publication_only_not_live')

    def test_arsa_purging_is_not_itself_impact(self):
        html=arsa_article('El personal realiza tareas de mantenimiento y purgado de red para mejorar el servicio.')
        n,_=w._arsa_article(html,ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(n,[])

    def test_arsa_negated_impact_is_not_outage(self):
        html=arsa_article('El personal realiza trabajos de purgado de red en Villa Turismo.',
                          'No se interrumpira el servicio y los trabajos se hacen sin afectar el suministro.')
        n,_=w._arsa_article(html,ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(n,[])

    def test_arsa_negation_does_not_hide_separate_positive_impact(self):
        html=arsa_article('Los trabajos en el sistema de agua no afectaran el suministro de agua potable. '
                          'No obstante, podra registrarse baja presion en Villa Turismo durante las tareas.')
        n,_=w._arsa_article(html,ARSA_URL,w.checked_instant(NOW))
        self.assertEqual(len(n),1)

if __name__=='__main__':unittest.main()

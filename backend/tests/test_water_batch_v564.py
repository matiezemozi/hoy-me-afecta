"""Aguas de Corrientes concessionaire, conservative public-news pilot v5.64.

Offline fixtures only. No actual service status can be inferred.
"""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T13:51:41Z'
INDEX='https://www.aguasdecorrientes.com/noticias'
ART='https://www.aguasdecorrientes.com/5555/corte-programado-de-agua-en-goya-por-reparaciones'
HEAD='Corte programado de agua en Goya por reparaciones'
LEAD='La interrupcion del suministro de agua potable afecta la zona sur de Goya durante las tareas.'

def listing(title=HEAD,url=ART):
    return '<html><a href="'+url+'">'+title+'</a></html>'

def story(title=HEAD,lead=LEAD,day='2026-11-21'):
    return ('<html><meta property="article:published_time" content="'+day+'T09:15:00-03:00">'
            '<h1>'+title+'</h1><p>'+lead+'</p></html>')

class ADC564(unittest.TestCase):
    def test_source_registered_and_no_automatic_water_notifications(self):
        self.assertEqual(len(w.SOURCES),24)
        self.assertEqual(w.SOURCES['aguas_corrientes_prestador'][2],INDEX)
        self.assertEqual(w.collect_water(NOW,lambda _: '<html></html>')['notifications_enabled'],False)

    def test_precise_signed_article_can_be_informational_only(self):
        calls=[]
        def get(url):
            calls.append(url)
            return listing() if url==INDEX else story()
        r=w.collect_one('aguas_corrientes_prestador',NOW,get)
        self.assertEqual(calls,[INDEX,ART])
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        n=r['notices'][0]
        self.assertEqual(n['locality_hint'],'Goya')
        self.assertEqual(n['published_on'],'2026-11-21')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_end'])

    def test_actual_official_infrastructure_headline_not_impact(self):
        r=w.collect_one('aguas_corrientes_prestador',NOW,lambda _:listing(
            title='CORRIENTES Aguas de Corrientes amplia la red de agua potable en el barrio Quintana'))
        self.assertEqual(r['valid_article_links_seen'],1)
        self.assertEqual(r['impact_title_candidates_seen'],0)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['notices'],[])

    def test_duplicate_links_fetch_only_once(self):
        idx='<html>'+listing()+listing()+'</html>'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:idx if u==INDEX else story())
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['articles_checked'],1)

    def test_official_generic_heading_before_real_title_is_ignored(self):
        html=('<html><h2>Agua y Saneamiento</h2><h1>'+HEAD+'</h1>'
              '<meta property="article:published_time" content="2026-11-21T09:00:00-03:00">'
              '<p>'+LEAD+'</p></html>')
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing() if u==INDEX else html)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['locality_hint'],'Goya')

    def test_undated_recent_looking_article_rejected(self):
        html='<html><h1>'+HEAD+'</h1><p>'+LEAD+'</p></html>'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u: listing() if u==INDEX else html)
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_old_article_with_precise_impact_not_reported(self):
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing() if u==INDEX else story(day='2026-09-05'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'outside_publication_window')

    def test_future_article_is_not_reported(self):
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing() if u==INDEX else story(day='2026-11-23'))
        self.assertEqual(r['notices'],[])

    def test_unknown_city_not_guessed(self):
        t='Corte programado de agua por reparaciones en diversos barrios'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing(t) if u==INDEX else story(title=t))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'locality_not_explicit_in_title')

    def test_two_named_cities_ambiguous_not_reported(self):
        t='Corte de agua en Goya y Mercedes por reparaciones'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing(t) if u==INDEX else story(title=t))
        self.assertEqual(r['notices'],[])

    def test_negated_water_impact_not_reported(self):
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing() if u==INDEX else story(lead='No se interrumpira el suministro de agua potable durante los trabajos.'))
        self.assertEqual(r['notices'],[])

    def test_completely_finished_headline_not_reported(self):
        t='Finalizaron los cortes de agua en Goya tras las reparaciones'
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing(t) if u==INDEX else story(title=t))
        self.assertEqual(r['notices'],[])

    def test_link_security_other_domain_http_query_credentials(self):
        invalid=('https://other.example/5555/corte-programado-de-agua-en-goya-por-reparaciones',
                 'http://www.aguasdecorrientes.com/5555/corte-programado-de-agua-en-goya-por-reparaciones',
                 'https://www.aguasdecorrientes.com@evil.example/5555/corte-programado-de-agua-en-goya-por-reparaciones',
                 ART+'?test=1',ART+'#fake')
        for url in invalid:self.assertFalse(w._adc_article_url(url))
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing(url='https://evil.example/5555/corte-programado-de-agua-en-goya-por-reparaciones'))
        self.assertEqual(r['articles_checked'],0)

    def test_http_403_never_claims_service_is_normal(self):
        def block(url):raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one('aguas_corrientes_prestador',NOW,block)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['http_status'],403)
        self.assertEqual(r['notices'],[])
        self.assertFalse(r['notifications_enabled'])

    def test_article_budget_three_and_partial(self):
        urls=['https://www.aguasdecorrientes.com/'+str(i)+'/corte-programado-de-agua-en-goya-por-reparaciones' for i in (5551,5552,5553,5554)]
        idx='<html>'+''.join(listing(url=u) for u in urls)+'</html>'
        calls=[]
        def fetch(u):
            calls.append(u)
            return idx if u==INDEX else story()
        r=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(r['articles_checked'],3)
        self.assertEqual(r['articles_deferred_by_budget'],1)
        self.assertEqual(len(calls),4)

    def test_article_title_mismatch_rejected(self):
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:listing() if u==INDEX else story(title='Corte de agua en Goya a raiz de una tormenta'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'article_title_mismatch')

if __name__=='__main__':unittest.main()

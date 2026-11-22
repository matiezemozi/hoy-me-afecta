"""v5.66: genuine same-site Aguas de Corrientes public /NNNN story routes.

Only the /noticias page authorizes candidates. A numeric path is not evidence
of an outage: independent signed publication date, locality and positive impact
are still mandatory. Everything is deterministic/offline.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-21T17:23:48Z'
INDEX='https://www.aguasdecorrientes.com/noticias'
IMPACT_URL='https://www.aguasdecorrientes.com/5536'
IMPACT_TITLE='Corte programado de agua en Goya por reparaciones'
IMPACT_PARA='Se registrara baja presion en el suministro de agua potable en Goya durante los trabajos.'


def listing(anchors):
    return '<html>'+''.join('<a href="%s">%s</a>'%(href,title) for href,title in anchors)+'</html>'


def article(title=IMPACT_TITLE, date='2026-11-21', para=IMPACT_PARA):
    meta=('<meta property="article:published_time" content="'+date+'T10:00:00-03:00">'
          if date else '')
    return '<html>'+meta+'<h2>Agua y Saneamiento</h2><h1>'+title+'</h1><p>'+para+'</p></html>'


class WaterV566(unittest.TestCase):
    def test_root_numeric_news_routes_recognised(self):
        for url in ('https://www.aguasdecorrientes.com/5554',
                    'https://www.aguasdecorrientes.com/5547/',
                    'https://aguasdecorrientes.com/5537'):
            with self.subTest(url=url):self.assertTrue(w._adc_article_url(url))

    def test_excludes_nonpublic_external_and_nonarticle_routes(self):
        urls=('https://evil.example/5554', 'http://www.aguasdecorrientes.com/5554',
              'https://www.aguasdecorrientes.com@evil.example/5554',
              'https://www.aguasdecorrientes.com/5554?account=PRIVATE',
              'https://www.aguasdecorrientes.com/5554#fragment',
              'https://www.aguasdecorrientes.com/5554/other',
              'https://www.aguasdecorrientes.com/noticias',
              'https://www.aguasdecorrientes.com/login')
        for url in urls:
            with self.subTest(url=url):self.assertFalse(w._adc_article_url(url))

    def test_original_real_article_titles_are_recognized_not_fetched_as_impacts(self):
        paths=('/5554','/5547','/5546','/5544','/5541','/5537','/5525','/5524')
        titles=('CORRIENTES Aguas de Corrientes amplía la red de agua potable en el barrio Quintana',
                'Aguas de Corrientes ratifica la calidad de sus procesos analíticos',
                'PASO DE LOS LIBRES Más de 2.600 metros de nuevas cañerías de agua potable para el barrio Catamarca',
                'CORRIENTES Aguas de Corrientes continúa con la renovación de cañerías en el casco céntrico de la ciudad',
                'Curuzú Cuatiá Aguas de Corrientes amplía la red de agua potable en el Barrio Progreso',
                'Paso de los Libres: trabajos preventivos en la toma de agua ante la creciente del río Uruguay',
                'Corrientes Aguas de Corrientes concretó la extensión de la red de agua potable en el barrio Pirayuí',
                'Aguas de Corrientes y la Municipalidad de Mercedes amplían la red de agua potable')
        index=listing(zip(paths,titles))
        fetched=[]
        def fetch(url):
            fetched.append(url)
            if url!=INDEX:raise AssertionError('Infrastructure article must not be fetched as an outage')
            return index
        result=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(result['valid_article_links_seen'],8)
        self.assertEqual(result['impact_title_candidates_seen'],0)
        self.assertEqual(result['articles_checked'],0)
        self.assertEqual(result['notices'],[])
        self.assertEqual(fetched,[INDEX])

    def test_public_numeric_path_with_exact_signed_notice(self):
        html=listing([('/5536',IMPACT_TITLE)])
        fetched=[]
        def fetch(url):
            fetched.append(url)
            return html if url==INDEX else article()
        result=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(fetched,[INDEX,IMPACT_URL])
        self.assertEqual(result['parser_revision'],'ADC-HEADING-PUBLISHED-DATE-v5.67')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['article_links_seen'],1)
        self.assertEqual(len(result['notices']),1)
        n=result['notices'][0]
        self.assertEqual(n['locality_hint'],'Goya')
        self.assertEqual(n['published_on'],'2026-11-21')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_start'])

    def test_numeric_story_without_date_does_not_claim_impact(self):
        idx=listing([('/5536',IMPACT_TITLE)])
        result=w.collect_one('aguas_corrientes_prestador',NOW,
                             lambda u:idx if u==INDEX else article(date=''))
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_numeric_story_with_negated_water_cut_rejected(self):
        idx=listing([('/5536',IMPACT_TITLE)])
        result=w.collect_one('aguas_corrientes_prestador',NOW,
                             lambda u:idx if u==INDEX else article(para='No se afectara el servicio de agua potable durante los trabajos.'))
        self.assertEqual(result['notices'],[])

    def test_numeric_story_with_other_locality_than_title_rejected(self):
        idx=listing([('/5536',IMPACT_TITLE)])
        result=w.collect_one('aguas_corrientes_prestador',NOW,
                             lambda u:idx if u==INDEX else article(title='Corte programado de agua en Mercedes'))
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['source_attempts'][0]['result'],'article_title_mismatch')

    def test_numeric_paths_still_respect_budget(self):
        idx=listing([('/'+str(x),IMPACT_TITLE) for x in (5531,5532,5533,5534,5535)])
        fetched=[]
        def fetch(u):
            fetched.append(u)
            return idx if u==INDEX else article()
        result=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(result['articles_checked'],3)
        self.assertEqual(result['articles_deferred_by_budget'],2)
        self.assertEqual(len(fetched),4)
        self.assertTrue(all(u.startswith('https://www.aguasdecorrientes.com/') for u in fetched))

    def test_live_index_shape_104_anchors_with_69_numeric_public_articles(self):
        # Approximate quantities and route shapes reported by GitHub v5.65.
        articles=[('/'+str(5000+i),'Ampliacion de redes en Corrientes') for i in range(68)]
        articles.append(('/5599',IMPACT_TITLE))
        externals=[('https://other.example/site/'+str(i),'Navegacion') for i in range(35)]
        idx=listing(articles+externals)
        urls=[]
        def fetch(url):
            urls.append(url)
            return idx if url==INDEX else article()
        r=w.collect_one('aguas_corrientes_prestador',NOW,fetch)
        self.assertEqual(r['html_anchors_seen'],104)
        self.assertEqual(r['same_site_anchors_seen'],69)
        self.assertEqual(r['valid_article_links_seen'],69)
        self.assertEqual(r['impact_title_candidates_seen'],1)
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(urls,[INDEX,'https://www.aguasdecorrientes.com/5599'])
        self.assertEqual(len(r['notices']),1)
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_explicit_denial_of_low_pressure_is_not_an_impact(self):
        idx=listing([('/5536',IMPACT_TITLE)])
        result=w.collect_one('aguas_corrientes_prestador',NOW,
                             lambda u:idx if u==INDEX else article(
                                 para='No se registrara baja presion en el suministro de agua potable durante las tareas.'))
        self.assertEqual(result['notices'],[])

    def test_negative_phrase_does_not_suppress_separate_positive_paragraph(self):
        idx=listing([('/5536',IMPACT_TITLE)])
        html=article(para='No se afectara el servicio de agua potable durante el lunes.').replace(
            '</html>','<p>El martes se registrara baja presion en el suministro de agua potable en Goya.</p></html>')
        r=w.collect_one('aguas_corrientes_prestador',NOW,
                        lambda u:idx if u==INDEX else html)
        # A documented impact in a separate paragraph remains eligible as
        # publication-only, never a live/scheduled automated notification.
        self.assertEqual(len(r['notices']),1)
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_status_and_flags_no_liveness_claim(self):
        result=w.collect_water(NOW,lambda _: '<html></html>')
        self.assertGreaterEqual(len(result['sources']),24)
        self.assertEqual(result['status'],'pilot_read_only_in_android')
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])

if __name__=='__main__':unittest.main()

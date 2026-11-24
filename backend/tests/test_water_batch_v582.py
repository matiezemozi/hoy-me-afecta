"""v5.82: recognize explicit, dated Jujuy water impacts without live outage claims."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-24T21:39:12Z'
INDEX = w.SOURCES['agua_potable_jujuy_prensa'][2]
ARTICLE = ('https://prensa.jujuy.gob.ar/agua-potable/'
           'agua-potable-informa-corte-emergencia-y-puesta-marcha-obra-definitiva-alto-comedero-y-los-alisos-n126093')
TITLE = 'Agua Potable informa corte de emergencia y puesta en marcha de obra definitiva en Alto Comedero y Los Alisos'
BODY = ('Agua Potable de Jujuy S.E. informa que debido a una avería en el acueducto '
        'principal se realizará un corte de emergencia del suministro de agua potable '
        'en amplios sectores de Alto Comedero y Los Alisos a partir de las 15:00 horas. '
        'Las tareas tienen un horario estimado de finalización cerca de las 2:00 '
        'de la madrugada del miércoles. La restitución del servicio será progresiva.')


def index(title=TITLE):
    return f'<html><body><h1>Agua Potable</h1><h2><a href="{ARTICLE}">{title}</a></h2></body></html>'


def article(body=BODY, title=TITLE, pub='24 de noviembre de 2026 - 11:00', pre=''):
    return (f'<html><head><meta property="article:published_time" '
            f'content="2026-11-24T11:00:00-03:00"></head><body>{pre}'
            f'<h1>{title}</h1><div>{pub}</div><p>{body}</p>'
            f'<h2>Las más leídas</h2><p>Otras noticias de cortes de agua en Palpalá.</p></body></html>')


class TestJujuyExplicitImpactV582(unittest.TestCase):
    def collect(self, html=None, headline=TITLE, stamp=STAMP):
        def fetch(u):
            if u == INDEX:
                return index(headline)
            self.assertEqual(u, ARTICLE)
            return article() if html is None else html
        return w.collect_one('agua_potable_jujuy_prensa',stamp,fetcher=fetch)

    def test_realistic_official_corte_de_emergencia_accepted(self):
        r=self.collect()
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['parser_revision'],'JUJUY-IMPACT-HEADLINE-DIAGNOSTIC-v5.82')
        self.assertEqual(len(r['notices']),1)
        n=r['notices'][0]
        self.assertEqual(n['published_on'],'2026-11-24')
        self.assertEqual(n['locality_hint'],'Alto Comedero / Los Alisos')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertFalse(n['notification_allowed'])
        self.assertEqual(r['source_attempts'][0]['result'],'parsed')

    def test_irrelevant_navigation_heading_does_not_steal_article_title(self):
        pre='<h1>Noticias generales del Gobierno de Jujuy</h1>'
        r=self.collect(article(pre=pre))
        self.assertEqual(len(r['notices']),1)

    def test_headline_and_body_must_be_from_same_official_article(self):
        bad=article(body='Agua Potable de Jujuy informa nueva inversion en la planta y mejor suministro de agua en Alto Comedero.')
        r=self.collect(bad)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'no_explicit_water_service_impact')

    def test_corte_total_del_suministro_with_water_context(self):
        body=('Agua Potable de Jujuy confirmó que se hará un corte total del suministro '
              'de agua potable en Alto Comedero y Los Alisos para reparar una cañería.')
        r=self.collect(article(body=body))
        self.assertEqual(len(r['notices']),1)

    def test_corte_de_emergencia_with_water_context_but_no_double_count(self):
        body=('Agua Potable de Jujuy anunció un corte de emergencia en la red de agua potable '
              'en Los Alisos. La empresa pide cuidar el recurso.')
        r=self.collect(article(body=body))
        self.assertEqual(len(r['notices']),1)

    def test_only_title_corte_but_no_water_disruption_in_body_rejected(self):
        body='Agua Potable de Jujuy inaugura una obra para mejorar la red de agua potable en Alto Comedero.'
        r=self.collect(article(body=body))
        self.assertFalse(r['notices'])

    def test_road_closure_for_water_pipe_not_water_cuts(self):
        body=('Agua Potable de Jujuy informó un corte de tránsito por trabajos de mejora '
              'de acueducto. Se cortará la calle en Los Alisos sin afectar el servicio de agua potable.')
        r=self.collect(article(body=body))
        self.assertFalse(r['notices'])

    def test_electricity_only_is_not_water_bulletin(self):
        body=('Agua Potable de Jujuy anunció un corte total del suministro eléctrico '
              'en Alto Comedero. Hay obras en la red de agua potable sin afectar el servicio de agua.')
        r=self.collect(article(body=body))
        self.assertFalse(r['notices'])

    def test_negated_water_outage_rejected(self):
        body=('Agua Potable de Jujuy informó que no se interrumpirá el suministro de agua potable '
              'en sectores de Alto Comedero y Los Alisos durante los trabajos.')
        r=self.collect(article(body=body))
        self.assertFalse(r['notices'])

    def test_no_provider_attribution_rejected(self):
        badtitle='Interrupción del suministro en Alto Comedero y Los Alisos'
        body='Una empresa informó corte total del suministro de agua potable en sectores de Alto Comedero.'
        html=article(body=body,title=badtitle)
        r=self.collect(html,headline=badtitle)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'water_provider_not_attributed')

    def test_location_only_in_site_footer_cannot_satisfy_geography(self):
        title='Agua Potable informa corte de emergencia por obra definitiva'
        body=('Agua Potable de Jujuy confirmó corte total del servicio de agua potable '
              'en varios puntos aun sin delimitar.')
        r=self.collect(article(body=body,title=title),headline=title)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'impacted_locality_not_verified')

    def test_old_article_no_bulletin(self):
        html=article(pub='27 de septiembre de 2026 - 11:50').replace(
            'content="2026-11-24T11:00:00-03:00"', 'content="2026-09-27T11:50:00-03:00"')
        r=self.collect(html)
        self.assertFalse(r['notices'])
        self.assertEqual(r['status'],'stale')
        self.assertEqual(r['source_attempts'][0]['result'],'outside_publication_window')

    def test_future_article_no_bulletin(self):
        html=article(pub='25 de noviembre de 2026 - 11:50')
        r=self.collect(html)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_conflict')

    def test_date_in_story_without_publication_not_accepted(self):
        html=article(pub='COMUNICADO',body='El 24 de noviembre de 2026, '+BODY).replace(
            '<meta property="article:published_time" content="2026-11-24T11:00:00-03:00">','')
        r=self.collect(html)
        self.assertFalse(r['notices'])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_excluded_official_sidebar_impact_not_mistaken_for_article(self):
        html=article(body='Agua Potable de Jujuy ejecuta mejoras en el sistema de agua potable.',pre='')
        r=self.collect(html)
        self.assertFalse(r['notices'])

    def test_no_unrelated_external_domain(self):
        html=(f'<h1>Agua potable</h1><h2><a href="https://fake.example/{ARTICLE.rsplit("/",1)[1]}">'
              f'{TITLE}</a></h2>')
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP,fetcher=lambda _:html)
        self.assertEqual(r['article_links_seen'],0)
        self.assertEqual(r['notices'],[])

    def test_publication_only_does_not_activate_water_pilot(self):
        r=self.collect()
        self.assertFalse(r['notifications_enabled'])
        self.assertTrue(all(x['notification_allowed'] is False for x in r['notices']))

if __name__=='__main__':unittest.main()

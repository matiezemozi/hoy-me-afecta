"""Offline tests: SCPL Chubut and EPAS Neuquen public water bulletins (v5.49)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-16T20:49:38Z'
SCPL_INDEX = w.SOURCES['scpl_comodoro_chubut'][2]
EPAS_INDEX = w.SOURCES['epas_neuquen_noticias'][2]
SCPL_ART = 'https://scpl.coop/index.php/site/ver-nota?id=2932'
EPAS_ART = 'https://www.epas.gov.ar/2026/11/16/ch-os-mala-l-interrupcion-agua/'
SCPL_TITLE = 'CORTE PROGRAMADO DE AGUA EN NUEVE BARRIOS DE ZONA NORTE'
EPAS_TITLE = 'Chos Malal: interrupcion temporal del servicio de agua potable'


def scpl_index(title=SCPL_TITLE, day='16-11-2026', link=SCPL_ART):
    return (f'<h1>Comunicados</h1><h2><a href="{link}">{title}</a></h2>'
            f'<div>{day}</div><a href="{link}">AMPLIAR</a>')


def scpl_article(title=SCPL_TITLE, day='16-11-2026', body=None):
    if body is None:
        body = ('Por tareas de mantenimiento, este lunes se interrumpe el suministro de agua '
                'en los barrios Centenario, Castelli y Caleta Cordova de Zona Norte, '
                'en Comodoro Rivadavia, por aproximadamente doce horas.')
    return f'<h1>{title}</h1><div>{day}</div><p>{body}</p><h2>CONSEJOS UTILES</h2>'


def epas_index(title=EPAS_TITLE, day='16 noviembre, 2026'):
    return (f'<h1>Novedades</h1><h3><a href="{EPAS_ART}">{title}</a></h3>'
            f'<p>Descripcion del comunicado.</p><span>{day}</span>')


def epas_article(title=EPAS_TITLE, day='2026-11-16', body=None):
    if body is None:
        body = ('Este lunes se interrumpira el suministro de agua potable en Chos Malal '
                'por mantenimiento de una cisterna. Los sectores afectados estan detallados '
                'en el comunicado oficial del EPAS.')
    return (f'<meta property="article:published_time" content="{day}T09:10:00-03:00"/>'
            f'<h1>{title}</h1><p>{body}</p>')


class TestNewWaterSources549(unittest.TestCase):
    def test_sources_present_and_notifying_off(self):
        self.assertEqual(len(w.SOURCES), 16)
        for key in ('absa_buenos_aires', 'samsa_misiones', 'agua_potable_jujuy_prensa',
                    'scpl_comodoro_chubut', 'epas_neuquen_noticias'):
            self.assertIn(key, w.SOURCES)
        # The other thirteen sources may be offline in this test fixture.
        r = w.collect_water(STAMP, fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(len(r['sources']), 16)
        self.assertFalse(r['notifications_enabled'])
        self.assertEqual(r['notices'], [])

    def test_scpl_index_readonly_bulletin_locality(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return scpl_index() if url == SCPL_INDEX else scpl_article()
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=fetch)
        self.assertEqual(r['article_links_seen'], 1)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)
        self.assertEqual(r['notices'][0]['locality_hint'], 'Comodoro Rivadavia')
        self.assertEqual(r['notices'][0]['status'], 'publication_only_not_live')
        self.assertFalse(r['notices'][0]['notification_allowed'])
        self.assertEqual(len(calls), 2)

    def test_scpl_old_articles_skipped_without_network(self):
        def fetch(url):
            self.assertEqual(url, SCPL_INDEX)
            return scpl_index(day='05-11-2026')
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=fetch)
        self.assertEqual(r['status'], 'stale')
        self.assertEqual(r['articles_skipped_old'], 1)
        self.assertEqual(r['articles_checked'], 0)
        self.assertEqual(r['notices'], [])

    def test_scpl_cancellation_not_reported_as_cut(self):
        title = 'SE SUSPENDE CORTE PROGRAMADO DE AGUA EN COMODORO'
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=lambda u:
                          scpl_index(title=title) if u == SCPL_INDEX else
                          scpl_article(title=title, body=('Hoy se suspende el corte programado '
                            'de agua en la Zona Norte por reservas suficientes.')))
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['source_attempts'][0]['result'], 'cancelled_or_restored_announcement')

    def test_scpl_explicit_past_event_excluded(self):
        # Publication still recent, but the dated event has already passed.
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=lambda u:
                         scpl_index(day='14-11-2026') if u == SCPL_INDEX else
                         scpl_article(day='14-11-2026', body=('Manana, domingo 15 de noviembre, '
                             'se interrumpe el suministro de agua en los barrios Centenario y Castelli.')))
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['source_attempts'][0]['result'], 'event_date_already_passed')

    def test_scpl_fallback_to_official_home(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if url == SCPL_INDEX:
                raise ValueError('too_big')
            if url == 'https://scpl.coop/':
                return scpl_index()
            return scpl_article()
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=fetch)
        self.assertEqual(r['index_mode'], 'official_home_fallback')
        self.assertEqual(len(r['notices']), 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(r['index_attempts'][0]['error_type'], 'ValueError')

    def test_scpl_rejects_energy_news_or_untrusted_hosts(self):
        html = scpl_index(title='CORTE PROGRAMADO DE ENERGIA EN ZONA NORTE')
        html += scpl_index(link='https://evil.example/index.php/site/ver-nota?id=42')
        html += scpl_index(link='https://scpl.coop/index.php/site/ver-nota?id=bad')
        self.assertEqual(w._scpl_index(html, SCPL_INDEX), [])

    def test_scpl_article_index_date_must_agree(self):
        r = w.collect_one('scpl_comodoro_chubut', STAMP, fetcher=lambda u:
                          scpl_index(day='16-11-2026') if u == SCPL_INDEX else
                          scpl_article(day='15-11-2026'))
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['source_attempts'][0]['result'], 'index_article_date_mismatch')

    def test_epas_recent_precise_locality_only(self):
        r = w.collect_one('epas_neuquen_noticias', STAMP, fetcher=lambda u:
                          epas_index() if u == EPAS_INDEX else epas_article())
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)
        self.assertEqual(r['notices'][0]['locality_hint'], 'Chos Malal')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_epas_generic_infrastructure_without_disruption_rejected(self):
        title = 'Chos Malal: EPAS inauguro una nueva planta de tratamiento de agua potable'
        r = w.collect_one('epas_neuquen_noticias', STAMP, fetcher=lambda u:
                          epas_index(title=title) if u == EPAS_INDEX else
                          epas_article(title=title, body=('EPAS inauguro nueva tecnologia '
                             'para mejorar el suministro en la ciudad, sin afectar el servicio.')))
        self.assertEqual(r['notices'], [])

    def test_epas_old_articles_not_requested(self):
        def fetch(url):
            self.assertEqual(url, EPAS_INDEX)
            return epas_index(day='11 noviembre, 2026')
        r = w.collect_one('epas_neuquen_noticias', STAMP, fetcher=fetch)
        self.assertEqual(r['status'], 'stale')
        self.assertEqual(r['articles_skipped_old'], 1)
        self.assertEqual(r['articles_checked'], 0)

    def test_epas_multiple_cities_ambiguous(self):
        title = 'EPAS informa interrupciones de agua en varias ciudades'
        r = w.collect_one('epas_neuquen_noticias', STAMP, fetcher=lambda u:
                          epas_index(title=title) if u == EPAS_INDEX else
                          epas_article(title=title, body=('En Chos Malal y en Centenario '
                          'se interrumpira el suministro de agua potable por trabajos urgentes.')))
        self.assertEqual(r['notices'], [])

    def test_failure_does_not_claim_normal_water(self):
        def fail(_): raise OSError('blocked')
        for key in ('scpl_comodoro_chubut', 'epas_neuquen_noticias'):
            with self.subTest(key=key):
                r = w.collect_one(key, STAMP, fetcher=fail)
                self.assertEqual(r['status'], 'unverified')
                self.assertFalse(r['notices'])

if __name__ == '__main__':
    unittest.main()

"""Offline tests for two additional Argentine official water bulletin sources."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-15T18:00:00Z'
SAMSA_URL = 'https://samsa.com.ar/noticias/'
SAMSA_ARTICLE = 'https://samsa.com.ar/trabajos-en-servicio-de-agua-potable-de-garupa/'
JUJUY_URL = 'https://prensa.jujuy.gob.ar/agua-potable-a48'
JUJUY_ARTICLE = ('https://prensa.jujuy.gob.ar/agua-potable/'
                 'agua-potable-trabaja-restablecer-el-servicio-sectores-alto-comedero-y-los-alisos-n125393')


def index_samsa(title, d='15 noviembre, 2026'):
    return f'<html><body><h1>Noticias</h1><h2><a href="{SAMSA_ARTICLE}">{title}</a></h2><div>{d}</div></body></html>'


def art_samsa(title, d='15 noviembre, 2026', body=None):
    if body is None:
        body = ('SAMSA informa que se registra una interrupción del servicio de agua '
                'en Garupá, afectando la distribución en el barrio Santa Helena.')
    return f'<html><body><h1>{title}</h1><div>{d}</div><p>{body}</p></body></html>'


def index_jujuy(title):
    return f'<html><body><h1>Agua Potable</h1><h2><a href="{JUJUY_ARTICLE}">{title}</a></h2></body></html>'


def art_jujuy(title, d='15 de noviembre de 2026 - 10:32', body=None):
    if body is None:
        body = ('Agua Potable de Jujuy informó sobre la interrupción del servicio de agua potable '
                'en sectores de Alto Comedero y Los Alisos. La reparación continúa.')
    return f'<html><body><h1>{title}</h1><div>{d}</div><p>{body}</p><h2>las más leídas</h2></body></html>'


class TestNewSources(unittest.TestCase):
    def test_source_count_existing_integrity_and_global_notifications_off(self):
        self.assertGreaterEqual(len(w.SOURCES), 14)
        self.assertIn('absa_buenos_aires', w.SOURCES)
        self.assertIn('osse_mar_del_plata', w.SOURCES)
        self.assertIn('samsa_misiones', w.SOURCES)
        self.assertIn('agua_potable_jujuy_prensa', w.SOURCES)

    def test_samsa_parses_read_only_localized_publication(self):
        title = 'Interrupción del servicio de agua potable en Garupá'
        def fetch(u):
            return index_samsa(title) if u == SAMSA_URL else art_samsa(title)
        result = w.collect_one('samsa_misiones', STAMP, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['article_links_seen'], 1)
        self.assertEqual(len(result['notices']), 1)
        item=result['notices'][0]
        self.assertEqual(item['locality_hint'], 'Garupá')
        self.assertEqual(item['status'], 'publication_only_not_live')
        self.assertFalse(item['notification_allowed'])
        self.assertFalse(result['notifications_enabled'])

    def test_samsa_old_dated_article_not_fetched(self):
        title = 'Interrupción del servicio de agua potable en Garupá'
        def fetch(u):
            self.assertEqual(u, SAMSA_URL)
            return index_samsa(title,'6 noviembre, 2026')
        r=w.collect_one('samsa_misiones', STAMP, fetcher=fetch)
        self.assertEqual(r['status'], 'stale')
        self.assertEqual(r['article_links_seen'], 1)
        self.assertEqual(r['articles_skipped_old'], 1)
        self.assertEqual(r['articles_checked'], 0)
        self.assertEqual(r['notices'], [])

    def test_samsa_generic_works_not_alarm(self):
        title='SAMSA INSTALÓ NUEVA TECNOLOGÍA EN EL SERVICIO DE AGUA POTABLE'
        body=('SAMSA instaló tecnología de avanzada en el servicio de agua potable. '
              'Estas inversiones permitirán ampliar la capacidad de los sistemas de Posadas.')
        r=w.collect_one('samsa_misiones', STAMP, fetcher=lambda u:
                        index_samsa(title) if u==SAMSA_URL else art_samsa(title,body=body))
        self.assertEqual(r['notices'], [])

    def test_samsa_no_geography_no_bulletin(self):
        title='Interrupción del servicio de agua potable'
        r=w.collect_one('samsa_misiones', STAMP, fetcher=lambda u:
                        index_samsa(title) if u==SAMSA_URL else
                        art_samsa(title,body='Se registra una interrupción del servicio de agua en sectores no identificados.'))
        self.assertEqual(r['notices'], [])

    def test_samsa_no_notification_if_negated(self):
        title='Trabajos en el servicio de agua potable de Garupá'
        r=w.collect_one('samsa_misiones', STAMP, fetcher=lambda u:
                        index_samsa(title) if u==SAMSA_URL else
                        art_samsa(title,body='SAMSA informa que no se interrumpirá el servicio de agua en Garupá por estos trabajos.'))
        self.assertEqual(r['notices'], [])

    def test_samsa_mismatched_date_not_published(self):
        title='Interrupción del servicio de agua potable en Garupá'
        r=w.collect_one('samsa_misiones', STAMP, fetcher=lambda u:
                        index_samsa(title) if u==SAMSA_URL else art_samsa(title,d='14 noviembre, 2026'))
        self.assertEqual(r['notices'], [])

    def test_jujuy_reads_water_company_government_story(self):
        title='Agua Potable trabaja para restablecer el servicio en Alto Comedero y Los Alisos'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u:
                        index_jujuy(title) if u==JUJUY_URL else art_jujuy(title))
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)
        item=r['notices'][0]
        self.assertIn('Alto Comedero',item['locality_hint'])
        self.assertIn('Los Alisos',item['locality_hint'])
        self.assertFalse(item['notification_allowed'])
        self.assertEqual(item['status'],'publication_only_not_live')

    def test_jujuy_old_not_offered_as_current(self):
        title='Agua Potable trabaja para restablecer el servicio en Alto Comedero y Los Alisos'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u:
                        index_jujuy(title) if u==JUJUY_URL else
                        art_jujuy(title,d='27 de septiembre de 2026 - 11:50'))
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['status'], 'stale')

    def test_jujuy_completed_story_not_alert(self):
        title='Agua Potable concluyó la reparación del acueducto en Alto Comedero'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u:
                        index_jujuy(title) if u==JUJUY_URL else art_jujuy(title))
        self.assertEqual(r['notices'], [])

    def test_jujuy_works_only_not_alert(self):
        title='Agua Potable de Jujuy inaugura obra de ampliación en Alto Comedero'
        body='Agua Potable de Jujuy mejorará el servicio con nueva cañería sin afectar a los usuarios.'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u:
                        index_jujuy(title) if u==JUJUY_URL else art_jujuy(title,body=body))
        self.assertEqual(r['notices'], [])

    def test_jujuy_generic_locality_unknown_no_alert(self):
        title='Agua Potable de Jujuy informa una interrupción temporal del servicio'
        body='Agua Potable de Jujuy confirmó una interrupción temporal del servicio en lugares aún no identificados.'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u:
                        index_jujuy(title) if u==JUJUY_URL else art_jujuy(title,body=body))
        self.assertEqual(r['notices'], [])

    def test_junior_news_links_not_followed(self):
        html='<h1>Agua Potable</h1><h2><a href="https://example.com/evil-n100">Corte de agua en San Pedro</a></h2>'
        html+='<h2><a href="https://prensa.jujuy.gob.ar/area/no-valid">Otra noticia de agua</a></h2>'
        r=w.collect_one('agua_potable_jujuy_prensa', STAMP, fetcher=lambda u: html)
        self.assertEqual(r['article_links_seen'], 0)
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['status'], 'unverified')

    def test_inaccessible_sites_do_not_claim_normal_supply(self):
        for key in ('samsa_misiones','agua_potable_jujuy_prensa'):
            with self.subTest(key=key):
                def fail(_u): raise OSError('offline')
                r=w.collect_one(key,STAMP,fetcher=fail)
                self.assertEqual(r['status'],'unverified')
                self.assertEqual(r['notices'], [])

if __name__ == '__main__': unittest.main()

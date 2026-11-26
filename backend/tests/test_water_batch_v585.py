"""v5.85: Jujuy official article paragraphs must not include related news cards."""
import sys
import unittest
from pathlib import Path
from datetime import date
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW=w.checked_instant('2026-11-24T22:27:39Z')
URL=('https://prensa.jujuy.gob.ar/agua-potable/'
     'agua-potable-informa-corte-emergencia-y-puesta-marcha-obra-definitiva-alto-comedero-y-los-alisos-n126093')
TITLE=('Agua Potable informa corte de emergencia y puesta en marcha de obra '
       'definitiva en Alto Comedero y Los Alisos')
OTHER=('Gestion integral para garantizar el abastecimiento de agua potable '
       'en la escuela de Coraya')
OTHER_LINK='/agua-potable/gestion-integral-garantizar-el-abastecimiento-agua-potable-la-escuela-coraya-n126018'
INTRO=('Agua Potable de Jujuy S.E. informa que un corte de emergencia del '
       'suministro de agua potable afectara sectores de Alto Comedero y '
       'Los Alisos tras la rotura de un acueducto.')
SECOND=('La interrupcion afectara sectores de Sargento Cabral, Alto Comedero '
        'y Los Alisos por los trabajos de reparacion de una caneria.')
NEGATIVE=('Agua Potable de Jujuy S.E. informa que las tareas en la red de '
          'agua potable de Alto Comedero y Los Alisos no interrumpiran el suministro.')
META='<meta property="article:published_time" content="2026-11-24T12:45:00-03:00">'

def official_html(body_html, *, appendix='', meta=META, date='24 de noviembre de 2026 - 12:45'):
    return (f'<html><head>{meta}</head><body><header><h2>{TITLE}</h2>'
            f'<div>Panel de Ministerios y servicios</div></header>'
            f'<main><article><h1>{TITLE}</h1><div>{date}</div>'
            f'{body_html}</article></main>'
            f'<aside><h2>Las mas leidas</h2>{appendix}</aside></body></html>')

class TestJujuyNoRelatedNewsContaminationV585(unittest.TestCase):
    def parse(self,html):
        return w._jujuy_article(html,URL,NOW,TITLE)

    def test_related_div_not_in_bulletin(self):
        related=f'<div>Segui leyendo <a href="{OTHER_LINK}">{OTHER}</a></div>'
        html=official_html(f'<p>{INTRO}</p>{related}<p>{SECOND}</p>')
        n,p,v=self.parse(html)
        self.assertEqual(v,'parsed')
        self.assertEqual(p,date(2026,11,24))
        self.assertIn('Sargento Cabral',n['zone_detail'])
        self.assertNotIn('Segui leyendo',n['zone_detail'])
        self.assertNotIn('Gestion integral',n['zone_detail'])

    def test_related_link_inside_article_paragraph_cleaned(self):
        body=(f'<p>{INTRO} Seguí leyendo '
              f'<a href="{OTHER_LINK}">{OTHER}</a> {SECOND}</p>')
        n,p,v=self.parse(official_html(body))
        self.assertEqual(v,'parsed')
        self.assertIn('Sargento Cabral',n['zone_detail'])
        self.assertNotIn('Seguí leyendo',n['zone_detail'])
        self.assertNotIn('Gestion integral',n['zone_detail'])
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])

    def test_unrelated_sidebar_paragraph_same_35_char_prefix_rejected(self):
        # The old substring test compared only the shared first 35 chars.
        same_prefix=('Agua Potable de Jujuy S.E. informa que un corte de emergencia '
                     'del suministro de agua potable afectara Alto Comedero y Los Alisos.')
        fake=official_html(f'<p>{NEGATIVE}</p>',
                           appendix=f'<p>{same_prefix}</p>')
        n,p,v=self.parse(fake)
        self.assertIsNone(n)
        self.assertNotEqual(v,'parsed')

    def test_no_article_paragraphs_not_accepted(self):
        n,p,v=self.parse(official_html(f'<div>{INTRO}</div>'))
        self.assertIsNone(n)
        self.assertEqual(v,'no_verifiable_water_article_body')

    def test_suggestion_only_not_evidence_of_cut(self):
        html=official_html(f'<p>{NEGATIVE}</p><div>Segui leyendo '
                           f'<a href="{OTHER_LINK}">{OTHER}</a></div>',
                           appendix=f'<p>{INTRO}</p>')
        n,p,v=self.parse(html)
        self.assertIsNone(n)

    def test_plain_article_with_two_paragraphs(self):
        n,p,v=self.parse(official_html(f'<p>{INTRO}</p><p>{SECOND}</p>'))
        self.assertEqual(v,'parsed')
        self.assertTrue(n['zone_detail'].startswith(INTRO))
        self.assertIn(SECOND,n['zone_detail'])

    def test_negative_article_remains_rejected(self):
        n,p,v=self.parse(official_html(f'<p>{NEGATIVE}</p>'))
        self.assertIsNone(n)
        self.assertNotEqual(v,'parsed')

    def test_article_header_date_conflict_remains_rejected(self):
        n,p,v=self.parse(official_html(f'<p>{INTRO}</p>',
                        date='23 de noviembre de 2026 - 12:45'))
        self.assertIsNone(n)
        self.assertEqual(v,'publication_date_conflict')

    def test_article_no_meta_no_date_remains_rejected(self):
        n,p,v=self.parse(official_html(f'<p>{INTRO}</p>',meta='',date='Comunicado'))
        self.assertIsNone(n)
        self.assertEqual(v,'publication_date_not_verified')

    def test_article_age_remains_rejected(self):
        old='<meta property="article:published_time" content="2026-11-10T12:45:00-03:00">'
        n,p,v=self.parse(official_html(f'<p>{INTRO}</p>',meta=old,
                        date='10 de noviembre de 2026 - 12:45'))
        self.assertIsNone(n)
        self.assertEqual(v,'outside_publication_window')

    def test_water_provider_cannot_be_inferred_from_related_story(self):
        text=('Personal de una empresa interviene por interrupcion del suministro '
              'de agua potable en Alto Comedero y Los Alisos.')
        heading='Interrupcion del suministro en Alto Comedero y Los Alisos'
        html=official_html(f'<p>{text}</p>'.replace('foo','foo'))
        html=html.replace(TITLE,heading)
        n,p,v=w._jujuy_article(html,URL,NOW,heading)
        self.assertIsNone(n)
        self.assertEqual(v,'water_provider_not_attributed')

    def test_all_sources_keep_read_only_pilot(self):
        self.assertEqual(len(w.SOURCES),30)
        feed=w.collect_water('2026-11-24T22:27:39Z',fetcher=lambda _: '<h1>Sin comunicados</h1>')
        self.assertFalse(feed['notifications_enabled'])
        self.assertFalse(feed['android_display_enabled'])
        self.assertEqual(len(feed['sources']),30)
        self.assertEqual(feed['source_health']['accepted_public_bulletins'],0)
        self.assertEqual(feed['notices'],[])

if __name__=='__main__':
    unittest.main()

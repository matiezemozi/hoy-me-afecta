"""Offline regression tests for SAMSA index-title discovery in v5.47."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

INDEX = 'https://samsa.com.ar/noticias/'
PUBLISHED = '2026-11-15T23:22:46Z'
TITLE = 'SAMSA INSTALÓ NUEVA TECNOLOGÍA EN EL SERVICIO DE AGUA POTABLE'
ARTICLE = 'https://samsa.com.ar/samsa-instalo-nueva-tecnologia-en-el-servicio-de-agua-potable/'


def sam_index(date_text='6 noviembre, 2026'):
    # Real public listing uses article cards and may render title as h4 rather
    # than h1/h2/h3. This is why v5.46 found zero article links.
    return (f'<html><body><h1>Noticias</h1><article><h4><a href="{ARTICLE}">{TITLE}</a></h4>'
            f'<div>{date_text}</div><p>Descripción breve.</p>'
            f'<a href="{ARTICLE}">Leer más: {TITLE}</a></article></body></html>')


class SAMSAIndex547(unittest.TestCase):
    def test_non_heading_title_accepted_and_deduplicated(self):
        entries = w._article_listing_html(sam_index(), INDEX, 'samsa')
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][0], ARTICLE)
        self.assertEqual(entries[0][2].isoformat(), '2026-11-06')

    def test_all_old_items_skipped_without_article_fetch(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            self.assertEqual(url, INDEX)
            return sam_index()
        r=w.collect_one('samsa_misiones',PUBLISHED,fetcher=fetch)
        self.assertEqual(calls,[INDEX])
        self.assertEqual(r['status'],'stale')
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['articles_skipped_old'],1)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(r['latest_published_date'],'2026-11-06')
        self.assertFalse(r['notices'])
        self.assertFalse(r['notifications_enabled'])

    def test_recent_article_can_be_parsed_but_never_push_notified(self):
        title='Interrupción del servicio de agua potable en Garupá'
        slug='interrupcion-del-servicio-de-agua-potable-en-garupa'
        url=f'https://samsa.com.ar/{slug}/'
        index=(f'<h1>Noticias</h1><h4><a href="{url}">{title}</a></h4>'
               '<span>15 noviembre, 2026</span>')
        article=(f'<h1>{title}</h1><div>15 noviembre, 2026</div>'
                 '<p>SAMSA informa que se registra una interrupción del servicio de agua potable '
                 'en Garupá, afectando la distribución en el barrio Santa Helena.</p>')
        r=w.collect_one('samsa_misiones', PUBLISHED,
                        fetcher=lambda u: index if u==INDEX else article)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['locality_hint'],'Garupá')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_bad_links_and_short_labels_rejected(self):
        html=(f'<h4><a href="https://bad.example/{ARTICLE.split("/")[-2]}/">{TITLE}</a></h4>'
              f'<h4><a href="{ARTICLE}">Noticias</a></h4>'
              f'<h4><a href="{ARTICLE}">Otro asunto con título largo totalmente distinto</a></h4>'
              f'<h4><a href="{ARTICLE}?a=1">{TITLE}</a></h4>')
        self.assertEqual(w._article_listing_html(html,INDEX,'samsa'),[])

    def test_government_jujuy_index_matching_is_unchanged(self):
        link=('https://prensa.jujuy.gob.ar/agua-potable/'
              'agua-potable-trabaja-restablecer-el-servicio-n125393')
        title='Agua Potable trabaja para restablecer el servicio'
        bad=f'<h4><a href="{link}">{title}</a></h4>'
        good=f'<h2><a href="{link}">{title}</a></h2>'
        self.assertEqual(w._article_listing_html(bad,'https://prensa.jujuy.gob.ar/agua-potable-a48','jujuy'),[])
        self.assertEqual(len(w._article_listing_html(good,'https://prensa.jujuy.gob.ar/agua-potable-a48','jujuy')),1)

if __name__=='__main__':unittest.main()

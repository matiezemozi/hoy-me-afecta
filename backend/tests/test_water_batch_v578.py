"""v5.78: Date belongs to the official article header, never the <title>/slug or event text."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW='2026-11-23T23:45:11Z'
HOST='https://www.aguascordobesas.com.ar'
INDEX=HOST+'/CanalSaladePrensa/HomeSalaPrensa/'
URL=HOST+'/CanalSaladePrensa/DetalleComunicado/598/trabajos-de-reparacion-en-barrio-centro-20-11-2026'
REL=URL[len(HOST)+1:]
TITLE='Trabajos de reparación en barrio Centro - 20/11/2026'
REPAIR=('Les informamos que estamos realizando tareas de reparación en Av. Vélez Sarsfield '
        'al 100, barrio Centro. Nuestros equipos se encuentran trabajando para resolver la '
        'situación en el menor tiempo posible. El único barrio alcanzado por los trabajos es Centro. '
        'Les recordamos que no deberían experimentar inconvenientes si realizan un uso responsable.')
IMPACT='Se registra baja presión en el servicio de agua potable de barrio Centro.'


def article(day='20/11/2026',body=REPAIR,label='Comunicado de prensa',title=TITLE,doc_title=True,extra=''):
    doc='<title>'+title+'</title>' if doc_title else ''
    return ('<html><head>'+doc+'</head><body>'+extra+'<h2>'+label+'</h2><div>'+day+'</div>'
            '<h1>'+title+'</h1><p>'+body+'</p></body></html>')


def index():
    return ('<html><body><h3>Comunicados de Prensa</h3><div><time>20 Noviembre 2026</time>'
            '<a href="'+REL+'">Leer más</a></div></body></html>')


class CordobaArticleHeaderV578(unittest.TestCase):
    def test_document_title_duplicate_is_not_publication_header(self):
        html=article()
        dom,visible=w.page(html)
        self.assertGreaterEqual(w.folded(visible).count(w.folded(TITLE)),2)
        self.assertEqual(w._cba_publication_date(html,dom,visible,TITLE).isoformat(),'2026-11-20')

    def test_repaired_realistic_public_article_stays_non_notice(self):
        n,p,why=w._cba_article(article(),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(p.isoformat(),'2026-11-20')
        self.assertEqual(why,'no_explicit_water_service_interruption')

    def test_explicit_effect_still_publication_only(self):
        n,p,why=w._cba_article(article(body=IMPACT),URL,w.checked_instant(NOW))
        self.assertEqual(why,'parsed')
        self.assertEqual(n['published_on'],'2026-11-20')
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])

    def test_collect_one_uses_actual_date_and_rejects_unverified_impact(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==INDEX:return index()
            if url==URL:return article()
            raise AssertionError(url)
        result=w.collect_one('aguas_cordobesas',NOW,fetch)
        self.assertEqual(calls,[INDEX,URL])
        self.assertEqual(result['source_attempts'][0]['result'],'no_explicit_water_service_interruption')
        self.assertEqual(result['latest_published_date'],'2026-11-20')
        self.assertEqual(result['notices'],[])
        self.assertFalse(result['notifications_enabled'])

    def test_older_than_three_days_still_rejected(self):
        n,p,why=w._cba_article(article(day='11/11/2026'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(p.isoformat(),'2026-11-11')
        self.assertEqual(why,'outside_publication_window')

    def test_future_date_still_rejected(self):
        n,p,why=w._cba_article(article(day='24/11/2026'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(why,'outside_publication_window')

    def test_date_only_in_document_title_is_not_publication_date(self):
        n,p,why=w._cba_article(article(day='Sin fecha'),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertIsNone(p)
        self.assertEqual(why,'publication_date_not_verified')

    def test_date_only_in_url_is_not_published_date(self):
        n,p,why=w._cba_article(article(day='Sin fecha',doc_title=False),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(why,'publication_date_not_verified')

    def test_event_date_inside_body_is_not_publication(self):
        n,p,why=w._cba_article(article(day='Sin fecha',body='El 20/11/2026 '+IMPACT),URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertIsNone(p)
        self.assertEqual(why,'publication_date_not_verified')

    def test_unlabelled_event_date_before_heading_is_not_publication(self):
        html=('<html><head><title>'+TITLE+'</title></head><body><p>La reparación comenzó el 20/11/2026</p>'
              '<h1>'+TITLE+'</h1><p>'+IMPACT+'</p></body></html>')
        n,p,why=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(why,'publication_date_not_verified')

    def test_unrelated_card_date_does_not_supply_header(self):
        html=('<html><head><title>'+TITLE+'</title></head><body><aside>Agenda de obras 20/11/2026</aside>'
              '<h1>'+TITLE+'</h1><p>'+IMPACT+'</p></body></html>')
        n,p,why=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(why,'publication_date_not_verified')

    def test_document_title_does_not_overrule_article_header_date(self):
        n,p,why=w._cba_article(article(day='21/11/2026',body=IMPACT),URL,w.checked_instant(NOW))
        self.assertEqual(why,'parsed')
        self.assertEqual(p.isoformat(),'2026-11-21')
        self.assertEqual(n['published_on'],'2026-11-21')

    def test_meta_date_still_supported(self):
        html=article(day='Sin fecha',body=IMPACT).replace('</head>',
                   '<meta property="article:published_time" content="2026-11-20T09:30:00-03:00"></head>')
        n,p,why=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertEqual(why,'parsed')
        self.assertEqual(p.isoformat(),'2026-11-20')

    def test_standalone_date_from_unrelated_para_not_used(self):
        html=('<html><head><title>'+TITLE+'</title></head><body><p>20/11/2026</p>'
              '<h1>'+TITLE+'</h1><p>'+IMPACT+'</p></body></html>')
        n,p,why=w._cba_article(html,URL,w.checked_instant(NOW))
        self.assertIsNone(n)
        self.assertEqual(why,'publication_date_not_verified')

    def test_no_new_source_or_notification_activated(self):
        self.assertEqual(len(w.SOURCES),30)
        result=w.collect_water(NOW,lambda _:'<html><body>Sin novedades</body></html>')
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(result['android_read_only_pilot_available'])
        self.assertTrue(all(not source['notifications_enabled'] for source in result['sources'].values()))

if __name__=='__main__': unittest.main()

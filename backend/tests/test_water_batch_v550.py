"""Offline regression tests for conservative ARSA and SCPL request budgets (v5.50)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-16T21:19:46Z'
ARSA_INDEX = w.SOURCES['aguas_rionegrinas_arsa'][2]
SCPL_INDEX = w.SOURCES['scpl_comodoro_chubut'][2]


def arsa_url(i):
    return f'https://aguasrionegrinas.com/bariloche-corte-de-agua-en-el-barrio-pilar-numero-{i}/'


def arsa_index(n=5, dated=False):
    pieces=['<h1>Interrupciones</h1>']
    for i in range(n):
        day = '13 de noviembre de 2026' if dated and i == 0 else '16 de noviembre de 2026'
        pieces.append(f'<p>{day}</p><a href="{arsa_url(i)}">Bariloche: interrupción del servicio de agua sector {i}</a>')
    return ''.join(pieces)


def arsa_article():
    return ('<meta property="article:published_time" content="2026-11-16T11:10:00-03:00">'
            '<h1>Bariloche: interrupción del servicio de agua potable en barrio Pilar</h1>'
            '<p>La empresa Aguas Rionegrinas informa que por un inconveniente '
            'en el sistema de bombeo el suministro de agua potable presenta '
            'baja presión en barrio Pilar, de la ciudad de Bariloche, desde esta mañana.</p>')


def scpl_url(i):
    return f'https://scpl.coop/index.php/site/ver-nota?id={2900+i}'


def scpl_archive(n=30, cancelled=frozenset()):
    out=['<h1>Comunicados SCPL</h1>']
    for i in range(n):
        title = ('SE SUSPENDE CORTE PROGRAMADO DE AGUA EN COMODORO' if i in cancelled
                 else f'CORTE PROGRAMADO DE AGUA EN BARRIOS DE COMODORO {i}')
        out.append(f'<h2><a href="{scpl_url(i)}">{title}</a></h2><p>16-11-2026</p>')
    return ''.join(out)


def scpl_article():
    return ('<h1>CORTE PROGRAMADO DE AGUA EN BARRIOS DE COMODORO</h1>'
            '<div>16-11-2026</div>'
            '<p>Se interrumpe el suministro de agua en diversos barrios de Comodoro Rivadavia '
            'como consecuencia de mantenimiento en las instalaciones de bombeo.</p>')


class TestWaterRequestBudget550(unittest.TestCase):
    def test_no_new_sources_or_notifications(self):
        self.assertGreaterEqual(len(w.SOURCES), 16)
        self.assertFalse(w.collect_water(STAMP, fetcher=lambda _: '').get('notifications_enabled'))

    def test_arsa_budget_max_two_and_partial(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return arsa_index(6) if url == ARSA_INDEX else arsa_article()
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['parser_revision'],'ARSA-FRESH-ROTATION-v5.55')
        self.assertEqual(result['article_links_seen'],6)
        self.assertEqual(result['articles_checked'],2)
        self.assertEqual(result['articles_deferred_by_budget'],4)
        self.assertEqual(result['article_fetch_completeness'],'partial')
        self.assertEqual(len(calls),3)
        self.assertFalse(result['rate_limited'])
        self.assertTrue(all(n['notification_allowed'] is False for n in result['notices']))

    def test_arsa_old_index_link_skipped(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return arsa_index(2,dated=True) if url==ARSA_INDEX else arsa_article()
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['article_links_skipped_old'],1)
        self.assertEqual(result['articles_checked'],1)
        self.assertNotIn(arsa_url(0),calls)

    def test_arsa_http_429_stops_requests_without_erasing_collected_notice(self):
        calls=[]
        result_hour=int(w.checked_instant(STAMP).astimezone(w.timezone.utc).timestamp()//3600)
        def fetch(url):
            calls.append(url)
            if url==ARSA_INDEX: return arsa_index(5)
            if url==arsa_url(1 + (result_hour % 4)):
                raise HTTPError(url,429,'Too Many Requests',None,None)
            return arsa_article()
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['articles_checked'],2)
        self.assertEqual(result['article_links_skipped_after_rate_limit'],0)
        self.assertEqual(result['articles_deferred_by_budget'],3)
        self.assertTrue(result['rate_limited'])
        self.assertEqual(result['article_fetch_completeness'],'partial')
        self.assertEqual(len(calls),3)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['notices']),1)

    def test_scpl_indicates_archive_outside_relevant_window(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return scpl_archive() if url==SCPL_INDEX else scpl_article()
        result=w.collect_one('scpl_comodoro_chubut',STAMP,fetcher=fetch)
        self.assertEqual(result['parser_revision'],'SCPL-INDEX-OPT-v5.50')
        self.assertEqual(result['article_links_seen'],30)
        self.assertEqual(result['index_window_considered'],12)
        self.assertEqual(result['article_links_outside_window'],18)
        self.assertEqual(result['articles_checked'],5)
        self.assertEqual(len(calls),6)
        self.assertIn('ventana reciente',result['message'])

    def test_scpl_cancelled_headlines_dont_require_article_fetch(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return scpl_archive(4,cancelled={0,1,2}) if url==SCPL_INDEX else scpl_article()
        result=w.collect_one('scpl_comodoro_chubut',STAMP,fetcher=fetch)
        self.assertEqual(result['articles_skipped_cancelled'],3)
        self.assertEqual(result['articles_checked'],1)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(result['notices']),1)
        self.assertTrue(all(x['not_fetched'] for x in result['source_attempts'][:3]))

    def test_scpl_no_false_service_normal_from_only_cancellations(self):
        result=w.collect_one('scpl_comodoro_chubut',STAMP,fetcher=lambda url:
                             scpl_archive(3,cancelled={0,1,2}) if url==SCPL_INDEX else
                             (_ for _ in ()).throw(AssertionError('Unnecessary article fetch')))
        self.assertEqual(result['notices'],[])
        self.assertEqual(result['status'],'unverified')
        self.assertEqual(result['articles_checked'],0)

    def test_scpl_archive_dates_beyond_first_24_not_evaluated(self):
        entries=w._scpl_index(scpl_archive(50),SCPL_INDEX)
        self.assertEqual(len(entries),50)
        self.assertTrue(all(item[2] is not None for item in entries[:24]))
        self.assertTrue(all(item[2] is None for item in entries[24:]))


if __name__=='__main__':
    unittest.main()

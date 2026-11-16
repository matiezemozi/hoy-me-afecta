"""Offline regression tests: SAT Tucuman and Aguas de Santiago (v5.51)."""
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-16T21:29:02Z'
SAT_INDEX=w.SOURCES['sat_tucuman_noticias'][2]
SDE_INDEX=w.SOURCES['aguas_santiago_novedades'][2]
SAT_URL='https://aguasdeltucuman.com.ar/noticias/Corte%20temporal%20del%20servicio%20en%20San%20Miguel%20de%20Tucuman'
SDE_URL='https://aguasdesantiago.com.ar/nota/39/interrupcion-temporal-en-la-banda'
SAT_TITLE='Corte temporal de suministro de agua en San Miguel de Tucumán'
SDE_TITLE='La Banda: corte programado de agua por mantenimiento'


def index(key='sat',day='16 NOV. 2026',title=None,url=None):
    if key=='sat':
        title=title or SAT_TITLE;url=url or SAT_URL
        return f'<h1>Noticias</h1><a href="{url}">{title}</a>'
    title=title or SDE_TITLE;url=url or SDE_URL
    return f'<h1>Noticias y novedades</h1><div>{day}</div><a href="{url}">{title}</a>'


def article(title=SAT_TITLE,day='2026-11-16',body=None,meta=True):
    if body is None:
        body=('La Sociedad Aguas del Tucumán informa que se interrumpirá el suministro '
              'de agua potable en San Miguel de Tucumán por trabajos programados '
              'en una cañería, con afectación limitada a los sectores detallados.')
    m=f'<meta property="article:published_time" content="{day}T08:30:00-03:00">' if meta else ''
    return m+f'<h1>{title}</h1><p>{body}</p>'


class TestRegionalNews551(unittest.TestCase):
    def test_sources_count_and_no_notifications(self):
        self.assertEqual(len(w.SOURCES),18)
        r=w.collect_water(STAMP,fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(len(r['sources']),18)
        self.assertFalse(r['notifications_enabled'])
        self.assertEqual(r['notices'],[])

    def test_sat_precise_recent_bulletin(self):
        calls=[]
        def fetch(u):
            calls.append(u)
            return index() if u==SAT_INDEX else article()
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['articles_checked'],1)
        self.assertEqual(r['notices'][0]['locality_hint'],'San Miguel de Tucumán')
        self.assertEqual(r['notices'][0]['status'],'publication_only_not_live')
        self.assertFalse(r['notices'][0]['notification_allowed'])
        self.assertEqual(len(calls),2)

    def test_sat_unknown_article_date_not_improvised(self):
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:
                      index() if u==SAT_INDEX else article(meta=False))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'publication_date_not_verified')

    def test_sat_completed_work_rejected(self):
        title='La SAT finalizó reparaciones y normalizó el servicio en San Miguel de Tucumán'
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:
                      index(title=title) if u==SAT_INDEX else article(title=title))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'finished_or_negative_headline')

    def test_sat_no_impact_and_negative_rejected(self):
        for body in (
             'La SAT inauguró una planta de abastecimiento en San Miguel de Tucumán para mejorar el servicio de agua potable y su rendimiento en la comunidad.',
             'Las tareas de mantenimiento no se interrumpirá el suministro en San Miguel de Tucumán y la red seguirá funcionando sin cortes.',
        ):
            with self.subTest(body=body):
                r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:
                              index() if u==SAT_INDEX else article(body=body))
                self.assertEqual(r['notices'],[])

    def test_sat_ambiguous_two_towns_rejected(self):
        body=('Se interrumpirá el suministro de agua potable en San Miguel de Tucumán '
              'y Yerba Buena debido a reparaciones del sistema de bombeo municipal.')
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=lambda u:
                      index() if u==SAT_INDEX else article(body=body))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'location_missing_or_ambiguous')

    def test_santiago_index_month_and_dated_article(self):
        body=('Aguas de Santiago informa que se interrumpirá el servicio de agua '
              'en La Banda por mantenimiento de una red. La medida afectará '
              'únicamente a los sectores indicados en este comunicado.')
        r=w.collect_one('aguas_santiago_novedades',STAMP,fetcher=lambda u:
                      index('sde') if u==SDE_INDEX else article(
                          title=SDE_TITLE,body=body,meta=False))
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['article_links_seen'],1)
        self.assertEqual(r['notices'][0]['locality_hint'],'La Banda')
        self.assertEqual(r['notices'][0]['published_on'],'2026-11-16')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_santiago_old_index_skipped(self):
        calls=[]
        def fetch(u):
            calls.append(u)
            if u==SDE_INDEX:return index('sde',day='02 NOV. 2026')
            raise AssertionError('old article should not be fetched')
        r=w.collect_one('aguas_santiago_novedades',STAMP,fetcher=fetch)
        self.assertEqual(r['status'],'stale')
        self.assertEqual(r['articles_skipped_old'],1)
        self.assertEqual(r['articles_checked'],0)
        self.assertEqual(len(calls),1)

    def test_santiago_publication_date_mismatch(self):
        r=w.collect_one('aguas_santiago_novedades',STAMP,fetcher=lambda u:
                      index('sde') if u==SDE_INDEX else article(
                          title=SDE_TITLE,day='2026-11-15'))
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['source_attempts'][0]['result'],'index_article_date_mismatch')

    def test_reject_untrusted_links(self):
        untrusted=(index(url='https://evil.example/noticias/fake')+
                   index(url='http://aguasdeltucuman.com.ar/noticias/fake')+
                   index('sde',url='https://evil.example/nota/1/fake')+
                   index('sde',url='http://aguasdesantiago.com.ar/nota/1/fake'))
        self.assertEqual(w._regional_index(untrusted,SAT_INDEX,'sat_tucuman_noticias'),[])
        self.assertEqual(w._regional_index(untrusted,SDE_INDEX,'aguas_santiago_novedades'),[])

    def test_source_failure_does_not_make_false_normal_report(self):
        r=w.collect_one('aguas_santiago_novedades',STAMP,fetcher=lambda _: (_ for _ in ()).throw(OSError('blocked')))
        self.assertEqual(r['status'],'unverified')
        self.assertIn('no se pudo',r['message'].lower())
        self.assertEqual(r['notices'],[])

    def test_http_429_preserves_partial_diagnostic(self):
        def fetch(u):
            if u==SAT_INDEX: return index()
            raise HTTPError(u,429,'rate limited',None,None)
        r=w.collect_one('sat_tucuman_noticias',STAMP,fetcher=fetch)
        self.assertTrue(r['rate_limited'])
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['source_attempts'][0]['http_status'],429)
        self.assertEqual(r['notices'],[])


if __name__=='__main__':unittest.main()

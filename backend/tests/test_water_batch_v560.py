"""v5.60: live v5.59 feed regressions and safe ABSA location/time precision."""
import unittest
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

DAY_BEFORE='2026-11-18T19:00:00Z'
DAY_AFTER='2026-11-20T01:21:35Z' # Nov 19, 22:21 local
LUBO='https://www.aguasbonaerenses.com.ar/noticias/5124'
MIL_NEW='https://www.aguasbonaerenses.com.ar/noticias/5123'
MIL_OLD='https://www.aguasbonaerenses.com.ar/noticias/5120'
RODRIGUEZ='https://www.aguasbonaerenses.com.ar/noticias/5122'


def release(day,header,text):
    return f'<html><h1>{header}</h1><div>{day}</div><p>{text}</p></html>'


def mil_new(city=''):
    return release('18-11-2026','Barrio Mil Viviendas: Trabajos programados',
       'Mañana jueves 19, se realizarán trabajos sobre la red de agua '
       'en calle Carlos Casares entre Italia y Lugones. Las tareas afectarán '
       'con baja presión y posible falta de agua al Barrio Mil Viviendas '
       'a partir de las 8:30 y hasta las 15:00 horas, aproximadamente. '+city)


def mil_old(city='San Fernando',address='Carlos Casares entre Italia y Lugones',day='18-11-2026'):
    return release(day,'Mil Viviendas: trabajos sobre la red de agua',
       'En la jornada de hoy se trabaja sobre la cañería de agua en calle '
       +address+', en el Barrio Mil Viviendas de '+city+'. '
       'La intervención genera baja presión en la red de agua del sector.')


class WaterV560(unittest.TestCase):
    def test_dposs_existed_and_notifications_off(self):
        self.assertGreaterEqual(len(w.SOURCES),21)
        self.assertIn('dposs_tierra_del_fuego_reparaciones',w.SOURCES)
        r=w.collect_water(DAY_AFTER,fetcher=lambda _: '<html/>')
        self.assertFalse(r['notifications_enabled'])
        self.assertTrue(all(not source['notifications_enabled'] for source in r['sources'].values()))
        self.assertEqual(r['sources']['absa_buenos_aires']['parser_revision'],
                         'ABSA-CROSSREF-TIMES-v5.60')

    def test_lubo_city_recovered_from_same_official_article(self):
        html=release('19-11-2026','Barrio Lubo: baja presión en la red de agua',
           'Una cuadrilla interviene sobre una perforación de agua para resolver '
           'una falla en el tablero de control ocasionando baja presión en la red '
           'de distribución de agua del barrio Lubo, en Campana.')
        notices,_=w._absa_article(html,LUBO,w.checked_instant(DAY_AFTER))
        self.assertEqual(len(notices),1)
        self.assertEqual(notices[0]['locality_hint'],'Campana')
        self.assertEqual(notices[0]['area_hint'],'Barrio Lubo')
        self.assertFalse(notices[0]['notification_allowed'])

    def test_lubo_without_express_city_is_not_guessed(self):
        html=release('19-11-2026','Barrio Lubo: baja presión en la red de agua',
             'Las tareas generan baja presión en la red de agua del barrio Lubo.')
        notes,_=w._absa_article(html,LUBO,w.checked_instant(DAY_AFTER))
        self.assertEqual(notes[0]['locality_hint'],'Barrio Lubo')
        self.assertNotIn('area_hint',notes[0])

    def test_mil_viviendas_is_not_guessed_by_article_alone(self):
        notes,_=w._absa_article(mil_new(),MIL_NEW,w.checked_instant(DAY_BEFORE))
        self.assertEqual(notes[0]['locality_hint'],'Barrio Mil Viviendas')
        self.assertNotIn('area_hint',notes[0])

    def test_mil_viviendas_correlates_same_barrio_and_exact_street(self):
        index='<html><a href="/noticias/5123">5123</a><a href="/noticias/5120">5120</a></html>'
        pages={w.SOURCES['absa_buenos_aires'][2]:index,MIL_NEW:mil_new(),MIL_OLD:mil_old()}
        def fetch(url):return pages[url]
        out=w.collect_one('absa_buenos_aires',DAY_BEFORE,fetcher=fetch)
        self.assertEqual(len(out['notices']),2)
        target=next(item for item in out['notices'] if item['source_url']==MIL_NEW)
        self.assertEqual(target['locality_hint'],'San Fernando')
        self.assertEqual(target['area_hint'],'Barrio Mil Viviendas')
        self.assertEqual(target['locality_evidence_source_url'],MIL_OLD)
        self.assertEqual(target['locality_resolution'],'matched_official_absa_article_same_address')
        self.assertEqual(len({item['id'] for item in out['notices']}),2)

    def test_mil_viviendas_ref_must_match_all_three_streets(self):
        index='<html><a href="/noticias/5123">5123</a><a href="/noticias/5120">5120</a></html>'
        pages={w.SOURCES['absa_buenos_aires'][2]:index,MIL_NEW:mil_new(),
               MIL_OLD:mil_old(address='Carlos Casares entre Italia y Sarandi')}
        result=w.collect_one('absa_buenos_aires',DAY_BEFORE,fetcher=lambda url:pages[url])
        target=next(item for item in result['notices'] if item['source_url']==MIL_NEW)
        self.assertEqual(target['locality_hint'],'Barrio Mil Viviendas')
        self.assertNotIn('locality_evidence_source_url',target)

    def test_mil_viviendas_must_match_date_window(self):
        idx='<html><a href="/noticias/5123">5123</a><a href="/noticias/5120">5120</a></html>'
        pages={w.SOURCES['absa_buenos_aires'][2]:idx,MIL_NEW:mil_new(),
               MIL_OLD:mil_old(day='12-11-2026')}
        # Official reference older than freshness window is not parsed.
        out=w.collect_one('absa_buenos_aires',DAY_BEFORE,fetcher=lambda u: pages[u])
        target=next(item for item in out['notices'] if item['source_url']==MIL_NEW)
        self.assertEqual(target['locality_hint'],'Barrio Mil Viviendas')

    def test_start_end_estimate_and_time_precision(self):
        txt=('Mañana jueves 19 se realizarán trabajos programados en la red de agua '
             'en General Rodríguez que afectarán el suministro con baja presión '
             'a partir de las 8:00 y hasta las 11:00 horas, aproximadamente.')
        notes,_=w._absa_article(release('18-11-2026','General Rodríguez: Trabajos programados',txt),
                                RODRIGUEZ,w.checked_instant(DAY_BEFORE))
        self.assertEqual(notes[0]['scheduled_start'],'2026-11-19T08:00-03:00')
        self.assertIsNone(notes[0]['scheduled_end'])
        self.assertEqual(notes[0]['scheduled_end_estimate'],'2026-11-19T11:00-03:00')
        self.assertEqual(notes[0]['time_precision'],'start_known_end_estimated')
        self.assertEqual(notes[0]['status'],'scheduled_not_confirmed')

    def test_two_conflicting_official_city_mappings_do_not_guess(self):
        target={'company':'ABSA','locality_hint':'Barrio Mil Viviendas',
                'published_on':'2026-11-18','source_url':MIL_NEW,
                'kind':'planned_water_service_impact',
                'zone_detail':'Trabajos sobre la red de agua en calle Carlos Casares entre Italia y Lugones.'}
        def ref(city,url):
            return {'company':'ABSA','locality_hint':city,'area_hint':'Barrio Mil Viviendas',
                    'published_on':'2026-11-18','source_url':url,
                    'zone_detail':'Baja presion en calle Carlos Casares entre Italia y Lugones.'}
        changed=w._absa_cross_reference_city([target,ref('San Fernando',MIL_OLD),
                                              ref('Otra Ciudad','https://www.aguasbonaerenses.com.ar/noticias/5000')])
        self.assertEqual(changed[0]['locality_hint'],'Barrio Mil Viviendas')
        self.assertNotIn('locality_evidence_source_url',changed[0])

    def test_mil_viviendas_0830_to_1500_approx(self):
        notes,_=w._absa_article(mil_new(),MIL_NEW,w.checked_instant(DAY_BEFORE))
        n=notes[0]
        self.assertEqual(n['scheduled_start'],'2026-11-19T08:30-03:00')
        self.assertEqual(n['scheduled_end_estimate'],'2026-11-19T15:00-03:00')
        self.assertIsNone(n['scheduled_end'])

    def test_elapsed_estimate_is_not_still_an_upcoming_plan(self):
        early,_=w._absa_article(mil_new(),MIL_NEW,w.checked_instant(DAY_BEFORE))
        late,_=w._absa_article(mil_new(),MIL_NEW,w.checked_instant(DAY_AFTER))
        self.assertEqual(early[0]['id'],late[0]['id'])
        self.assertEqual(late[0]['status'],'publication_only_not_live')
        self.assertIn('No confirma',late[0]['message'])
        self.assertFalse(late[0]['notification_allowed'])

    def test_exact_stated_end_without_approx_is_not_estimated(self):
        t=('El jueves 19 se realizarán trabajos programados en la red de agua '
           'en General Rodríguez y afectarán el suministro desde las 08:00 '
           'y hasta las 11:00 horas.')
        n,_=w._absa_article(release('18-11-2026','General Rodríguez: Trabajos programados',t),
                            RODRIGUEZ,w.checked_instant(DAY_BEFORE))
        self.assertEqual(n[0]['scheduled_end'],'2026-11-19T11:00-03:00')
        self.assertNotIn('scheduled_end_estimate',n[0])
        self.assertEqual(n[0]['time_precision'],'start_and_end_published')

    def test_exact_end_elapsed_is_also_publication_only(self):
        t=('El jueves 19 se realizarán trabajos programados en la red de agua '
           'de General Rodríguez afectando el suministro desde las 08:00 '
           'y hasta las 11:00 horas.')
        n,_=w._absa_article(release('18-11-2026','General Rodríguez: Trabajos programados',t),
                            RODRIGUEZ,w.checked_instant(DAY_AFTER))
        self.assertEqual(n[0]['status'],'publication_only_not_live')
        self.assertFalse(n[0]['notification_allowed'])

    def test_end_before_start_does_not_create_false_window(self):
        t=('El jueves 19 se realizarán trabajos programados sobre la red de agua '
           'de General Rodríguez afectando el suministro a partir de las 17:00 '
           'y hasta las 11:00 horas.')
        n,_=w._absa_article(release('18-11-2026','General Rodríguez: Trabajos programados',t),
                            RODRIGUEZ,w.checked_instant(DAY_BEFORE))
        self.assertEqual(n[0]['scheduled_start'],'2026-11-19T17:00-03:00')
        self.assertIsNone(n[0]['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n[0])

    def test_office_hours_do_not_count_as_work_end(self):
        t=('El jueves 19 se realizarán trabajos programados de agua que '
           'afectarán la red de General Rodríguez. El horario de atención '
           'de oficina es a partir de las 08:00 y hasta las 11:00 horas.')
        n,_=w._absa_article(release('18-11-2026','General Rodríguez: Trabajos programados',t),
                            RODRIGUEZ,w.checked_instant(DAY_BEFORE))
        self.assertIsNone(n[0]['scheduled_end'])
        self.assertNotIn('scheduled_end_estimate',n[0])

    def test_past_calendar_day_is_not_relabelled_as_new_plan(self):
        n,_=w._absa_article(mil_new(),MIL_NEW,w.checked_instant('2026-11-20T20:00:00Z'))
        self.assertEqual(n,[])

    def test_older_multiday_work_is_kept_while_future_dates_remain(self):
        body=('Durante esta semana se realizarán trabajos programados sobre la '
              'red de agua de Punta Alta. Aunque no implican interrupciones '
              'podría registrarse baja presión. Martes 17: calle A. '
              'Miércoles 18: calle B. Jueves 19: calle C. Viernes 20: calle D.')
        html=release('16-11-2026','Punta Alta: Cronograma de trabajos',body)
        notes,_=w._absa_article(html,
            'https://www.aguasbonaerenses.com.ar/noticias/5114',
            w.checked_instant(DAY_AFTER))
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['kind'],'multi_day_water_works_bulletin')
        self.assertEqual(notes[0]['scheduled_dates'],
                         ['2026-11-17','2026-11-18','2026-11-19','2026-11-20'])
        self.assertFalse(notes[0]['notification_allowed'])

    def test_old_multiday_work_disappears_after_all_dates(self):
        body=('Durante esta semana se realizarán trabajos programados sobre la '
              'red de agua de Punta Alta con posible baja presión. '
              'Martes 17: calle A. Miércoles 18: calle B. '
              'Jueves 19: calle C. Viernes 20: calle D.')
        html=release('16-11-2026','Punta Alta: Cronograma de trabajos',body)
        notes,_=w._absa_article(html,
            'https://www.aguasbonaerenses.com.ar/noticias/5114',
            w.checked_instant('2026-11-21T18:00:00Z'))
        self.assertEqual(notes,[])

    def test_old_unplanned_news_is_not_revived_by_extended_lookback(self):
        html=release('16-11-2026','San Fernando: baja presión en la red',
                     'Una cuadrilla trabaja sobre la cañería de agua y '
                     'se registra baja presión en el suministro.')
        notes,pub=w._absa_article(html,MIL_OLD,w.checked_instant(DAY_AFTER))
        self.assertEqual(notes,[])
        self.assertEqual(pub.isoformat(),'2026-11-16')

    def test_different_ref_city_with_same_area_does_not_override_explicit_source(self):
        target={'company':'ABSA','locality_hint':'Campana','area_hint':'Barrio Lubo',
                'published_on':'2026-11-19','source_url':LUBO,'kind':'water_service_bulletin',
                'zone_detail':'Baja presión en barrio Lubo, en Campana.'}
        changed=w._absa_cross_reference_city([target])
        self.assertEqual(changed[0]['locality_hint'],'Campana')

if __name__=='__main__':unittest.main()

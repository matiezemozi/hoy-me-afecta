"""v5.58: live-feed-derived edge cases, with offline HTML/XML fixtures."""
import sys, unittest
from pathlib import Path
from datetime import date
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW = w.checked_instant('2026-11-18T20:00:38Z')
ABSA_URL = 'https://www.aguasbonaerenses.com.ar/noticias/5120'
ARSA_URL = ('https://aguasrionegrinas.com/'
    'bariloche-arsa-realizara-tareas-en-planta-pilar-y-podria-registrarse-baja-presion-en-algunos-sectores/')
ARSA_TITLE = 'Bariloche: ARSA realizará tareas en Planta Pilar y podría registrarse baja presión'
SANTA_ROSA = 'santa_rosa_municipal_lp'
SANTA_RSS = w.SOURCES[SANTA_ROSA][2]
SANTA_APEX = 'https://santarosa.gob.ar/rss.xml'
SANTA_ARTICLE = ('https://www.santarosa.gob.ar/noticias/'
                 'santa-rosa-informa-trabajos-de-agua-potable-en-barrio-norte/')
SANTA_TITLE = 'Santa Rosa informa baja presion de agua potable en barrio norte'


def absa(body, title='Mil Viviendas: trabajos sobre la red de agua'):
    return '<html><h1>'+title+'</h1><span>18-11-2026</span><p>'+body+'</p></html>'


def arsa(body, title=ARSA_TITLE, day='18 de noviembre de 2026'):
    return '<html><h1>'+title+'</h1><span>'+day+'</span><p>'+body+'</p></html>'


def official_rss():
    return ('<rss version="2.0"><channel><item><title>'+SANTA_TITLE+'</title>'
            '<link>'+SANTA_ARTICLE+'</link>'
            '<pubDate>Wed, 18 Nov 2026 12:00:00 -0300</pubDate>'
            '</item></channel></rss>')


class FixV558(unittest.TestCase):
    def test_absa_neighborhood_is_not_locality(self):
        text=('En la jornada de hoy se trabaja sobre la cañería de agua en calle Carlos Casares '
              'entre Italia y Lugones, en el Barrio Mil Viviendas de San Fernando. '
              'La intervención genera baja presión en la red de agua del sector hasta las 15.00 horas.')
        notices,pub=w._absa_article(absa(text),ABSA_URL,NOW)
        self.assertEqual(pub,date(2026,11,18))
        self.assertEqual(len(notices),1)
        self.assertEqual(notices[0]['locality_hint'],'San Fernando')
        self.assertEqual(notices[0]['area_hint'],'Barrio Mil Viviendas')
        self.assertIn('Mil Viviendas',notices[0]['zone_detail'])
        self.assertEqual(notices[0]['status'],'publication_only_not_live')
        self.assertFalse(notices[0]['notification_allowed'])

    def test_absa_no_remap_without_official_city(self):
        text=('Se trabaja sobre la red de agua en el barrio Mil Viviendas, '
              'donde se registra baja presión hasta la normalización.')
        notices,_=w._absa_article(absa(text),ABSA_URL,NOW)
        self.assertEqual(notices[0]['locality_hint'],'Mil Viviendas')
        self.assertNotIn('area_hint',notices[0])

    def test_absa_different_city_not_san_fernando(self):
        text=('Se trabaja sobre la red de agua en el Barrio Mil Viviendas de Tandil, '
              'donde se registra baja presión en el suministro.')
        notices,_=w._absa_article(absa(text),ABSA_URL,NOW)
        self.assertEqual(notices[0]['locality_hint'],'Mil Viviendas')
        self.assertNotIn('area_hint',notices[0])

    def test_arsa_explicit_same_day_window_is_preserved_not_live(self):
        text=('Aguas Rionegrinas informa que este miércoles se realizarán tareas de limpieza '
              'de un decantador en la Planta Potabilizadora Pilar de Bariloche, '
              'entre las 13 y las 17 horas. Durante los trabajos podría registrarse '
              'baja presión o servicio intermitente en Reina Mora, Entre Cerros y Lomas del Cauquén.')
        notes,pub=w._arsa_article(arsa(text),ARSA_URL,NOW)
        self.assertEqual(pub,date(2026,11,18))
        self.assertEqual(len(notes),1)
        note=notes[0]
        self.assertEqual(note['scheduled_start'],'2026-11-18T13:00-03:00')
        self.assertEqual(note['scheduled_end'],'2026-11-18T17:00-03:00')
        self.assertEqual(note['scheduled_date'],'2026-11-18')
        self.assertEqual(note['time_precision'],'published_same_day_work_window_not_live')
        self.assertEqual(note['status'],'publication_only_not_live')
        self.assertFalse(note['notification_allowed'])

    def test_arsa_weekday_mismatch_does_not_assign_hours(self):
        text=('Aguas Rionegrinas informa que este martes se realizarán tareas en la '
              'Planta Potabilizadora de Bariloche entre las 13 y las 17 horas, '
              'con posible baja presión en los barrios de la ciudad.')
        notes,_=w._arsa_article(arsa(text),ARSA_URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertIsNone(notes[0]['scheduled_start'])
        self.assertIsNone(notes[0]['scheduled_end'])

    def test_arsa_rejects_invalid_hour_window(self):
        self.assertIsNone(w._arsa_reported_same_day_work_window([
            'Este miércoles se realizarán tareas en la Planta Potabilizadora '
            'entre las 17 y las 13 horas.'],date(2026,11,18)))
        self.assertIsNone(w._arsa_reported_same_day_work_window([
            'Este miércoles se realizarán tareas en la Planta Potabilizadora '
            'entre las 25 y las 26 horas.'],date(2026,11,18)))

    def test_arsa_office_hours_not_work_window(self):
        text=('Aguas Rionegrinas informa que este miércoles se realizarán tareas en la '
              'Planta Potabilizadora de Bariloche. Durante las tareas podría registrarse '
              'baja presión. El horario de atención al público es entre las 13 y las 17 horas.')
        # Matching hours in the same paragraph are ambiguous with office hours.
        # This should not be attributed to the water work.
        got=w._arsa_reported_same_day_work_window([text],date(2026,11,18))
        self.assertIsNone(got)

    def test_arsa_does_not_take_neighbor_paragraph_hour(self):
        paras=['Este miércoles se realizarán tareas en la planta potabilizadora de Bariloche.',
               'La oficina atiende al público entre las 13 y las 17 horas.']
        self.assertIsNone(w._arsa_reported_same_day_work_window(paras,date(2026,11,18)))

    def test_santa_rosa_http_403_fallback_to_official_apex(self):
        calls=[]
        article=('<html><meta property="article:published_time" content="2026-11-18T11:00:00-03:00">'
                 '<h1>'+SANTA_TITLE+'</h1><p>La Municipalidad de Santa Rosa informa que '
                 'el suministro de agua potable registra baja presión en sectores del barrio norte '
                 'por reparaciones de un acueducto.</p></html>')
        def fetch(url):
            calls.append(url)
            if url==SANTA_RSS:raise HTTPError(url,403,'Forbidden',{},None)
            if url==SANTA_APEX:return official_rss()
            if url==SANTA_ARTICLE:return article
            raise AssertionError(url)
        r=w.collect_one(SANTA_ROSA,'2026-11-18T20:00:38Z',fetcher=fetch)
        self.assertEqual(calls,[SANTA_RSS,SANTA_APEX,SANTA_ARTICLE])
        self.assertEqual(r['index_mode'],'official_apex_rss_fallback')
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['rss_items_seen'],1)
        self.assertEqual(len(r['notices']),1)
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_santa_rosa_two_http_failures_are_explained(self):
        def fetch(url):raise HTTPError(url,403 if url==SANTA_RSS else 404,'',{},None)
        r=w.collect_one(SANTA_ROSA,'2026-11-18T20:00:38Z',fetcher=fetch)
        self.assertEqual(len(r['index_attempts']),2)
        self.assertEqual(r['index_attempts'][0]['http_status'],403)
        self.assertEqual(r['index_attempts'][1]['http_status'],404)
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])
        self.assertIn('404',r['message'])

    def test_santa_rosa_rate_limit_does_not_retry(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            raise HTTPError(url,429,'Too many requests',{},None)
        r=w.collect_one(SANTA_ROSA,'2026-11-18T20:00:38Z',fetcher=fetch)
        self.assertEqual(calls,[SANTA_RSS])
        self.assertEqual(r['index_attempts'][0]['http_status'],429)

    def test_santa_rosa_invalid_xml_does_not_retry(self):
        calls=[]
        def fetch(url):calls.append(url);return '<DOCTYPE>'
        r=w.collect_one(SANTA_ROSA,'2026-11-18T20:00:38Z',fetcher=fetch)
        self.assertEqual(calls,[SANTA_RSS])
        self.assertEqual(r['status'],'unverified')

    def test_all_20_sources_stay_read_only(self):
        result=w.collect_water('2026-11-18T20:00:38Z',fetcher=lambda _: '')
        self.assertEqual(len(result['sources']),21)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(not x['notifications_enabled'] for x in result['sources'].values()))

if __name__=='__main__':unittest.main()

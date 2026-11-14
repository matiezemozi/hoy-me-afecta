"""GitHub v5.35 Bariloche regression: date and hours separated by two paragraphs."""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w
from test_water_batch_v533 import STAMP, NOW

URL='https://aguasrionegrinas.com/bariloche-arsa-ejecutara-trabajos-para-fortalecer-la-red-de-agua-potable-en-el-sector-de-riberas-del-nireco/'
INTRO=('Aguas Rionegrinas informa que este jueves 12 de noviembre se realizaran trabajos de empalme '
       'de caneria en Bariloche, una intervencion destinada a fortalecer la infraestructura y '
       'optimizar el funcionamiento de la red de distribucion de agua potable.')
LOCATION=('Las tareas se ejecutaran sobre calle 7 y La Habana, en el barrio Riberas del Nireco. '
          'Los trabajos son para mejorar la red en ese sector.')
TIME='Los trabajos comenzaran a las 8 y se extenderan hasta las 18 horas, aproximadamente.'
IMPACT='Para llevar adelante estas tareas sera necesario afectar temporalmente la prestacion del servicio en el barrio Quimey Ruca.'

def article(*paragraphs):
    return ('<html><h1>Bariloche: ARSA ejecutara trabajos para fortalecer la red de agua potable</h1>'
            '11 noviembre, 2026'+''.join('<p>'+p+'</p>' for p in paragraphs)+'</html>')

class PublishedBarilocheRegression(unittest.TestCase):
    def test_two_intervening_paragraphs_real_publication_shape(self):
        notes,_=w._arsa_article(article(INTRO,LOCATION,TIME,IMPACT),URL,NOW)
        self.assertEqual(len(notes),1)
        notice=notes[0]
        self.assertEqual(notice['scheduled_start'],'2026-11-12T08:00-03:00')
        self.assertIsNone(notice['scheduled_end'])
        self.assertEqual(notice['scheduled_end_estimate'],'2026-11-12T18:00-03:00')
        self.assertEqual(notice['time_precision'],'start_known_end_estimated')
        self.assertFalse(notice['notification_allowed'])

    def test_no_harvest_from_another_dated_task_in_second_neighbor(self):
        other='El viernes 13 de noviembre los trabajos comenzaran a las 9 y finalizaran a las 13.'
        notes,_=w._arsa_article(article(INTRO, LOCATION, other, IMPACT),URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertIsNone(notes[0]['scheduled_start'])
        self.assertEqual(notes[0]['time_precision'],'date_only')

    def test_no_harvest_from_distant_unrelated_task(self):
        filler='Los equipos continúan su trabajo en la zona de la red de distribución de agua potable.'
        notes,_=w._arsa_article(article(INTRO, LOCATION, filler, filler, TIME, IMPACT),URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertIsNone(notes[0]['scheduled_start'])

    def test_no_harvest_from_office_hours(self):
        office='La oficina de atención al público comenzará a las 8 y finalizará a las 18 horas.'
        notes,_=w._arsa_article(article(INTRO, LOCATION, office, IMPACT),URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertIsNone(notes[0]['scheduled_start'])

    def test_dated_article_but_no_published_hours(self):
        notes,_=w._arsa_article(article(INTRO, LOCATION, IMPACT),URL,NOW)
        self.assertEqual(len(notes),1)
        self.assertIsNone(notes[0]['scheduled_start'])

    def test_end_to_end_category_article_and_non_live_status(self):
        title='Bariloche: ARSA ejecutara trabajos para fortalecer la red de agua potable'
        listing=('<html><div><span>11 noviembre, 2026</span>'
                 '<a href="'+URL+'">'+title+'</a></div></html>')
        def fetch(url):
            if url == w.SOURCES['aguas_rionegrinas_arsa'][2]:
                return listing
            if url == URL:
                return article(INTRO, LOCATION, TIME, IMPACT)
            raise ValueError(url)
        result=w.collect_one('aguas_rionegrinas_arsa',STAMP,fetcher=fetch)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['parser_revision'],'ARSA-ARTICLES-v5.35.1')
        self.assertEqual(len(result['notices']),1)
        self.assertEqual(result['notices'][0]['scheduled_start'],'2026-11-12T08:00-03:00')
        self.assertEqual(result['notices'][0]['scheduled_end_estimate'],'2026-11-12T18:00-03:00')
        self.assertFalse(result['notices'][0]['notification_allowed'])

if __name__=='__main__':unittest.main()

"""DPOSS Tierra del Fuego official public repair bulletin tests (offline)."""
import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

KEY='dposs_tierra_del_fuego_reparaciones'
URL=w.SOURCES[KEY][2]
WHEN='2026-11-18T22:27:23Z'  # 19:27 Argentina time


def item(day='19/11/2026', start='07:00', end='12:30',
         pub='18/11/2026', location='Ushuaia', address='Perito Moreno y Gendarme',
         kind='Programado', body=None):
    if body is None:
        body=('La Dirección Provincial de Obras y Servicios Sanitarios informa que '
              'por trabajos programados en la red de distribución de agua potable '
              'podrá registrarse baja presión o falta de suministro en sectores '
              'aledaños a los trabajos. Se recomienda cuidar las reservas de agua.')
    return (f'<section>Publicada el: {pub} 15:20 '
            f'<span>Tipo de corte: {kind}</span> '
            f'<span>Localidad: {location}</span> '
            f'<span>Dirección aproximada: {address}</span> '
            f'<div>Fecha: El {day} de {start} a {end}</div> '
            f'<p>{body}</p></section>')


class DPOSS559(unittest.TestCase):
    def test_source_is_official_and_read_only(self):
        self.assertEqual(URL,'https://dposs.gob.ar/reparaciones/')
        self.assertGreaterEqual(len(w.SOURCES),21)
        self.assertFalse(w.collect_water(WHEN,fetcher=lambda _: '<html/>')['notifications_enabled'])

    def test_scheduled_future_with_explicit_city_address_and_times(self):
        result=w.collect_one(KEY,WHEN,fetcher=lambda u:'<html>'+item()+'</html>')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['records_seen'],1)
        self.assertEqual(len(result['notices']),1)
        event=result['notices'][0]
        self.assertEqual(event['locality_hint'],'Ushuaia')
        self.assertEqual(event['repair_category'],'programado')
        self.assertEqual(event['scheduled_date'],'2026-11-19')
        self.assertEqual(event['scheduled_start'],'2026-11-19T07:00-03:00')
        self.assertEqual(event['scheduled_end'],'2026-11-19T12:30-03:00')
        self.assertEqual(event['status'],'scheduled_not_confirmed')
        self.assertFalse(event['notification_allowed'])

    def test_same_day_ongoing_is_only_bulletin_not_live(self):
        html='<html>'+item(day='18/11/2026',start='19:00',end='21:30',kind='Imprevisto')+'</html>'
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:html)
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['status'],'publication_only_not_live')
        self.assertEqual(r['notices'][0]['kind'],'water_service_bulletin')
        self.assertFalse(r['notices'][0]['notification_allowed'])

    def test_finished_today_and_historical_do_not_reappear(self):
        html=('<html>'+item(day='18/11/2026',start='08:00',end='12:00',kind='Imprevisto')+
              item(day='06/11/2026',start='10:00',end='12:00',pub='06/11/2026')+'</html>')
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:html)
        self.assertEqual(r['status'],'stale')
        self.assertEqual(len(r['notices']),0)
        self.assertEqual(r['records_completed_today'],1)
        self.assertEqual(r['records_skipped_old'],1)

    def test_individual_records_keep_their_own_city_and_event_id(self):
        html=('<html>'+item(address='Calle A y B')+
              item(location='Tolhuin',address='Calle C y D',start='07:30')+
              item(address='Calle F y G',start='08:00')+'</html>')
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:html)
        self.assertEqual([x['locality_hint'] for x in r['notices']],['Ushuaia','Tolhuin','Ushuaia'])
        self.assertEqual(len({x['id'] for x in r['notices']}),3)
        self.assertTrue(all(x['source_url']==URL for x in r['notices']))

    def test_no_impact_or_only_sanitation_are_not_water_outages(self):
        body='La DPOSS informa obras de infraestructura cloacal. Se realizó la reparación de desagües.'
        html='<html>'+item(body=body)+item(address='Calle C y D',body='No se registrarán cortes de agua potable ni baja presión.')+'</html>'
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:html)
        self.assertEqual(len(r['notices']),0)
        self.assertEqual(r['records_skipped_without_water_impact'],2)

    def test_incomplete_record_does_not_borrow_dates_from_next(self):
        partial='<section>Publicada el: 18/11/2026 12:00 Tipo de corte: Programado Localidad: Ushuaia Dirección aproximada: Avenida Central</section>'
        r=w.collect_one(KEY,WHEN,fetcher=lambda _: '<html>'+partial+item(location='Tolhuin')+'</html>')
        self.assertEqual(len(r['notices']),1)
        self.assertEqual(r['notices'][0]['locality_hint'],'Tolhuin')
        self.assertEqual(r['records_skipped_invalid'],1)

    def test_future_unplanned_record_is_not_scheduled(self):
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:'<html>'+item(kind='Imprevisto')+'</html>')
        self.assertEqual(len(r['notices']),0)

    def test_official_page_without_structured_data_is_unverified(self):
        r=w.collect_one(KEY,WHEN,fetcher=lambda _:'<html><h1>DPOSS</h1>Estado del servicio</html>')
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])

    def test_http_failure_is_isolated_and_code_preserved(self):
        def fail(url): raise HTTPError(url,403,'Forbidden',{},None)
        r=w.collect_one(KEY,WHEN,fetcher=fail)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['source_attempts'][0]['http_status'],403)
        self.assertFalse(r['notices'])

if __name__=='__main__': unittest.main()

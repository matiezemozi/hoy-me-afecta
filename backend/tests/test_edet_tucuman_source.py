"""Regression tests for official EDET Tucuman schedules and ENRESE fallback."""
import unittest
from datetime import date
from provincial_outages import PROVIDERS, collect_one, _parse_edet, _instant

DATE = '2026-11-09T15:00:00Z'
EDET_URL = PROVIDERS['edet_tucuman'][2]


def card(town='LAS CEJAS', iso='2026-11-10', start='08:00', end='12:00',
         zone='LOS PEREYRA', count='7', status='APROBADA', explicit_date=None,
         description='881020 SO BRS (P) LR Normalizar Set 7552 Los Pereyra'):
    day = explicit_date if explicit_date is not None else date.fromisoformat(iso).strftime('%d/%m/%Y')
    return f'''<section><h5>{town}</h5><p>{day}</p><p>{iso}</p>
    <p>access_time {start} a {end}</p><p>expand_more access_time</p>
    <h6>Horario:</h6><p>Desde {start} hasta {end}</p>
    <p>location_on</p><h6>Zona:</h6><p>{zone}</p>
    <p>flag</p><h6>Sucursal:</h6><p>{town}</p>
    <p>description</p><h6>Descripción:</h6><p>{description}</p>
    <p>format_list_numbered</p><h6>Cantidad de servicios afectados:</h6><p>{count}</p>
    <p>beenhere</p><h6>Estado de la tarea:</h6><p>{status}</p></section>'''


class EDETTests(unittest.TestCase):
    def test_strict_future_approved_with_affected_services(self):
        html = '<h1>Tareas programadas y Novedades de suministro</h1>' + (
            card() + card('TAFI DEL VALLE','2026-11-11','07:30','11:30',
                          'Centro El Mollar', '228') +
            card('LULES', '2026-11-08','08:00','12:00',
                 'Zona de calle 12 de octubre fuera de servicio','96','EJECUTADA'))
        out = collect_one('edet_tucuman',DATE,fetcher=lambda url: html)
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['records_checked'], 3)
        self.assertEqual(out['parser_revision'], 'EDET-WEB-v5.24')
        self.assertEqual({n['locality_hint'] for n in out['notices']},
                         {'LAS CEJAS','TAFI DEL VALLE'})
        self.assertEqual(out['notices'][0]['source_url'], EDET_URL)
        self.assertEqual(out['notices'][1]['province'],'Tucumán')
        self.assertTrue(all(n['status']=='scheduled_not_confirmed' for n in out['notices']))

    def test_rejects_cancelled_zero_count_and_no_service_effect(self):
        html = '<h1>Tareas Programadas</h1>' + (
            card(iso='2026-11-10',status='CANCELADA')+
            card(iso='2026-11-11',count='0')+
            card(iso='2026-11-12',zone='Tarea de mantenimiento sin afectar el servicio')+
            card(iso='2026-11-13',count='')+
            card(iso='2026-11-14',zone=''))
        out = collect_one('edet_tucuman',DATE,fetcher=lambda _:html)
        self.assertEqual(out['status'],'ok')
        self.assertEqual(out['notices'],[])

    def test_rejects_inconsistent_dates_and_hours(self):
        html = '<h1>Tareas programadas</h1>' + (
            card(iso='2026-11-10',explicit_date='11/11/2026')+
            card(iso='2026-11-11',start='13:00',end='08:00')+
            card(iso='2026-11-12').replace('08:00 a 12:00','07:00 a 12:00'))
        out = collect_one('edet_tucuman',DATE,fetcher=lambda _:html)
        self.assertEqual(out['notices'], [])

    def test_not_joining_neighboring_cards(self):
        broken = card(iso='2026-11-10',status='APROBADA').replace(
            '<h6>Estado de la tarea:</h6><p>APROBADA',
            '<h6>Estado de la tarea:</h6><p>')
        next_one=card(iso='2026-11-11',status='EJECUTADA')
        out = collect_one('edet_tucuman',DATE,fetcher=lambda _:
                          '<h1>Tareas programadas</h1>'+broken+next_one)
        self.assertEqual(out['notices'],[])

    def test_unavailable_or_stale_not_normal(self):
        shell = '<html><body>Loading...</body></html>'
        out = collect_one('edet_tucuman',DATE,fetcher=lambda _:shell)
        self.assertEqual(out['status'],'unverified')
        out = collect_one('edet_tucuman',DATE,fetcher=lambda _:
                          '<h1>Tareas programadas</h1>'+card(iso='2026-09-10'))
        self.assertEqual(out['status'],'stale')
        self.assertEqual(out['notices'],[])

    def test_enrese_non_www_fallback_keeps_android_source_url(self):
        from provincial_outages import EDESE_ALTERNATE
        # Minimal legitimate official bulletin table. The last/notes column
        # must never appear in the notice, as it may have private customer data.
        sensitive = 'Medidor 500000001 particular electrodependiente'
        html = '''<h1>Cortes de Servicio Programados de EDESE</h1>
        <table><tr><th>Fecha</th><th>Hora Inicio</th><th>Hora Fin</th>
        <th>Trabajo</th><th>Zona</th><th>Notas</th></tr>
        <tr><td>10/11/2026</td><td>09:00</td><td>12:00</td>
        <td>Izado de columnas de MT.</td><td>Parte de La Florida.</td>
        <td>''' + sensitive + '''</td></tr></table>'''
        calls=[]
        def fetch(url):
            calls.append(url)
            if url == EDESE_ALTERNATE:
                return html
            raise OSError('First official host unavailable')
        out = collect_one('edese_santiago_del_estero',DATE,fetcher=fetch)
        self.assertEqual(out['status'],'ok', out)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1],EDESE_ALTERNATE)
        self.assertTrue(out['notices'])
        self.assertEqual(out['notices'][0]['source_url'],
                         PROVIDERS['edese_santiago_del_estero'][2])
        self.assertNotIn(sensitive,str(out['notices']))

if __name__=='__main__':
    unittest.main()

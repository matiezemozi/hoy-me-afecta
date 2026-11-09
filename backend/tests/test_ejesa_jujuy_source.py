"""Conservative EJESA Jujuy task-page regression tests (offline fixtures)."""
import unittest
from provincial_outages import PROVIDERS, _parse_ejesa, collect_one, _instant

DATE = '2026-11-09T15:00:00Z'
URL = PROVIDERS['ejesa_jujuy'][2]


def card(town, iso_day, time_start, time_end, zone, status='APROBADA',
         explicit_day=None, description='Dist. Colectora'):
    from datetime import date
    d = date.fromisoformat(iso_day)
    day = explicit_day or d.strftime('%d/%m/%Y')
    return f"""<section><h5>{town}</h5><p>{day}</p><p>{iso_day}</p>
      <span>access_time</span><p>{time_start} a {time_end}</p><div>expand_more</div>
      <div>access_time</div><h6>Horario:</h6><p>Desde {time_start} hasta {time_end}</p>
      <div>location_on</div><h6>Zona:</h6><p>{zone}</p>
      <div>flag</div><h6>Localidad:</h6><p>{town}</p>
      <div>description</div><h6>Descripción:</h6><p>{description}</p>
      <div>beenhere</div><h6>Estado de la tarea:</h6><p>{status}</p>
    </section>"""


class EJESATests(unittest.TestCase):
    def test_approved_future_interruptions_only(self):
        html = ('<html><body><h1>Tareas Programadas</h1>' +
            card('S.S. DE JUJUY', '2026-11-10', '07:00', '11:00',
                 'Interrupcion Programada en zona de B Alto Comedero y aledaños') +
            card('SAN PEDRO DE JUJUY', '2026-11-10', '08:30', '11:00',
                 'Mapro, sin afectar el servicio') +
            card('PERICO', '2026-11-11', '09:00', '14:00',
                 'Interrupcion Programada en zona de Severino y Aeroclub') +
            card('PERICO', '2026-11-08', '08:00', '13:00',
                 'Interrupcion Programada en zona Ruta N° 2', 'EJECUTADA') +
            '</body></html>')
        got = collect_one('ejesa_jujuy', DATE, fetcher=lambda url: html)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(got['records_checked'], 4)
        self.assertEqual(got['parser_revision'], 'EJESA-WEB-v5.23')
        self.assertEqual(len(got['notices']), 2)
        towns = {x['locality_hint'] for x in got['notices']}
        self.assertEqual(towns, {'S.S. DE JUJUY', 'PERICO'})
        self.assertTrue(all(x['status']=='scheduled_not_confirmed' for x in got['notices']))
        self.assertTrue(all(x['source_url']==URL for x in got['notices']))
        self.assertTrue(all(x['company']=='EJESA' and x['province']=='Jujuy' for x in got['notices']))

    def test_dated_future_record_not_current_outage(self):
        html='<h1>Tareas Programadas</h1>'+card('PERICO','2026-11-10','09:00','14:00',
             'Interrupción Programada en zona de El Ceibal')
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda url:html)
        self.assertEqual(got['status'], 'ok')
        self.assertEqual(got['notices'][0]['scheduled_start'], '2026-11-10T09:00-03:00')
        self.assertEqual(got['notices'][0]['scheduled_end'], '2026-11-10T14:00-03:00')

    def test_missing_zone_cancelled_or_finished_are_rejected(self):
        html='<h1>Tareas Programadas</h1>'
        html+=card('PERICO','2026-11-10','09:00','14:00','',status='APROBADA')
        html+=card('PERICO','2026-11-11','09:00','14:00',
                   'Interrupcion Programada en zona de barrio 1',status='SUSPENDIDA')
        html+=card('PERICO','2026-11-12','09:00','14:00',
                   'Interrupcion Programada en zona de barrio 2',status='EJECUTADA')
        html+=card('PERICO','2026-11-13','09:00','14:00','Mapro, sin afectar el servicio')
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda url:html)
        self.assertEqual(got['status'],'ok')
        self.assertEqual(got['notices'],[])
        self.assertIn('NO confirma',got['message'])

    def test_inconsistent_printed_date_and_clock(self):
        a=card('PERICO','2026-11-10','09:00','14:00',
               'Interrupcion Programada en zona de El Ceibal',explicit_day='11/11/2026')
        b=card('PERICO','2026-11-11','14:00','09:00',
               'Interrupcion Programada en zona de El Ceibal')
        c=card('PERICO','2026-11-12','09:00','14:00',
               'Interrupcion Programada en zona de El Ceibal').replace('09:00 a 14:00',
                                                '07:00 a 14:00')
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda _: '<h1>Tareas Programadas</h1>'+a+b+c)
        self.assertEqual(got['notices'],[])

    def test_empty_shell_and_fetch_error_are_not_normal(self):
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda _: '<html><body>Loading...</body></html>')
        self.assertEqual(got['status'],'unverified')
        self.assertEqual(got['notices'],[])
        self.assertEqual(got['source_attempts'][0]['result'],'no_complete_records')
        def bad(_): raise OSError('offline')
        got=collect_one('ejesa_jujuy',DATE,fetcher=bad)
        self.assertEqual(got['status'],'unverified')

    def test_expired_archive_is_stale_not_success(self):
        html='<h1>Tareas Programadas</h1>'+card('PERICO','2026-10-20',
                   '09:00','14:00','Interrupcion Programada en zona de una calle',
                   status='EJECUTADA')
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda _:html)
        self.assertEqual(got['status'],'stale')
        self.assertEqual(got['notices'],[])

    def test_no_cross_card_spill(self):
        blank='<h1>Tareas Programadas</h1>'+card('PERICO','2026-11-10',
                    '08:00','13:00','Interrupcion Programada en zona de una calle').replace(
                        'Estado de la tarea:</h6><p>APROBADA','Estado de la tarea:</h6><p>')
        after=card('SAN PEDRO DE JUJUY','2026-11-11','08:00','13:00',
                   'Interrupcion Programada en zona de una calle',status='EJECUTADA')
        got=collect_one('ejesa_jujuy',DATE,fetcher=lambda _:blank+after)
        self.assertEqual(got['notices'],[])


if __name__=='__main__':unittest.main()

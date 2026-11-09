"""Regresiones para la fuente publica EPRE Mendoza (EDEMSA)."""
import unittest
from provincial_outages import collect_one, _parse_edemsa_epre, _instant, PROVIDERS

WHEN = '2026-11-09T16:00:00Z'
URL = 'https://www.epremendoza.gob.ar/mantenimientos.php'


def table(*rows):
    head = '''<table><thead><tr><th>Empresa</th><th>Fecha de inicio</th>
    <th>Duración (horas)</th><th>Motivo</th><th>Descripción</th>
    <th>Distrito</th><th>Departamento</th><th>Cantidad Afectados</th>
    <th>Ver mapa</th></tr></thead><tbody>'''
    return head + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'


def record(company='EDEMSA', start='10-11-2026 08:30:00', duration='6',
           district='CARRODILLA', department='LUJAN', affected='679',
           reason='Mantenimiento Preventivo', detail='Trabajos en Subestaciones Transformadoras'):
    return (company,start,duration,reason,detail,district,department,affected,'Ver')


class MendozaEPRETests(unittest.TestCase):
    def test_regulator_public_table(self):
        self.assertEqual(PROVIDERS['edemsa_mendoza'][2], URL)
        html=table(record(),record(start='10-11-2026 14:30:00',duration='4',
                      district='SC-CHILECITO',department='SAN CARLOS',affected='155'),
                   record(company='EDESTE',affected='15'))
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda url:html)
        self.assertEqual(out['status'],'ok')
        self.assertEqual(out['parser_revision'],'EDEMSA-EPRE-v5.25')
        self.assertEqual(out['company'],'EDEMSA')
        self.assertEqual(out['province'],'Mendoza')
        self.assertEqual(out['records_checked'],2)
        self.assertEqual(len(out['notices']),2)
        n=out['notices'][0]
        self.assertEqual(n['source_url'],URL)
        self.assertEqual(n['company'],'EDEMSA')
        self.assertEqual(n['locality_hint'],'CARRODILLA')
        self.assertEqual(n['zone_detail'],'Distrito CARRODILLA; departamento LUJAN; Mendoza')
        self.assertEqual(n['scheduled_start'],'2026-11-10T08:30-03:00')
        self.assertEqual(n['scheduled_end'],'2026-11-10T14:30-03:00')
        self.assertEqual(n['status'],'scheduled_not_confirmed')
        self.assertEqual(out['notices'][1]['locality_hint'],'CHILECITO')
        self.assertIn('679',n['task'])

    def test_rejects_incomplete_zone_and_zero_affected(self):
        html=table(record(affected='0'),record(district='N/A'),
                   record(department='N/A'),record(affected=''),
                   record(affected='12.5'),record(duration='0'),
                   record(duration='13'),record(start='32-11-2026 15:00:00'))
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:html)
        self.assertEqual(out['status'],'ok')
        self.assertEqual(out['notices'],[])
        self.assertEqual(out['records_checked'],7)

    def test_future_window_stays_separate_from_current_outages(self):
        html=table(record(start='09-11-2026 08:30:00'),
                   record(start='13-11-2026 08:30:00',duration='3,5'))
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:html)
        self.assertEqual(out['status'],'ok')
        self.assertEqual(len(out['notices']),1)
        self.assertEqual(out['notices'][0]['scheduled_end'],'2026-11-13T12:00-03:00')

    def test_missing_table_remains_unverified(self):
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:'<h1>Buscar por fecha</h1>')
        self.assertEqual(out['status'],'unverified')
        self.assertEqual(out['notices'],[])
        self.assertEqual(out['source_attempts'][0]['date_markers'],0)

    def test_only_old_rows_stale(self):
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:table(record(start='01-10-2026 08:30:00')))
        self.assertEqual(out['status'],'stale')
        self.assertEqual(out['notices'],[])

    def test_deduplicates_identical_rows(self):
        html=table(record(),record())
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:html)
        self.assertEqual(out['records_checked'],2)
        self.assertEqual(len(out['notices']),1)

    def test_foreign_host_cannot_be_introduced_by_html(self):
        html=table(record(detail='<a href="https://external.invalid">Obras</a>'))
        out=collect_one('edemsa_mendoza',WHEN,fetcher=lambda _:html)
        self.assertEqual(out['notices'][0]['source_url'],URL)
        self.assertNotIn('external.invalid',out['notices'][0]['task'])

if __name__=='__main__':
    unittest.main()

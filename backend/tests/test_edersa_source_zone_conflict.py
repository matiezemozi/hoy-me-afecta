"""Safety tests for contradictory location descriptions in official EDERSA schedules."""
import unittest
from datetime import datetime

from provincial_outages import _parse_edersa, collect_one

AT = '2026-11-05T20:00:00Z'  # 17h in Argentina
NOW = datetime.fromisoformat('2026-11-05T17:00:00-03:00')
ZONE = ('Sectores comprendidos por las calles: Esandi, Pedemonte, Borgatti y '
        'Entraigas. Ruta N°3 (zona caminera, Instituto F. Física, Cayetano Arias) '
        'Ayacucho, Bvd. Contín, Alvear y Pueyrredón. Chirinos, Krause y Laprida.')


def row(locality, date='6/11', hours='13:00 a 16:00', zone=ZONE):
    return ('<tr><td>' + locality + '</td><td>' + date + '</td><td>' + hours +
            '</td><td>' + zone + '</td><td>Mantenimiento de redes de media tension</td></tr>')


def page(*rows):
    return ('<h4>Noviembre 2026</h4><table><tr><th>Localidad</th><th>Día</th>'
            '<th>Hora</th><th>Zona alcanzada</th><th>Tareas</th></tr>' +
            ''.join(rows) + '</table>')


class EdersaSourceIntegrity(unittest.TestCase):
    def test_duplicate_specific_zone_for_different_localities_is_not_presented_as_verified(self):
        html = page(row('Viedma'), row('El Bolsón', hours='14:00 a 17:00'))
        notices, checked, newest = _parse_edersa(html, NOW)
        self.assertEqual(checked, 2)
        self.assertEqual(len(notices), 2)
        self.assertEqual({n['locality_hint'] for n in notices}, {'Viedma', 'El Bolsón'})
        self.assertEqual({n['scheduled_start'] for n in notices},
                         {'2026-11-06T13:00-03:00', '2026-11-06T14:00-03:00'})
        for n in notices:
            self.assertIsNone(n['zone_detail'])
            self.assertEqual(n['status'], 'scheduled_zone_unverified')
            self.assertTrue(n['source_zone_conflict'])
            self.assertIn('Zona no verificada', n['message'])
        self.assertEqual(str(newest), '2026-11-06')

    def test_published_diagnostics_distinguish_source_conflict_from_parse_error(self):
        html = page(row('Viedma'), row('El Bolsón', hours='14:00 a 17:00'))
        result = collect_one('edersa_rio_negro', AT, fetcher=lambda _: html)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['parser_revision'], 'EDERSA-v5.18.1')
        self.assertEqual(result['source_zone_conflict_count'], 2)
        self.assertEqual(result['source_attempts'][0]['source_zone_conflict_count'], 2)
        self.assertEqual(len(result['notices']), 2)
        self.assertIn('contradicción en la fuente', result['message'])

    def test_same_zone_on_different_days_not_assumed_conflict(self):
        html = page(row('Viedma'), row('El Bolsón', date='7/11', hours='14:00 a 17:00'))
        notices, _, _ = _parse_edersa(html, NOW)
        self.assertEqual(len(notices), 2)
        self.assertTrue(all(n['zone_detail'] == ZONE for n in notices))
        self.assertTrue(all('source_zone_conflict' not in n for n in notices))

    def test_generic_description_is_not_automatically_rejected(self):
        html = page(row('Viedma', zone='Zona rural'), row('El Bolsón', zone='Zona rural'))
        notices, _, _ = _parse_edersa(html, NOW)
        self.assertEqual(len(notices), 2)
        self.assertEqual([n['zone_detail'] for n in notices], ['Zona rural', 'Zona rural'])

    def test_duplicate_same_locality_is_still_deduplicated(self):
        html = page(row('Viedma'), row('Viedma'))
        notices, _, _ = _parse_edersa(html, NOW)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['zone_detail'], ZONE)


if __name__ == '__main__':
    unittest.main()

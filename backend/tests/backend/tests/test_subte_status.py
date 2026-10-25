import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subte_status import parse_public_status, clean_text


def page(updated):
    rows = [
        ('A', 'Plaza de Mayo - San Pedrito', 'check_circle Servicio normal'),
        ('B', 'J.M. Rosas - L.N. Alem', 'warning Estación Medrano cerrada por obras.'),
        ('C', 'Constitución - Retiro', 'check_circle Servicio normal'),
        ('D', 'Catedral - Congreso', 'check_circle Servicio normal'),
        ('E', 'Retiro - Plaza de los Virreyes', 'warning Entre Ríos cerrada por obras.'),
        ('H', 'Hospitales - Facultad', 'check_circle Servicio normal'),
    ]
    return ('<html><body><h1>Estado del subte BA</h1>'
            f'<p>Última actualización: {updated}</p>' +
            ''.join(f'<section><h3>Línea {line}</h3><span>{route}</span><p>{status}</p></section>'
                    for line, route, status in rows) +
            '<h2>Qué trámite o servicio buscás</h2><div>Línea B incendio simulado</div></body></html>')


class SubteTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc)
        self.iso = self.now.isoformat().replace('+00:00', 'Z')

    def test_recent_explicit_timestamp_parses(self):
        # 13:00 Buenos Aires == 16:00 UTC
        result = parse_public_status(page('25/10/2026 13:00:00'), self.iso)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['event_count'], 2)
        self.assertEqual(len(result['lines']), 6)
        self.assertEqual(result['lines'][1]['line'], 'B')
        self.assertEqual(result['lines'][1]['state'], 'affected')

    def test_stale_source_does_not_produce_events(self):
        result = parse_public_status(page('31/08/2026 22:30:34'), self.iso)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['lines'], [])

    def test_without_date_cannot_be_presented_as_live(self):
        result = parse_public_status('<p>Estado del Subte</p><p>Línea B cerrada</p>', self.iso)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['lines'], [])

    def test_future_date_is_not_accepted(self):
        result = parse_public_status(page('25/10/2026 15:00:00'), self.iso)
        self.assertEqual(result['status'], 'stale')

    def test_unknown_schema_fails_closed(self):
        result = parse_public_status('<p>Estado del subte BA</p><p>Última actualización: 25/10/2026 13:00:00</p>', self.iso)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['lines'], [])

    def test_scripts_are_not_considered_source_data(self):
        text = clean_text('<script>Estado del subte BA Última actualización: 25/10/2026 13:00:00</script><p>hola</p>')
        self.assertEqual(text, 'hola')

    def test_subte_fetch_failure_does_not_break_electricity(self):
        import tempfile
        import json
        from unittest.mock import patch
        from collector import collect

        with tempfile.TemporaryDirectory() as dirname:
            dest = Path(dirname) / 'feed.json'
            notices = Path(dirname) / 'missing.json'
            fake_doc = {'cortes': {'cortesBajaTension': []}}
            with patch('collector.fetch_js', return_value=fake_doc):
                def broken(_timestamp):
                    raise RuntimeError('Fuera de servicio')
                collect(dest, notices, notices, fetch_subte=broken)
            result = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(result['subte']['status'], 'error')
            self.assertEqual(result['sources']['edenor']['status'], 'ok')
            self.assertEqual(result['sources']['edesur']['status'], 'ok')

    def test_bad_input_has_no_timestamp(self):
        result = parse_public_status('', self.iso)
        self.assertEqual(result['status'], 'unverified')


if __name__ == '__main__':
    unittest.main()

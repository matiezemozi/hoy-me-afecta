import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector


class CollectorTests(unittest.TestCase):
    def test_parse_representative_enre_js(self):
        doc = collector.unpack_js('var data = { cortesServicioBaja: [{partido:"LUJAN", localidad:"CENTRO", usuarios: 12}], cortesProgramados: [] };')
        events = collector.parse_enre(doc, 'edenor', '2026-10-19T12:00:00Z')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['partido'], 'LUJAN')
        self.assertEqual(events[0]['title'], 'Interrupción de baja tensión')

    def test_empty_but_valid_feed(self):
        doc = collector.unpack_js('var data = { cortesServicioBaja: [], cortesProgramados: [] };')
        self.assertEqual(collector.parse_enre(doc, 'edesur', '2026-10-19T12:00:00Z'), [])

    def test_unknown_schema_cannot_be_misread_as_no_outages(self):
        with self.assertRaises(ValueError):
            collector.parse_enre({'misc': []}, 'edenor', '2026-10-19T12:00:00Z')

    def test_no_javascript_execution(self):
        with self.assertRaises(ValueError):
            collector.unpack_js('alert(1); var data = {}')

    def test_bus_notice_must_be_fresh_and_sourced(self):
        now = datetime.now(timezone.utc)
        fmt = lambda date: date.isoformat().replace('+00:00','Z')
        valid = {'line':'57', 'branch':'Q', 'title':'Aviso comprobado', 'description':'Cambio temporal',
                 'source_url':'https://example.org/noticia','verified_at':fmt(now-timedelta(minutes=10)),
                 'ends_at':fmt(now+timedelta(hours=2))}
        stale = dict(valid, verified_at=fmt(now-timedelta(days=2)))
        with TemporaryDirectory() as folder:
            path = Path(folder)/'notice.json'
            path.write_text(json.dumps([valid,stale]), encoding='utf-8')
            self.assertEqual(len(collector.load_bus_alerts(path, fmt(now))), 1)

if __name__ == '__main__':
    unittest.main()

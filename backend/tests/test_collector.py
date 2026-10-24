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

    def test_other_line_notice_is_allowed_but_not_live(self):
        now = datetime.now(timezone.utc)
        fmt = lambda d: d.isoformat(timespec='seconds').replace('+00:00', 'Z')
        item = {'line':'60', 'branch':'', 'title':'Prueba', 'description':'Solo test',
                'source_url':'https://example.org/aviso',
                'verified_at':fmt(now-timedelta(minutes=5)),
                'ends_at':fmt(now+timedelta(hours=2))}
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'avisos.json'
            path.write_text(json.dumps([item]), encoding='utf-8')
            events = collector.load_bus_alerts(path, fmt(now))
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['line'], '60')
            self.assertEqual(events[0]['country'], 'Argentina')

    def test_expired_notice_rejected(self):
        now = datetime.now(timezone.utc)
        fmt = lambda d: d.isoformat(timespec='seconds').replace('+00:00', 'Z')
        item = {'line':'57','title':'Prueba','description':'Solo test',
                'source_url':'https://example.org/aviso',
                'verified_at':fmt(now-timedelta(minutes=5)),
                'ends_at':fmt(now-timedelta(minutes=1))}
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'avisos.json'
            path.write_text(json.dumps([item]), encoding='utf-8')
            self.assertEqual(collector.load_bus_alerts(path, fmt(now)), [])

    def test_collector_reports_multiple_lines_as_documented_not_live(self):
        from unittest.mock import patch
        now = datetime.now(timezone.utc)
        fmt = lambda d: d.isoformat(timespec='seconds').replace('+00:00', 'Z')
        manual = [
            {'line':'57', 'title':'Prueba 57','description':'No real',
             'source_url':'https://example.org/57', 'verified_at':fmt(now),
             'ends_at':fmt(now+timedelta(hours=1))},
            {'line':'60', 'title':'Prueba 60','description':'No real',
             'source_url':'https://example.org/60', 'verified_at':fmt(now),
             'ends_at':fmt(now+timedelta(hours=1))},
        ]
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'manual.json'
            target = root/'feed.json'
            source.write_text(json.dumps(manual), encoding='utf-8')
            with patch.object(collector,'now_utc',return_value=fmt(now)), \
                 patch.object(collector,'fetch_js',return_value={'cortesServicioBaja': []}):
                collector.collect(target, source)
            result = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(result['transport']['57']['status'], 'not_connected')
            self.assertEqual(result['transport']['60']['status'], 'not_connected')
            self.assertEqual(result['transport']['60']['documented_notices'], 1)
            self.assertEqual(len(result['alerts']), 2)

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

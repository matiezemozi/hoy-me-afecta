import json
import sys
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector
from bank_calendar import banking_calendar
from public_notices import import_public_notices, allowed_public_source


def iso(instant):
    return instant.isoformat(timespec='seconds').replace('+00:00', 'Z')


class NewSourceTests(unittest.TestCase):
    def test_official_bcra_2026_calendar(self):
        bank = banking_calendar(date(2026, 10, 24))
        self.assertEqual(bank['status'], 'published_reference_2026')
        self.assertEqual(bank['source_reviewed_at'], '2026-10-24')
        self.assertEqual(bank['upcoming'][0]['date'], '2026-11-09')
        self.assertEqual(bank['upcoming'][1]['date'], '2026-11-10')

    def test_does_not_claim_a_2027_calendar(self):
        bank = banking_calendar(date(2027, 1, 1))
        self.assertEqual(bank['status'], 'calendar_not_available_for_year')
        self.assertEqual(bank['upcoming'], [])

    def test_only_official_source_urls_allowed(self):
        self.assertTrue(allowed_public_source('https://www.argentina.gob.ar/ejemplo'))
        self.assertTrue(allowed_public_source('https://buenosaires.gob.ar/ejemplo'))
        self.assertFalse(allowed_public_source('https://fake.gob.ar.example.com/x'))
        self.assertFalse(allowed_public_source('http://www.argentina.gob.ar/x'))
        self.assertTrue(allowed_public_source('https://www.bna.com.ar/Home/AtencionEnSucursales', 'banco'))
        self.assertFalse(allowed_public_source('https://www.bna.com.ar/Home/AtencionEnSucursales', 'tren'))

    def item(self, now, category='tren'):
        return {'category':category, 'country':'Argentina',
                'line': 'Sarmiento', 'title':'Aviso de prueba',
                'description':'Interrupción comunicada para una estación (solo prueba)',
                'partido':'Moreno', 'localidad':'Moreno',
                'verified_at':iso(now-timedelta(minutes=10)),
                'ends_at':iso(now+timedelta(hours=2)),
                'source_url':'https://www.argentina.gob.ar/transporte/trenes-argentinos/app'}

    def imported(self, items, now):
        with TemporaryDirectory() as root:
            path = Path(root)/'avisos.json'
            path.write_text(json.dumps(items,ensure_ascii=False), encoding='utf-8')
            return import_public_notices(path, iso(now))

    def test_valid_verified_train_notice(self):
        now = datetime(2026,10,24,22,0, tzinfo=timezone.utc)
        events = self.imported([self.item(now)], now)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['category'], 'tren')
        self.assertEqual(events[0]['line'], 'Sarmiento')
        self.assertIn('valid_until', events[0])

    def test_stale_and_expired_rejected(self):
        now = datetime(2026,10,24,22,0, tzinfo=timezone.utc)
        old = self.item(now)
        old['verified_at'] = iso(now - timedelta(days=3))
        expired = self.item(now)
        expired['ends_at'] = iso(now-timedelta(minutes=1))
        self.assertEqual(self.imported([old, expired], now), [])

    def test_police_tactical_report_not_allowed(self):
        now = datetime(2026,10,24,22,0, tzinfo=timezone.utc)
        item = self.item(now, 'operativo_publico')
        item['impact_type'] = 'ubicacion_control_policial'
        self.assertEqual(self.imported([item], now), [])
        item['impact_type'] = 'acceso_restringido'
        self.assertEqual(len(self.imported([item], now)), 1)

    def test_unknown_area_rejected(self):
        now = datetime(2026,10,24,22,0, tzinfo=timezone.utc)
        item = self.item(now)
        item['partido'] = ''
        item['localidad'] = ''
        self.assertEqual(self.imported([item], now), [])

    def test_feed_integrates_new_categories_without_claiming_live(self):
        now = datetime(2026,10,24,22,0,tzinfo=timezone.utc)
        with TemporaryDirectory() as folder:
            folder=Path(folder)
            public=folder/'manual.json'
            bus=folder/'bus.json'
            public.write_text(json.dumps([self.item(now)]),encoding='utf-8')
            bus.write_text('[]', encoding='utf-8')
            with patch.object(collector, 'now_utc', return_value=iso(now)), \
                 patch.object(collector, 'fetch_js', return_value={'cortesServicioBaja': []}):
                collector.collect(folder/'feed.json', bus, public)
            result=json.loads((folder/'feed.json').read_text(encoding='utf-8'))
            self.assertEqual(result['public_notice_count'],1)
            self.assertEqual(result['coverage']['trains'],'manual_notices_only')
            self.assertEqual(result['alerts'][0]['category'],'tren')
            self.assertEqual(result['banking']['status'],'published_reference_2026')


if __name__ == '__main__':
    unittest.main()

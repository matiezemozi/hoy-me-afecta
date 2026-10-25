import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bank_calendar import parse_official_calendar, refresh_official_calendar, SOURCE_REVIEWED
import collector


def html_calendar():
    rows = ''.join('<tr><td>%02d %s 2026</td><td>Motivo %d</td></tr>' % (d, month, d)
                   for d, month in [
                       (1, 'ene'), (16, 'feb'), (17, 'feb'), (23, 'mar'),
                       (24, 'mar'), (2, 'abr'), (3, 'abr'), (1, 'may'),
                       (25, 'may'), (15, 'jun'), (9, 'jul'), (10, 'jul'),
                       (17, 'ago'), (12, 'oct'), (9, 'nov'), (10, 'nov'),
                       (23, 'nov'), (7, 'dic'), (8, 'dic'), (25, 'dic')])
    return '<html><h2>Feriados bancarios de 2026</h2><table><tr><th>Fecha</th><th>Motivo</th></tr>' + rows + '</table></html>'


class BCARLiveTests(unittest.TestCase):
    NOW = '2026-10-25T15:10:32Z'

    def test_parse_realistic_table_and_sort(self):
        items = parse_official_calendar(html_calendar(), 2026)
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0]['date'], '2026-01-01')
        self.assertEqual(items[-1]['date'], '2026-12-25')
        self.assertEqual(items[-5]['date'], '2026-11-10')

    def test_official_refresh_records_provenance(self):
        data = refresh_official_calendar(self.NOW, fetch_html=html_calendar)
        self.assertEqual(data['source_retrieval'], 'ok')
        self.assertEqual(data['source_reviewed_at'], '2026-10-25')
        self.assertEqual(data['status'], 'published_reference_2026')
        self.assertEqual(data['upcoming'][0]['date'], '2026-11-09')

    def test_failed_fetch_keeps_historical_review_date(self):
        def fail():
            raise TimeoutError('simulated network failure')
        data = refresh_official_calendar(self.NOW, fetch_html=fail)
        self.assertEqual(data['source_retrieval'], 'error')
        self.assertEqual(data['source_reviewed_at'], SOURCE_REVIEWED)
        self.assertIn('No se pudo verificar', data['message'])

    def test_few_rows_cannot_masquerade_as_complete_year(self):
        data = refresh_official_calendar(self.NOW, fetch_html=lambda: '<table><tr><td>09 nov 2026</td><td>Feriado</td></tr></table>')
        self.assertEqual(data['source_retrieval'], 'error')
        self.assertEqual(data['source_reviewed_at'], SOURCE_REVIEWED)

    def test_old_year_not_claimed_current_in_2027(self):
        data = refresh_official_calendar('2027-01-04T15:10:32Z', fetch_html=html_calendar)
        self.assertEqual(data['source_retrieval'], 'not_available_for_year')
        self.assertEqual(data['upcoming'], [])

    def test_enre_missing_restoration_is_null(self):
        doc = {'cortesProgramados': [{'partido': 'PILAR', 'localidad': 'VILLA ROSA',
                                      'normalizacion': 'Sin datos', 'usuarios': 2}]}
        item = collector.parse_enre(doc, 'edenor', self.NOW)[0]
        self.assertIsNone(item['expected_restoration'])

    def test_feed_uses_bcra_fetcher_when_provided(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root/'bus.json'
            manual.write_text('[]', encoding='utf-8')
            public = root/'avisos.json'
            public.write_text('[]', encoding='utf-8')
            with patch.object(collector, 'now_utc', return_value=self.NOW), \
                 patch.object(collector, 'fetch_js', return_value={'cortesServicioBaja': []}):
                collector.collect(root/'feed.json', manual, public,
                    fetch_banking=lambda stamp: refresh_official_calendar(stamp, fetch_html=html_calendar))
            result = json.loads((root/'feed.json').read_text(encoding='utf-8'))
            self.assertEqual(result['banking']['source_retrieval'], 'ok')
            self.assertEqual(result['sources']['edenor']['status'], 'ok')
            self.assertEqual(result['subte']['status'], 'not_checked')


if __name__ == '__main__':
    unittest.main()

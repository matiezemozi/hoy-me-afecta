import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from provincial_outages import (
    EPE_LEGACY, PROVIDERS, _parse_edersa, _parse_epe, _parse_epec,
    collect_one, collect_provincial,
)
from collector import collect
from datetime import datetime

CHECK = '2026-10-31T18:00:00Z'  # 15h Argentina
NOW = datetime.fromisoformat('2026-10-31T15:00:00-03:00')


def edersa_row(locality='Maquinchao', date='2/11', hour='11:30 a 13:30'):
    return (f'<tr><td>{locality}</td><td>{date}</td><td>{hour}</td>'
            '<td>Sector San Martín a 9 de Julio</td>'
            '<td>Mantenimiento de subestaciones</td></tr>')


def edersa_page(*rows):
    return '<h4>Noviembre 2026</h4><table><tr><th>Localidad</th><th>Día</th><th>Hora</th><th>Zona alcanzada</th><th>Tareas</th></tr>' + ''.join(rows) + '</table>'


def epe_card(date='02-11-2026', locality='Rosario', zone='Barrio Centro entre calles 123'):
    return (f'<li>Localidad: {locality}<br>Inicio: {date} 08:00 hs.<br>'
            f'Fin: 11:00 hs.<br>Zona: {zone}<br>Causa: Mantenimiento<br>'
            'Corte programado</li>')


def epec_card(day='02/11/2026', locality='CORDOBA'):
    return (f'<h3>{day}</h3><div>De 08:00 a 12:00</div>'
            f'<div>Motivo: Poda</div><div>Localidad: {locality}</div>'
            '<div>Zona afectada: Barrios Centro y Alberdi.</div>')


class ProvincialSources(unittest.TestCase):
    def test_edersa_future_and_locality(self):
        items, count, newest = _parse_edersa(edersa_page(edersa_row()), NOW)
        self.assertEqual(count, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['locality_hint'], 'Maquinchao')
        self.assertEqual(items[0]['scheduled_start'], '2026-11-02T11:30-03:00')
        self.assertEqual(newest.isoformat(), '2026-11-02')

    def test_edersa_cancelled_or_incomplete_time_rejected(self):
        page = edersa_page(edersa_row('General Roca (SUSPENDIDO)') + edersa_row('Cipolletti', hour='–'))
        items, count, newest = _parse_edersa(page, NOW)
        self.assertEqual(count, 2)
        self.assertEqual(items, [])

    def test_edersa_missing_heading_not_current(self):
        items, count, newest = _parse_edersa('<table>'+edersa_row()+'</table>', NOW)
        self.assertEqual(count, 0)
        self.assertEqual(items, [])

    def test_edersa_old_archive_not_present(self):
        page = '<h4>Septiembre 2026</h4><table>' + edersa_row(date='30/9') + '</table>'
        result = collect_one('edersa_rio_negro', CHECK, fetcher=lambda u: page)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['notices'], [])

    def test_epe_parses_current_scheduled(self):
        items, seen, _ = _parse_epe(epe_card(), NOW, EPE_LEGACY)
        self.assertEqual(seen, 1)
        self.assertEqual(items[0]['province'], 'Santa Fe')
        self.assertEqual(items[0]['scheduled_end'], '2026-11-02T11:00-03:00')

    def test_epe_legacy_fallback_after_dynamic_shell(self):
        urls = []
        def fetch(url):
            urls.append(url)
            if url == EPE_LEGACY:
                return epe_card()
            return '<h1>Trabajos programados</h1><p>Acá se cargan los cortes</p>'
        result = collect_one('epe_santa_fe', CHECK, fetcher=fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['notices']), 1)
        self.assertEqual(urls, [PROVIDERS['epe_santa_fe'][2], EPE_LEGACY])

    def test_epec_parses_dated_locality_and_zone(self):
        items, seen, _ = _parse_epec(epec_card(), NOW)
        self.assertEqual(seen, 1)
        self.assertEqual(items[0]['locality_hint'], 'CORDOBA')
        self.assertEqual(items[0]['scheduled_start'], '2026-11-02T08:00-03:00')

    def test_epec_does_not_infer_date(self):
        result = collect_one('epec_cordoba', CHECK, fetcher=lambda u: '<p>De 08:00 a 12:00 Motivo: Poda Localidad: CORDOBA Zona afectada: Alberdi</p>')
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])

    def test_epec_old_data_marked_stale(self):
        result = collect_one('epec_cordoba', CHECK, fetcher=lambda u: epec_card(day='13/10/2026'))
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['notices'], [])

    def test_current_empty_shell_not_implied_normal(self):
        result = collect_one('edersa_rio_negro', CHECK, fetcher=lambda u: '<h2>Cortes programados</h2>')
        self.assertEqual(result['status'], 'unverified')

    def test_error_per_provider_is_isolated(self):
        def fetch(url):
            if 'edersa' in url: return edersa_page(edersa_row())
            raise TimeoutError('sin acceso')
        items = collect_provincial(CHECK, fetcher=fetch)
        self.assertEqual(items['edersa_rio_negro']['status'], 'ok')
        self.assertEqual(items['epec_cordoba']['status'], 'unverified')
        self.assertEqual(items['epe_santa_fe']['status'], 'unverified')

    def test_dont_add_planned_to_enre_or_notifications(self):
        with TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            with patch('collector.now_utc', return_value=CHECK), \
                 patch('collector.fetch_js', side_effect=TimeoutError('internet')):
                collect(dest, Path(folder, 'missing.json'),
                        fetch_provincial=lambda t: collect_provincial(
                            t, fetcher=lambda url: edersa_page(edersa_row()) if 'edersa' in url else '<p>Noticia</p>'))
            feed = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(feed['alerts'], [])
            self.assertEqual(feed['notification_events']['events'], [])
            self.assertEqual(feed['provincial_electricity']['edersa_rio_negro']['status'], 'ok')
            self.assertFalse(feed['coverage_argentina']['national_electricity_coverage'])

    def test_no_network_in_direct_collect_by_default(self):
        with TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            with patch('collector.fetch_js', side_effect=TimeoutError('internet')):
                collect(dest, Path(folder, 'missing.json'))
            feed = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(feed['provincial_electricity']['edersa_rio_negro']['status'], 'not_checked')

    def test_dedupe_repeated_rows(self):
        page = edersa_page(edersa_row(), edersa_row())
        items, count, _ = _parse_edersa(page, NOW)
        self.assertEqual(count, 2)
        self.assertEqual(len(items), 1)


if __name__ == '__main__':
    unittest.main()

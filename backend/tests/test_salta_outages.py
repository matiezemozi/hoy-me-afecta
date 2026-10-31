import unittest
import tempfile
import json
from pathlib import Path
from collector import collect
from datetime import datetime, timezone
from unittest.mock import patch

from salta_outages import URL, collect_edesa_salta, parse_official_html

CHECK = "2026-10-31T18:00:00Z"  # 15:00 ART


def card(date, start, zone, state="PUBLICADO"):
    return ("<div><h3>SALTA Norte " + date + " " + start + "</h3>"
            "<p>Duración04:00:00</p><p>Zona" + zone + "</p>"
            "<p>Estado " + state + "</p><p>Motivo Renovación de red</p></div>")


class PlannedSalta(unittest.TestCase):
    def test_future_planned_is_allowed(self):
        html = card("01/11/2026", "07:00", "LOCALIDAD: SALTA - Barrio: norte y alrededores")
        notices, seen = parse_official_html(html, CHECK)
        self.assertEqual(seen, 1)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["province"], "Salta")
        self.assertEqual(notices[0]["locality_hint"], "SALTA")
        self.assertEqual(notices[0]["scheduled_start"], "2026-11-01T07:00-03:00")
        self.assertEqual(notices[0]["source_url"], URL)

    def test_canceled_and_executed_excluded(self):
        html = (card("01/11/2026", "07:00", "ZONA SALTA calle 123, 456", "CANCELADO")
                + card("02/11/2026", "07:00", "ZONA SALTA calle 123, 456", "EJECUTADO"))
        self.assertEqual(len(parse_official_html(html, CHECK)[0]), 0)

    def test_past_removed_without_implying_restoration(self):
        self.assertEqual(parse_official_html(card("25/10/2026", "08:00", "LOCALIDAD: SALTA - Centro"), CHECK)[0], [])

    def test_dedupe(self):
        html = card("02/11/2026", "09:00", "LOCALIDAD: CAMPO QUIJANO - Barrio Centro")
        self.assertEqual(len(parse_official_html(html + html, CHECK)[0]), 1)

    def test_bad_html_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_official_html("<html><p>Calendario de octubre</p></html>", CHECK)

    def test_exception_source_is_unverified(self):
        output = collect_edesa_salta(CHECK, fetcher=lambda: (_ for _ in ()).throw(TimeoutError("timeout")))
        self.assertEqual(output["status"], "unverified")
        self.assertEqual(output["notices"], [])

    def test_no_schedule_explicit(self):
        output = collect_edesa_salta(CHECK, fetcher=lambda: "<p>No hay cortes programados</p>")
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["notices"], [])

    def test_no_random_site_injection(self):
        output = collect_edesa_salta(CHECK, fetcher=lambda: "<script>document.write('Estado PUBLICADO')</script>")
        self.assertEqual(output["status"], "unverified")

    def test_time_window(self):
        self.assertEqual(parse_official_html(card("25/11/2026", "07:00", "LOCALIDAD: SALTA - Centro"), CHECK)[0], [])

    def test_html_labels_on_one_line(self):
        text = "<h3>SALTA Este 204/11/2026 08:00</h3>Duración04:30:00 ZonaSalta Capital: sector sur y alrededores Estado PUBLICADO MotivoObras"
        notices, seen = parse_official_html(text, CHECK)
        self.assertEqual(len(notices), 1)

class IntegracionArgentina(unittest.TestCase):
    def test_works_are_separate_from_live_alerts_and_push(self):
        fake_html = ("<h3>SALTA Centro 01/11/2026 08:00</h3>"
                     "Duración04:00:00 ZonaLOCALIDAD: SALTA - Barrio Centro"
                     " Estado PUBLICADO Motivo renovación de red")
        stamp = '2026-10-31T18:00:00Z'
        def edesa(checked_at):
            return collect_edesa_salta(checked_at, fetcher=lambda: fake_html)
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            manual = Path(folder, 'missing.json')
            with patch('collector.now_utc', return_value=stamp), patch('collector.fetch_js', side_effect=TimeoutError('network')):
                collect(dest, manual, fetch_salta=edesa)
            feed = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(feed['edesa_salta']['status'], 'ok')
            self.assertEqual(len(feed['edesa_salta']['notices']), 1)
            self.assertEqual(feed['alerts'], [])
            self.assertEqual(feed['notification_events']['events'], [])
            self.assertFalse(feed['coverage_argentina']['national_electricity_coverage'])
            self.assertIn('Salta', str(feed['coverage_argentina']))

    def test_source_failure_does_not_become_no_work(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder, 'feed.json')
            with patch('collector.fetch_js', side_effect=TimeoutError('network')):
                collect(dest, Path(folder, 'missing.json'),
                        fetch_salta=lambda stamp: (_ for _ in ()).throw(TimeoutError('offline')))
            feed = json.loads(dest.read_text(encoding='utf-8'))
            self.assertEqual(feed['edesa_salta']['status'], 'unverified')
            self.assertEqual(feed['edesa_salta']['notices'], [])


if __name__ == "__main__":
    unittest.main()

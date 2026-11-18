"""v5.56: stated ABSA start hours and expired program date safety. Offline."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

URL = 'https://www.aguasbonaerenses.com.ar/noticias/5119'
NOW = w.checked_instant('2026-11-17T22:16:06Z')


def article(text, published='17-11-2026', title='Carmen de Patagones: Trabajos programados'):
    return f'<html><h1>{title}</h1><div>{published}</div><p>{text}</p></html>'


class AbsaTimesV556(unittest.TestCase):
    def test_real_november_19_press_release_has_precise_start(self):
        text = (
            'El próximo jueves 19, se realizarán trabajos de reparación sobre una '
            'cañería de la red de agua en la intersección de Bynon y Perú, en '
            'Carmen de Patagones. Como consecuencia se verá afectado el servicio '
            'de agua en calle Lavalle entre Plaza Chacabuco y Bynon, donde '
            'se registrará baja presión o falta de agua. Las tareas comenzarán '
            'a las 07:00 y se extenderán durante toda la mañana.')
        notes, pub = w._absa_article(article(text), URL, NOW)
        self.assertEqual(pub, date(2026, 11, 17))
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note['scheduled_date'], '2026-11-19')
        self.assertEqual(note['scheduled_start'], '2026-11-19T07:00-03:00')
        self.assertIsNone(note['scheduled_end'])
        self.assertEqual(note['time_precision'], 'start_known_end_unknown')
        self.assertFalse(note['notification_allowed'])

    def test_existing_desde_las_remains_supported(self):
        text = ('El jueves 19 se realizarán trabajos de reparación sobre la red '
                'de agua de Carmen de Patagones desde las 06:30 y afectarán '
                'el suministro de usuarios en calle Lavalle.')
        notes, _ = w._absa_article(article(text), URL, NOW)
        self.assertEqual(notes[0]['scheduled_start'], '2026-11-19T06:30-03:00')

    def test_iniciaran_and_a_partir_de_are_supported(self):
        self.assertEqual(w._absa_start_clock('Los trabajos se iniciarán a las 08:15'), (8, 15))
        self.assertEqual(w._absa_start_clock('A partir de las 9 se afectará el servicio'), (9, 0))

    def test_end_time_is_not_an_inferred_start(self):
        self.assertIsNone(w._absa_start_clock('Las tareas se extenderán hasta las 14:00'))

    def test_two_distinct_start_times_cannot_describe_one_city(self):
        text = ('El jueves 19 se realizarán trabajos programados de la red '
                'de agua en Carmen de Patagones y afectarán el suministro. '
                'Las tareas comenzarán a las 07:00; la segunda obra comenzará a las 09:00.')
        notes, _ = w._absa_article(article(text), URL, NOW)
        self.assertEqual(len(notes), 1)
        self.assertIsNone(notes[0]['scheduled_start'])
        self.assertEqual(notes[0]['time_precision'], 'date_only')

    def test_absent_start_stays_unknown(self):
        text = ('El jueves 19 se realizarán trabajos programados sobre la red '
                'de agua que afectarán el suministro durante la mañana.')
        notes, _ = w._absa_article(article(text), URL, NOW)
        self.assertIsNone(notes[0]['scheduled_start'])
        self.assertIsNone(notes[0]['scheduled_end'])

    def test_related_article_time_not_borrowed(self):
        body = ('El jueves 19 se realizarán trabajos programados en la red '
                'de agua que afectarán el suministro sin horario confirmado.')
        html = article(body).replace('</html>',
               '<p>Relacionado: otros trabajos comenzarán a las 08:00 el viernes 20.</p></html>')
        notes, _ = w._absa_article(html, URL, NOW)
        self.assertEqual(len(notes), 1)
        self.assertIsNone(notes[0]['scheduled_start'])
        self.assertEqual(notes[0]['scheduled_date'], '2026-11-19')

    def test_expired_one_day_plan_does_not_become_current_event(self):
        now = w.checked_instant('2026-11-18T21:00:00Z')
        body = ('Mañana, martes 17, se realizarán trabajos programados '
                'en una cañería de agua. Estará afectado el suministro '
                'en calle Vieytes de Bahía Blanca.')
        notes, pub = w._absa_article(
            article(body, published='16-11-2026', title='Bahía Blanca: Trabajos programados'),
            URL, now)
        self.assertEqual(pub, date(2026, 11, 16))
        self.assertEqual(notes, [])

    def test_multi_day_schedule_id_stable_as_days_pass(self):
        body = ('Miércoles 18 y jueves 19 se realizarán trabajos programados '
                'en distintas calles de Bahía Blanca, afectando el suministro de agua.')
        html = article(body, title='Bahía Blanca: Trabajos programados')
        now18 = w.checked_instant('2026-11-18T12:00:00Z')
        now19 = w.checked_instant('2026-11-19T12:00:00Z')
        first, _ = w._absa_article(html, URL, now18)
        second, _ = w._absa_article(html, URL, now19)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]['id'], second[0]['id'])
        self.assertEqual(first[0]['kind'], 'multi_day_water_works_bulletin')
        self.assertEqual(second[0]['scheduled_dates'], ['2026-11-18', '2026-11-19'])
        self.assertIsNone(second[0]['scheduled_date'])
        self.assertFalse(second[0]['notification_allowed'])

    def test_expired_multiday_schedule_is_not_current(self):
        body = ('Miércoles 18 y jueves 19 se realizarán trabajos programados '
                'en la red de agua de Bahía Blanca que afectarán el suministro.')
        notes, _ = w._absa_article(
            article(body, title='Bahía Blanca: Trabajos programados', published='18-11-2026'),
            URL, w.checked_instant('2026-11-20T18:00:00Z'))
        self.assertEqual(notes, [])

    def test_source_count_and_safety_flags_unchanged(self):
        result = w.collect_water('2026-11-17T22:16:06Z',
            fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertGreaterEqual(len(result['sources']), 18)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertEqual(result['sources']['absa_buenos_aires']['parser_revision'], 'ABSA-TIMES-v5.56')


if __name__ == '__main__':
    unittest.main()

"""ABSA multi-day schedule regression tests for v5.48, entirely offline."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

NOW = w.checked_instant('2026-11-16T20:37:25Z')
ARTICLE = 'https://www.aguasbonaerenses.com.ar/noticias/5114'


def html(title, paragraphs, published='16-11-2026'):
    return ('<html><body><h1>' + title + '</h1><div>' + published + '</div>'
            + ''.join('<p>' + p + '</p>' for p in paragraphs) + '</body></html>')


class AbsaCalendarV548(unittest.TestCase):
    def test_multiple_explicit_days_not_misreported_as_one_day_outage(self):
        content = (
            'Durante el transcurso de esta semana, una empresa contratista realizara tareas '
            'sobre la red de agua de Punta Alta. Si bien los trabajos no implican '
            'interrupciones en el servicio, es posible que se registre baja presion en '
            'zonas aledanas de los sectores a intervenir. '
            'Se detalla el cronograma de tareas: Martes 17: Urquiza y Buchardo; '
            'Miercoles 18: Murature e Irigoyen; Jueves 19: Patagones y 25 de Mayo; '
            'Viernes 20: Patagones y Paso. '
            'Se solicita a las personas usuarias que cuiden las reservas de agua.')
        notes, pub = w._absa_article(
            html('Punta Alta: Trabajos programados', [content]), ARTICLE, NOW)
        self.assertEqual(pub, date(2026, 11, 16))
        self.assertEqual(len(notes), 1)
        n = notes[0]
        self.assertEqual(n['scheduled_dates'],
                         ['2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20'])
        self.assertIsNone(n['scheduled_date'])
        self.assertIsNone(n['scheduled_start'])
        self.assertIsNone(n['scheduled_end'])
        self.assertEqual(n['status'], 'publication_only_not_live')
        self.assertEqual(n['impact_type'], 'possible_low_pressure_only')
        self.assertFalse(n['notification_allowed'])
        self.assertIn('No presupone corte continuo', n['message'])

    def test_single_confirmed_calendar_day_is_preserved(self):
        text = ('Manana, martes 17, se llevaran adelante tareas de recambio de '
                'canerias en Bahia Blanca, por lo que estara afectado el suministro '
                'en las calles Vieytes y Juan Molina.')
        notes, _ = w._absa_article(
            html('Bahia Blanca: Trabajos programados', [text]), ARTICLE, NOW)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['scheduled_date'], '2026-11-17')
        self.assertEqual(notes[0]['status'], 'scheduled_not_confirmed')
        self.assertFalse(notes[0]['notification_allowed'])

    def test_no_calendar_guess_from_this_week_or_today(self):
        text = ('Durante el transcurso de esta semana, la empresa realizara '
                'trabajos sobre la red de agua. El dia de la fecha, se '
                'registrara baja presion en algunas zonas de Punta Alta.')
        notes, _ = w._absa_article(
            html('Punta Alta: Trabajos programados', [text]), ARTICLE, NOW)
        self.assertFalse(any(n.get('scheduled_date') for n in notes))

    def test_invalid_weekday_and_day_pair_is_not_a_schedule(self):
        self.assertEqual(w._absa_explicit_weekday_dates(
            ['Martes 18: obras programadas en la red de agua.'],
            date(2026, 11, 16), NOW), [])

    def test_old_publications_do_not_become_future_notices(self):
        text = ('Martes 17: se realizaran trabajos de agua en Bahia Blanca '
                'y se vera afectado el suministro de agua.')
        notes, pub = w._absa_article(
            html('Bahia Blanca: Trabajos programados', [text], '10-11-2026'),
            ARTICLE, NOW)
        self.assertEqual(pub, date(2026, 11, 10))
        self.assertEqual(notes, [])

    def test_month_boundary_dates_are_validated(self):
        now=w.checked_instant('2026-11-30T15:00:00Z')
        dates=w._absa_explicit_weekday_dates(
            ['Martes 1 de diciembre: trabajos en la red.',
             'Miercoles 2 de diciembre: otra obra.'],
            date(2026, 11, 30), now)
        self.assertEqual(dates, [date(2026,12,1), date(2026,12,2)])


if __name__ == '__main__':
    unittest.main()

class AbsaRelatedArticleSafetyV548(unittest.TestCase):
    def test_related_news_dates_do_not_change_schedule(self):
        main = ('Manana, martes 17, se realizaran trabajos programados de canerias '
                'en Bahia Blanca y estara afectado el suministro de agua.')
        related = ('Relacionado: miercoles 18, jueves 19, viernes 20, se programan '
                   'otros trabajos con baja presion en otra ciudad.')
        notes, _ = w._absa_article(
            html('Bahia Blanca: Trabajos programados', [main, related]), ARTICLE, NOW)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['scheduled_date'], '2026-11-17')
        self.assertNotIn('scheduled_dates', notes[0])

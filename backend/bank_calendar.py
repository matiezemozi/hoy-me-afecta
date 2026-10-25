"""2026 Argentina bank holiday calendar transcribed from official BCRA publication.

This is a dated reference calendar, not a live banking-availability feed.
The BCRA can revise the schedule. Do not use this as proof a particular branch is closed.
Source: https://www.bcra.gob.ar/consulta-feriados-bancarios-2026/
Consulted: 2026-10-24.
"""
from datetime import date
from zoneinfo import ZoneInfo
from datetime import datetime

SOURCE_URL = 'https://www.bcra.gob.ar/consulta-feriados-bancarios-2026/'
SOURCE_REVIEWED = '2026-10-24'
YEAR = 2026
HOLIDAYS = [
    ('2026-01-01', 'Año Nuevo'),
    ('2026-02-16', 'Carnaval'),
    ('2026-02-17', 'Carnaval'),
    ('2026-03-23', 'Día no laborable con fines turísticos'),
    ('2026-03-24', 'Día Nacional de la Memoria por la Verdad y la Justicia'),
    ('2026-04-02', 'Día del Veterano y de los Caídos en Malvinas y Jueves Santo'),
    ('2026-04-03', 'Viernes Santo'),
    ('2026-05-01', 'Día del Trabajador'),
    ('2026-05-25', 'Día de la Revolución de Mayo'),
    ('2026-06-15', 'Paso a la Inmortalidad del Gral. Martín Miguel de Güemes'),
    ('2026-07-09', 'Día de la Independencia'),
    ('2026-07-10', 'Día no laborable con fines turísticos'),
    ('2026-08-17', 'Paso a la Inmortalidad del Gral. José de San Martín'),
    ('2026-10-12', 'Día del Respeto a la Diversidad Cultural'),
    ('2026-11-09', 'Feriado nacional por visita del Papa León XIV'),
    ('2026-11-10', 'Feriado bancario por visita del Papa León XIV'),
    ('2026-11-23', 'Día de la Soberanía Nacional'),
    ('2026-12-07', 'Día no laborable con fines turísticos'),
    ('2026-12-08', 'Inmaculada Concepción de María'),
    ('2026-12-25', 'Navidad'),
]


def banking_calendar(at=None):
    """Return future dates in a published 2026 calendar, no claim of live access."""
    current = at or datetime.now(ZoneInfo('America/Argentina/Buenos_Aires')).date()
    if isinstance(current, datetime):
        current = current.astimezone(ZoneInfo('America/Argentina/Buenos_Aires')).date()
    if not isinstance(current, date):
        raise ValueError('Se esperaba una fecha')
    upcoming = [{'date': day, 'reason': label} for day, label in HOLIDAYS
                if date.fromisoformat(day) >= current][:5]
    return {
        'status': 'published_reference_2026' if current.year == YEAR else 'calendar_not_available_for_year',
        'year': YEAR,
        'country': 'Argentina',
        'source_url': SOURCE_URL,
        'source_reviewed_at': SOURCE_REVIEWED,
        'message': 'Calendario oficial consultado en la fecha indicada; no es un control en vivo de sucursales.',
        'upcoming': upcoming if current.year == YEAR else [],
    }

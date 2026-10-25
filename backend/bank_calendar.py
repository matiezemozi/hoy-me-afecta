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

# --- Consulta automatica y conservadora de la fuente oficial ---
# Esta seccion no convierte el calendario en un estado en tiempo real de sucursales.
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_PAGE_BYTES = 1_500_000
MONTHS = {
    'ene': 1, 'enero': 1, 'feb': 2, 'febrero': 2, 'mar': 3, 'marzo': 3,
    'abr': 4, 'abril': 4, 'may': 5, 'mayo': 5, 'jun': 6, 'junio': 6,
    'jul': 7, 'julio': 7, 'ago': 8, 'agosto': 8, 'sep': 9, 'sept': 9,
    'septiembre': 9, 'set': 9, 'setiembre': 9, 'oct': 10, 'octubre': 10,
    'nov': 11, 'noviembre': 11, 'dic': 12, 'diciembre': 12,
}


class _TableRows(HTMLParser):
    """Extrae exclusivamente celdas de tablas HTML (no scripts ni noticias)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.hidden_depth = 0
        self.current_row = None
        self.current_cell = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ('script', 'style', 'noscript'):
            self.hidden_depth += 1
        if self.hidden_depth:
            return
        if tag == 'table':
            self.table_depth += 1
        elif self.table_depth == 1 and tag == 'tr':
            self.current_row = []
        elif self.table_depth == 1 and tag in ('td', 'th') and self.current_row is not None:
            self.current_cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('script', 'style', 'noscript') and self.hidden_depth:
            self.hidden_depth -= 1
            return
        if self.hidden_depth:
            return
        if tag in ('td', 'th') and self.current_cell is not None:
            cell = ' '.join(' '.join(self.current_cell).split())
            self.current_row.append(cell)
            self.current_cell = None
        elif tag == 'tr' and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
        elif tag == 'table' and self.table_depth:
            self.table_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth and self.current_cell is not None:
            self.current_cell.append(data)


def _normalized_month(value):
    text = ''.join(c for c in unicodedata.normalize('NFKD', value.lower())
                   if not unicodedata.combining(c))
    return MONTHS.get(text.strip('.'))


def _day_from_cell(value, expected_year):
    raw = ' '.join(value.split()).strip().lower()
    match = re.fullmatch(r'(\d{1,2})\s+([a-záéíóúñ.]+)\s+(\d{4})', raw)
    if match:
        day, month, year = match.groups()
        month_value = _normalized_month(month)
        if month_value is None or int(year) != expected_year:
            return None
        try:
            return date(int(year), month_value, int(day)).isoformat()
        except ValueError:
            return None
    match = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', raw)
    if match:
        day, month, year = map(int, match.groups())
        if year != expected_year:
            return None
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def parse_official_calendar(html, year):
    """Devuelve fechas respaldadas por filas de una tabla del BCRA.

    Rechaza páginas parciales, mal formadas o sin un calendario anual completo.
    Nunca infiere eventos a partir de titulares o texto suelto.
    """
    if not isinstance(html, str) or len(html) > MAX_PAGE_BYTES:
        raise ValueError('Contenido HTML no válido o demasiado grande')
    parser = _TableRows()
    parser.feed(html)
    events = {}
    for cells in parser.rows:
        if len(cells) < 2:
            continue
        day = _day_from_cell(cells[0], year)
        if day is None:
            continue
        reason = ' '.join(cells[1].split()).strip()
        if not reason or len(reason) > 350:
            continue
        if day in events and events[day] != reason:
            raise ValueError('Fecha duplicada con motivos distintos')
        events[day] = reason
    if len(events) < 12:
        raise ValueError('No se pudo verificar una tabla anual completa del BCRA')
    return [{'date': day, 'reason': events[day]} for day in sorted(events)]


def fetch_official_html(url=SOURCE_URL):
    """Consulta solo el dominio oficial; no se aceptan redirecciones externas."""
    if url != SOURCE_URL:
        raise ValueError('URL no autorizada')
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (consulta-de-calendario-publico)',
        'Accept': 'text/html',
    })
    with urlopen(req, timeout=18) as response:
        final = urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in ('bcra.gob.ar', 'www.bcra.gob.ar'):
            raise ValueError('Redirección fuera del dominio oficial')
        raw = response.read(MAX_PAGE_BYTES + 1)
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError('Respuesta demasiado grande')
    return raw.decode('utf-8-sig', errors='replace')


def refresh_official_calendar(checked_at, fetch_html=None):
    """Obtiene el calendario oficial y registra si la consulta fue válida.

    Cuando la fuente falla conserva la referencia manual, sin renovar su fecha.
    La salida mantiene los campos que ya utiliza HOY ME AFECTA v4/v5.
    """
    moment = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('checked_at necesita zona horaria')
    local_today = moment.astimezone(ZoneInfo('America/Argentina/Buenos_Aires')).date()
    fallback = banking_calendar(local_today)
    if local_today.year != YEAR:
        fallback['source_retrieval'] = 'not_available_for_year'
        return fallback
    try:
        page = fetch_html() if fetch_html is not None else fetch_official_html()
        records = parse_official_calendar(page, YEAR)
        fallback['upcoming'] = [x for x in records if x['date'] >= local_today.isoformat()][:5]
        fallback['source_reviewed_at'] = local_today.isoformat()
        fallback['source_retrieval'] = 'ok'
        fallback['checked_at'] = checked_at
        fallback['message'] = ('Calendario del BCRA consultado y verificado automáticamente; '
                               'no indica el estado en vivo de sucursales.')
        return fallback
    except Exception as exc:
        # No borrar la referencia anterior, pero tampoco disfrazarla de nueva.
        fallback['source_retrieval'] = 'error'
        fallback['checked_at'] = checked_at
        fallback['retrieval_error'] = f'{type(exc).__name__}: {str(exc)[:140]}'
        fallback['message'] = ('No se pudo verificar nuevamente el calendario del BCRA. '
                               'Se muestra la referencia revisada el ' + SOURCE_REVIEWED + '. '
                               'Comprobar en la web oficial antes de actuar.')
        return fallback

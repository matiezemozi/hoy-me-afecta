"""EDEN and EDEA: public, dated work plans for Buenos Aires Province.

A scheduled grid improvement MAY affect service; it is never confirmation of an
active outage. This module is intentionally independent of ENRE alerts, change
tracking and Android push notifications. Avoid mistaking an empty/failing site
for normal service, and never infer a work from undated announcements.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import re
import unicodedata

SOURCES = {
    'eden_buenos_aires': ('EDEN', 'https://www.edensa.com.ar/obras-en-tu-barrio/'),
    'edea_buenos_aires': ('EDEA', 'https://www.edeaweb.com.ar/obras-en-tu-barrio/'),
}
ART = timezone(timedelta(hours=-3))
MAX_BYTES = 650_000
MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}
DATE_RE = re.compile(
    r'^(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+'
    r'(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(20\d{2}))?$', re.I)
TIME_RE = re.compile(
    r'\b([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)\s*(?:hs\.?|horas?)?\s*'
    r'(?:a|hasta|al|-)\s*([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)\s*(?:hs\.?|horas?)?\b', re.I)
CANCELED = ('suspendid', 'cancelad', 'anulad', 'no se realiz', 'reprogramad')
MAX_DAYS_AHEAD = 14


def _normalize(value):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', str(value).lower())
                   if not unicodedata.combining(ch))


def _line(value):
    return re.sub(r'\s+', ' ', value.replace('\xa0', ' ')).strip(' \t\r\n\u2013\u2014')


class _VisibleLines(HTMLParser):
    """Extract safe text lines without JavaScript or any third-party packages."""
    BREAKS = {'br', 'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
              'section', 'div', 'article', 'ul', 'ol', 'tr', 'td'}
    IGNORED = {'script', 'style', 'noscript', 'svg', 'nav', 'footer'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED:
            self.ignored.append(tag)
        if not self.ignored and tag in self.BREAKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag in self.BREAKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)

    def lines(self):
        # Keep separated work lines; deduplicate adjacent repeated heading only.
        items = [_line(x) for x in ''.join(self.parts).split('\n')]
        return [x for x in items if x]


def _work_section(lines):
    start = None
    for i, line in enumerate(lines):
        n = _normalize(line)
        if 'obras en tu barrio' in n:
            start = i + 1
            break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        n = _normalize(lines[i])
        if 'los trabajos pueden implicar' in n or 'los usuarios alcanzados' in n:
            end = i
            break
    return lines[start:end]


def _date_from_label(label, today):
    m = DATE_RE.fullmatch(_normalize(label).strip(' .:'))
    if not m:
        return None
    day, month, year = m.groups()
    month = MONTHS.get(month)
    if not month:
        return None
    years = [int(year)] if year else [today.year - 1, today.year, today.year + 1]
    possibilities = []
    for y in years:
        try:
            d = date(y, month, int(day))
        except ValueError:
            continue
        if today <= d <= today + timedelta(days=MAX_DAYS_AHEAD):
            possibilities.append(d)
    return min(possibilities) if possibilities else None


def _is_locality(line):
    if len(line) < 3 or len(line) > 90 or not any(c.isalpha() for c in line):
        return False
    # Uppercase titles only; ignore introductory text and obvious descriptions.
    stripped = line.strip(' -\u2013\u2014:')
    return (stripped == stripped.upper() and
            re.fullmatch(r'[A-ZÁÉÍÓÚÜÑ0-9 .,/()\-]+', stripped) is not None and
            not any(x in _normalize(stripped) for x in ('hora', 'trabajo', 'obras en')))


def _zone_line(text):
    # Valid work lines describe a concrete zone and a time range. No guessing.
    m = TIME_RE.search(text)
    if not m:
        return None
    sh, sm, eh, em = map(int, m.groups())
    start = time(sh, sm)
    end = time(eh, em)
    if datetime.combine(date.min, end) <= datetime.combine(date.min, start):
        return None
    if not (0 < (eh * 60 + em) - (sh * 60 + sm) <= 14 * 60):
        return None
    if any(w in _normalize(text) for w in CANCELED):
        return None
    # Strip the time from the zone to ensure the place has actual detail.
    zone = re.sub(r'\b(?:en\s+el\s+)?horario\s+de\s*$', '', text[:m.start()], flags=re.I)
    zone = re.sub(r',?\s*de\s*$', '', zone, flags=re.I)
    zone = _line(zone)
    if len(zone) < 6 or len(zone) > 700:
        return None
    return start, end, zone


def extract_works(html, key, checked_at):
    """Returns (notices, parsed_dates, examined_areas) from an official HTML page."""
    if key not in SOURCES:
        raise ValueError('Empresa no permitida')
    if not isinstance(html, str) or not html.strip() or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Página vacía o demasiado grande')
    checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if checked.tzinfo is None:
        raise ValueError('checked_at sin huso horario')
    today = checked.astimezone(ART).date()
    parser = _VisibleLines()
    parser.feed(html)
    section = _work_section(parser.lines())
    if not section:
        return [], 0, 0
    company, url = SOURCES[key]
    day = None
    locality = None
    notices = {}
    dates = 0
    areas = 0
    for line in section:
        found_date = _date_from_label(line, today)
        # Date headings may be in the past. Always clear locality when a date-like
        # heading is found, even when it is outside our future time window.
        if DATE_RE.fullmatch(_normalize(line).strip(' .:')):
            day = found_date
            locality = None
            dates += 1
            continue
        if day is None:
            continue
        if _is_locality(line):
            locality = _line(line)[:90]
            areas += 1
            continue
        if locality is None:
            continue
        candidate = _zone_line(line)
        if not candidate:
            continue
        start_t, end_t, zone = candidate
        start = datetime.combine(day, start_t, tzinfo=ART)
        end = datetime.combine(day, end_t, tzinfo=ART)
        if end <= checked.astimezone(ART):
            continue
        full = company + '|' + day.isoformat() + '|' + locality + '|' + zone + '|' + str(start_t)
        code = sha256(full.encode('utf-8')).hexdigest()[:18]
        notices[code] = {
            'id': 'ba-work-' + code, 'country': 'Argentina', 'province': 'Buenos Aires',
            'company': company, 'kind': 'planned_electricity_work',
            'status': 'scheduled_not_confirmed', 'locality_hint': locality,
            'scheduled_start': start.isoformat(timespec='minutes'),
            'scheduled_end': end.isoformat(timespec='minutes'),
            'zone_detail': zone, 'source_url': url,
            'message': 'Trabajo de red programado que puede requerir interrupción del servicio; NO confirma un corte en curso ni afectación del domicilio.',
        }
    return sorted(notices.values(), key=lambda x: (x['scheduled_start'], x['company'], x['locality_hint'], x['id'])), dates, areas


def fetch_html(url):
    if url not in (entry[1] for entry in SOURCES.values()):
        raise ValueError('Solo fuentes oficiales predefinidas')
    p = urlsplit(url)
    if p.scheme != 'https':
        raise ValueError('HTTPS obligatorio')
    request = Request(url, headers={'User-Agent': 'HoyMeAfecta/0.1 (public-source-check)'})
    with urlopen(request, timeout=16) as response:
        if urlsplit(response.geturl()).hostname != p.hostname:
            raise ValueError('Redirección a un dominio no permitido')
        if 'html' not in response.headers.get('Content-Type', '').lower():
            raise ValueError('Fuente no HTML')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('HTML demasiado grande')
    return raw.decode('utf-8-sig', errors='replace')


def collect_buenos_aires(checked_at, fetch=fetch_html):
    results = {}
    for key, (company, url) in SOURCES.items():
        entry = {
            'status': 'unverified', 'company': company, 'province': 'Buenos Aires',
            'country': 'Argentina', 'source_url': url, 'checked_at': checked_at,
            'coverage_kind': 'planned_network_work_may_interrupt_only', 'notices': [],
        }
        try:
            html = fetch(url)
            notices, dates, areas = extract_works(html, key, checked_at)
            entry['date_sections_recognized'] = dates
            entry['localities_recognized'] = areas
            entry['notices'] = notices
            if notices:
                entry['status'] = 'ok'
                entry['message'] = 'Obras programadas con fecha y zona; no prueban interrupciones actuales.'
            elif dates:
                entry['status'] = 'stale'
                entry['message'] = 'Página reconocida, sin obras futuras vigentes verificadas; no significa servicio normal.'
            else:
                entry['message'] = 'Página sin calendario completo reconocible. No significa servicio normal.'
        except Exception as exc:
            entry['message'] = 'No se pudo verificar la fuente: ' + type(exc).__name__
        results[key] = entry
    return results

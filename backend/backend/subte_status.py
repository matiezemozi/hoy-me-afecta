"""Experimental read of public subte status on the Buenos Aires City website.

IMPORTANT: A successful HTTP response is NOT evidence of current service.
Only a source-published update timestamp within 90 minutes makes the content
eligible for display. Stale, missing or unexpected pages generate no service
claims. Not a public API and may change without warning.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import re

SOURCE_URL = 'https://buenosaires.gob.ar/inicio/mis-documentos'
MAX_BYTES = 1_000_000
MAX_SOURCE_AGE = timedelta(minutes=90)
BA_TZ = ZoneInfo('America/Argentina/Buenos_Aires')


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ('style', 'script', 'svg', 'noscript'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag.lower() in ('style', 'script', 'svg', 'noscript'):
            self.hidden = max(0, self.hidden-1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def clean_text(html):
    parser = _VisibleText()
    parser.feed(html)
    return ' '.join(' '.join(parser.parts).split())


def fetch_public_page(url=SOURCE_URL):
    # Fixed official-domain endpoint only; URL must not come from user input.
    if url != SOURCE_URL:
        raise ValueError('Dominio o ruta no autorizados')
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (+public-source-reference)',
        'Accept': 'text/html',
    })
    with urlopen(req, timeout=16) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Página demasiado grande')
    return data.decode('utf-8', errors='replace')


def _parse_line_states(section):
    parts = list(re.finditer(r'(?i)\bL[ií]nea\s+([ABCDEHP])\b', section))
    result = []
    for index, match in enumerate(parts):
        line = match.group(1).upper()
        block_end = parts[index + 1].start() if index + 1 < len(parts) else len(section)
        block = section[match.end():block_end]
        state = None
        code = 'unknown'
        disruption = re.search(r'(?i)\bwarning\s+(.{8,240}?)(?:\s+\b(?:check_circle|warning|info)\b|$)', block)
        if disruption:
            state = disruption.group(1).strip(' .') + '.'
            code = 'affected'
        elif re.search(r'(?i)\bservicio normal\b', block):
            state = 'Servicio normal (según la fuente)'
            code = 'normal'
        if state and line not in {entry['line'] for entry in result}:
            result.append({'line': line, 'state': code, 'description': state})
    return result


def parse_public_status(html, checked_at):
    """Return status safely; never turn an undated page into a live alert."""
    date = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('checked_at necesita zona horaria')
    checked = date.astimezone(timezone.utc)
    text = clean_text(html)
    marker = re.search(r'(?i)Estado del subte\s+BA\s+Última actualizaci[oó]n\s*:\s*'
                       r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})', text)
    if not marker:
        return {'status': 'unverified', 'message': 'La página no publica una fecha de actualización verificable.',
                'checked_at': checked_at, 'url': SOURCE_URL, 'lines': []}
    day, month, year, timepart = marker.groups()
    published = datetime.strptime(f'{int(day):02d}/{int(month):02d}/{year} {timepart}',
                                  '%d/%m/%Y %H:%M:%S').replace(tzinfo=BA_TZ).astimezone(timezone.utc)
    published_at = published.isoformat(timespec='seconds').replace('+00:00', 'Z')
    age = checked - published
    if age > MAX_SOURCE_AGE or age < -timedelta(minutes=3):
        return {'status': 'stale', 'message': 'El estado publicado no es suficientemente reciente.',
                'checked_at': checked_at, 'source_updated_at': published_at,
                'url': SOURCE_URL, 'lines': []}
    # Limit parsing to the state widget, not the entire page (which can have news).
    section = text[marker.end():]
    end = re.search(r'(?i)\bQu[eé] tr[aá]mite|\bMomentos de vida|\bNavegaci[oó]n de pie', section)
    if end:
        section = section[:end.start()]
    states = _parse_line_states(section)
    if len(states) < 5:
        return {'status': 'unverified', 'message': 'No se pudo identificar el estado de al menos cinco líneas.',
                'checked_at': checked_at, 'source_updated_at': published_at,
                'url': SOURCE_URL, 'lines': []}
    return {'status': 'ok', 'checked_at': checked_at, 'source_updated_at': published_at,
            'url': SOURCE_URL, 'lines': states, 'event_count': sum(x['state'] == 'affected' for x in states)}


def collect_subte(checked_at):
    try:
        return parse_public_status(fetch_public_page(), checked_at)
    except Exception as exc:
        return {'status': 'error', 'checked_at': checked_at,
                'url': SOURCE_URL, 'lines': [],
                'message': f'{type(exc).__name__}: {str(exc)[:170]}'}

"""Conservative scheduled electricity work collectors for three Argentine provinces.

The three sources are public web pages, not documented APIs. Record only
published, date-verified future schedules; never infer an outage in progress.
Remote failures, empty JavaScript shells and stale archives are NOT "no outages".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import os
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlsplit

from source_javascript_diagnostics import probe_official_scripts

ART = timezone(timedelta(hours=-3))
MAX_BYTES = 2_500_000
MAX_DAYS = 14
PROVIDERS = {
    'epec_cordoba': ('EPEC', 'Córdoba', 'https://www.epec.com.ar/actualidad/trabajos-mejoras'),
    'epe_santa_fe': ('EPE', 'Santa Fe', 'https://www.epe.santafe.gov.ar/institucional/trabajos-programados'),
    'edersa_rio_negro': ('EDERSA', 'Río Negro', 'https://www.edersa.com.ar/cortes-programados/'),
}
EPE_LEGACY = 'https://www.epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPE_LEGACY_ALT = 'https://epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPEC_ALTERNATE = 'https://epec.com.ar/actualidad/trabajos-mejoras'


def _clean(s, limit=700):
    return re.sub(r'\s+', ' ', str(s or '')).strip()[:limit]


def _instant(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Se requiere fecha con zona horaria')
    return date.astimezone(ART)


def _datetime(day, hour):
    return datetime.combine(day, datetime.strptime(hour, '%H:%M').time(), ART)


def _notice(provider, province, url, locality, start, end, zone, task):
    compact = '|'.join([provider, locality, start.isoformat(), end.isoformat(), zone, task])
    return {
        'id': 'plan-' + sha256(compact.encode('utf-8')).hexdigest()[:18],
        'province': province, 'company': provider, 'country': 'Argentina',
        'kind': 'planned_electricity_work', 'status': 'scheduled_not_confirmed',
        'locality_hint': _clean(locality, 100),
        'scheduled_start': start.isoformat(timespec='minutes'),
        'scheduled_end': end.isoformat(timespec='minutes'),
        'zone_detail': _clean(zone), 'task': _clean(task, 250),
        'source_url': url,
        'message': 'Trabajo programado; no confirma interrupción actual ni afectación de domicilio.',
    }


def _filter_window(notices, now):
    # Do not transform ongoing or expired work into a current-outage report.
    unique = {}
    for x in notices:
        start = datetime.fromisoformat(x['scheduled_start'])
        if now <= start <= now + timedelta(days=MAX_DAYS):
            unique[x['id']] = x
    return sorted(unique.values(), key=lambda x: (x['scheduled_start'], x['company'], x['locality_hint']))


class _Visible(HTMLParser):
    """Text plus structural table/heading events, without JS or style content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignore = 0
        self.bits = []
        self.events = []
        self.heading = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignore += 1
            return
        if self.ignore:
            return
        if tag in ('h2', 'h3', 'h4', 'h5'):
            self.heading = []
        elif tag == 'tr':
            self.row = []
        elif tag in ('th', 'td') and self.row is not None:
            self.cell = []
        if tag in ('br', 'p', 'li', 'div', 'tr', 'td', 'h2', 'h3', 'h4', 'h5'):
            self.bits.append(' ')
            if self.cell is not None:
                self.cell.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignore = max(self.ignore - 1, 0)
            return
        if self.ignore:
            return
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(_clean(' '.join(self.cell), 1400))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.events.append(('row', self.row))
            self.row = None
        elif tag in ('h2', 'h3', 'h4', 'h5') and self.heading is not None:
            self.events.append(('heading', _clean(' '.join(self.heading), 140)))
            self.heading = None
        if tag in ('p', 'li', 'div', 'tr', 'td', 'h2', 'h3', 'h4', 'h5'):
            self.bits.append(' ')

    def handle_data(self, data):
        if self.ignore:
            return
        self.bits.append(data)
        if self.cell is not None:
            self.cell.append(data)
        if self.heading is not None:
            self.heading.append(data)


def _visible(html):
    if not isinstance(html, str) or not html.strip() or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('HTML vacío o demasiado grande')
    parser = _Visible()
    parser.feed(html)
    return parser, _clean(' '.join(parser.bits), MAX_BYTES)


def _parse_edersa(html, now):
    dom, _ = _visible(html)
    month_names = {'enero':1, 'febrero':2, 'marzo':3, 'abril':4, 'mayo':5,
                   'junio':6, 'julio':7, 'agosto':8, 'septiembre':9,
                   'setiembre':9, 'octubre':10, 'noviembre':11, 'diciembre':12}
    year = None
    month = None
    seen = 0
    items = []
    newest = None
    for kind, item in dom.events:
        if kind == 'heading':
            match = re.search(r'\b(' + '|'.join(month_names) + r')\s+(20\d\d)\b', item.lower())
            if match:
                month, year = month_names[match.group(1)], int(match.group(2))
            continue
        if not isinstance(item, list) or len(item) < 5 or month is None:
            continue
        locality, date, hour, zone, task = item[:5]
        day_match = re.fullmatch(r'(\d{1,2})/(\d{1,2})', date)
        if not day_match or int(day_match.group(2)) != month:
            continue
        try:
            day = datetime(year, month, int(day_match.group(1))).date()
        except ValueError:
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        if 'suspendid' in locality.lower() or 'cancelad' in locality.lower():
            continue
        hrs = re.search(r'(\d{1,2}:\d\d)\s*(?:a|hasta|[-–])\s*(\d{1,2}:\d\d)', hour, re.I)
        # Some EDERSA rows have multiple windows or '-' in Hora: reject until
        # we can model all intervals exactly; never guess times from free text.
        if not hrs or len(re.findall(r'\b\d{1,2}:\d{2}\b', hour)) != 2:
            continue
        try:
            start, end = _datetime(day, hrs.group(1)), _datetime(day, hrs.group(2))
        except ValueError:
            continue
        if start >= end or not _clean(zone) or not _clean(locality):
            continue
        items.append(_notice('EDERSA', 'Río Negro', PROVIDERS['edersa_rio_negro'][2],
                             locality, start, end, zone, task))
    return _filter_window(items, now), seen, newest


_EPE = re.compile(
    r'Localidad\s*:\s*(?P<locality>.*?)\s*'
    r'Inicio\s*:\s*(?P<date>\d{1,2}-\d{1,2}-20\d\d)\s*'
    r'(?P<start>\d{1,2}:\d\d)\s*hs\.?\s*'
    r'Fin\s*:\s*(?P<end>\d{1,2}:\d\d)\s*hs\.?\s*'
    r'Zona\s*:\s*(?P<zone>.*?)\s*'
    r'Causa\s*:\s*(?P<task>.*?)\s*Corte programado\b',
    re.IGNORECASE | re.DOTALL)


def _parse_epe(html, now, url):
    _, visible = _visible(html)
    items = []
    seen = 0
    newest = None
    for match in _EPE.finditer(visible):
        try:
            date = datetime.strptime(match.group('date'), '%d-%m-%Y').date()
            start, end = _datetime(date, match.group('start')), _datetime(date, match.group('end'))
        except ValueError:
            continue
        seen += 1
        newest = max(newest, date) if newest else date
        if start >= end or not _clean(match.group('zone')) or not _clean(match.group('locality')):
            continue
        items.append(_notice('EPE', 'Santa Fe', url, match.group('locality'),
                             start, end, match.group('zone'), match.group('task')))
    return _filter_window(items, now), seen, newest


_EPEC = re.compile(
    r'\bDe\s+(?P<start>\d{1,2}:\d\d)\s+a\s+(?P<end>\d{1,2}:\d\d)\s*'
    r'Motivo\s*:\s*(?P<task>.*?)\s*'
    r'Localidad\s*:\s*(?P<locality>.*?)\s*'
    r'Zona afectada\s*:\s*(?P<zone>.*?)(?=\bDe\s+\d{1,2}:\d\d\s+a\s+\d{1,2}:\d\d\b|$)',
    re.IGNORECASE | re.DOTALL)


def _parse_epec(html, now):
    _, visible = _visible(html)
    date_matches = list(re.finditer(r'(?<!\d)\d{1,2}/\d{1,2}/20\d\d(?!\d)', visible))
    if not date_matches:
        return [], 0, None
    items, seen, newest = [], 0, None
    for index, date_match in enumerate(date_matches):
        try:
            day = datetime.strptime(date_match.group(0), '%d/%m/%Y').date()
        except ValueError:
            continue
        chunk_end = date_matches[index+1].start() if index+1 < len(date_matches) else len(visible)
        chunk = visible[date_match.end():chunk_end]
        for match in _EPEC.finditer(chunk):
            seen += 1
            newest = max(newest, day) if newest else day
            try:
                start, end = _datetime(day, match.group('start')), _datetime(day, match.group('end'))
            except ValueError:
                continue
            if start >= end or not _clean(match.group('zone')) or not _clean(match.group('locality')):
                continue
            items.append(_notice('EPEC', 'Córdoba', PROVIDERS['epec_cordoba'][2],
                                 match.group('locality'), start, end,
                                 match.group('zone'), match.group('task')))
    return _filter_window(items, now), seen, newest


def fetch_html(url):
    # Official public HTTPS pages; no credentials, JS execution or bypasses.
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (piloto fuentes provinciales; contacto en repositorio)',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'es-AR,es;q=0.9',
    })
    with urlopen(req, timeout=14) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Fuente demasiado grande')
    return raw.decode('utf-8-sig', errors='replace')


class _ScriptPaths(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paths = []

    def handle_starttag(self, tag, attrs):
        if tag != 'script':
            return
        src = dict(attrs).get('src', '')
        if src and len(src) <= 400:
            self.paths.append(src)


def _diagnose_html(html, page, key):
    """Conservative bounded diagnostics, never exposing raw page text or tokens."""
    _, visible = _visible(html)
    patterns = {
        'epec_cordoba': r'(?<!\d)\d{1,2}/\d{1,2}/20\d\d(?!\d)',
        'epe_santa_fe': r'(?<!\d)\d{1,2}-\d{1,2}-20\d\d(?!\d)',
    }
    expected = patterns.get(key, '')
    dates = len(re.findall(expected, visible)) if expected else 0
    low = visible.lower()
    diag = {
        'html_bytes': len(html.encode('utf-8')),
        'date_markers': min(dates, 5000),
        'has_locality': 'localidad' in low,
        'has_zone': 'zona' in low,
        'dynamic_shell': 'acá se cargan los cortes' in low or 'aca se cargan los cortes' in low,
    }
    scanner = _ScriptPaths()
    scanner.feed(html)
    official_host = urlsplit(page).hostname or ''
    paths = []
    for raw in scanner.paths:
        absolute = urljoin(page, raw)
        parsed = urlsplit(absolute)
        # Only report script paths hosted on the same official origin.
        if parsed.hostname == official_host and parsed.scheme == 'https':
            cleaned = parsed.path[:160]  # Deliberately omit query params and credentials.
            if cleaned and cleaned not in paths:
                paths.append(cleaned)
    diag['same_origin_script_paths'] = paths[:8]
    return diag


def collect_one(key, checked_at, fetcher=None, script_fetcher=None):
    if key not in PROVIDERS:
        raise KeyError(key)
    company, province, url = PROVIDERS[key]
    now = _instant(checked_at)
    output = {'status': 'unverified', 'province': province, 'country': 'Argentina',
              'company': company, 'source_url': url, 'checked_at': checked_at,
              'coverage_kind': 'planned_outages_only', 'notices': [],
              'message': 'Sin verificación de publicaciones; no implica suministro normal.',
              'source_attempts': []}
    fetch = fetcher or fetch_html
    if key == 'epe_santa_fe':
        pages = [url, EPE_LEGACY, EPE_LEGACY_ALT]
    elif key == 'epec_cordoba':
        pages = [url, EPEC_ALTERNATE]
    else:
        pages = [url]
    problems = []
    js_probe_completed = False
    for page in pages:
        attempt = {'url': page}
        try:
            html = fetch(page)
            # Diagnostics are collected from the actual HTML returned at GitHub,
            # not from search engine snippets, so failures can be distinguished.
            attempt.update(_diagnose_html(html, page, key))
            if key == 'edersa_rio_negro':
                notices, count, newest = _parse_edersa(html, now)
            elif key == 'epe_santa_fe':
                notices, count, newest = _parse_epe(html, now, page)
            else:
                notices, count, newest = _parse_epec(html, now)
            attempt['records_checked'] = count
            if newest is not None:
                attempt['latest_published_date'] = newest.isoformat()
            if count == 0 or newest is None:
                # Probe one preidentified public JS bundle only when the server
                # cannot read complete records from the static page.
                if (key in ('epec_cordoba', 'epe_santa_fe') and not js_probe_completed
                        and (script_fetcher is not None or (fetcher is None
                             and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'))):
                    attempt['javascript_diagnostics'] = probe_official_scripts(
                        page, key, attempt.get('same_origin_script_paths', []),
                        fetcher=script_fetcher)
                    js_probe_completed = True
                attempt['result'] = ('dynamic_shell' if attempt.get('dynamic_shell')
                                     else 'no_complete_records')
                problems.append(attempt['result'])
                continue
            # A page full of old schedules is not evidence of current coverage.
            if newest < (now - timedelta(days=2)).date():
                attempt['result'] = 'stale'
                problems.append('La última fecha publicada es antigua')
                output.update(status='stale', source_url=page, records_checked=count,
                              latest_published_date=newest.isoformat())
                continue
            attempt['result'] = 'verified'
            output.update(status='ok', source_url=page, notices=notices,
                          records_checked=count, latest_published_date=newest.isoformat(),
                          message='Trabajos programados, NO confirmación de corte en curso.')
            if not notices:
                output['message'] = 'Sin trabajos futuros reconocidos en la consulta; NO confirma servicio normal.'
            return output
        except Exception as exc:
            attempt['result'] = 'fetch_or_parse_error'
            attempt['error_type'] = type(exc).__name__
            # Deliberately do not store exception strings: they can expose URLs.
            problems.append(type(exc).__name__)
        finally:
            output['source_attempts'].append(attempt)
    if output['status'] == 'stale':
        output['message'] = 'Solo se reconocieron publicaciones antiguas; no hay datos futuros verificables.'
    else:
        output['message'] = 'No se pudo verificar la fuente: ' + ', '.join(problems)[:150]
    return output


def collect_provincial(checked_at, fetcher=None):
    # One failure never blocks another distributor.
    result = {}
    for key in PROVIDERS:
        try:
            result[key] = collect_one(key, checked_at, fetcher=fetcher)
        except Exception as exc:
            company, province, url = PROVIDERS[key]
            result[key] = {'status':'unverified', 'province':province, 'company':company,
                           'source_url':url, 'checked_at':checked_at, 'notices':[],
                           'message':'Error verificando fuente: '+type(exc).__name__}
    return result

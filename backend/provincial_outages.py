"""Conservative scheduled electricity work collectors for three Argentine provinces.

The three sources are public web pages, not documented APIs. Record only
published, date-verified future schedules; never infer an outage in progress.
Remote failures, empty JavaScript shells and stale archives are NOT "no outages".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from html import unescape
from xml.etree import ElementTree
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
    'edese_santiago_del_estero': ('EDESE', 'Santiago del Estero', 'https://www.enrese.com.ar/CortesProgramados.html'),
    'epen_neuquen': ('EPEN', 'Neuquén', 'https://www.epen.gov.ar/index.php/cortes-programados/'),
}
EPE_LEGACY = 'https://www.epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPE_LEGACY_ALT = 'https://epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPEC_ALTERNATE = 'https://epec.com.ar/actualidad/trabajos-mejoras'
EPEN_RSS = 'https://www.epen.gov.ar/index.php/feed/'


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
    # The official EDERSA page occasionally repeats exactly the same long zone
    # description for different localities on the same day (e.g. Viedma and El
    # Bolson on 6 November 2026). Do not present such a geographical description
    # as verified. Keep the real, dated bulletin with an explicit uncertainty.
    return _flag_ambiguous_edersa_zones(_filter_window(items, now)), seen, newest


def _flag_ambiguous_edersa_zones(notices):
    # Restrict to long, specific descriptions: short generic phrases like
    # 'zona rural' are insufficient evidence of a mistaken source publication.
    zone_localities = {}
    for notice in notices:
        zone = _clean(notice.get('zone_detail', ''), 700).casefold()
        if len(zone) < 100:
            continue
        key = (notice['scheduled_start'][:10], zone)
        zone_localities.setdefault(key, set()).add(_clean(notice.get('locality_hint'), 100).casefold())

    for notice in notices:
        zone = _clean(notice.get('zone_detail', ''), 700).casefold()
        key = (notice['scheduled_start'][:10], zone)
        if len(zone_localities.get(key, ())) <= 1:
            continue
        # The date, company, locality and hours remain source-derived; only
        # the zone association is ambiguous, so we withhold it.
        notice['zone_detail'] = None
        notice['status'] = 'scheduled_zone_unverified'
        notice['source_zone_conflict'] = True
        notice['message'] = ('La fuente oficial publica la misma zona detallada '
                             'para distintas localidades en la misma fecha. '
                             'Zona no verificada; consultar el enlace original. '
                             'No confirma corte actual.')
    return notices


def _edese_locality(zone):
    """Conservative first locality, without fabricating a city from a street."""
    text = _clean(zone, 700).split(',')[0].strip().strip('.;')
    if not text:
        return ''
    if re.match(r'^(?:en\s+calle|entre\s+calles|ruta|camino|calle|barrio|b[°º]|zona\s+rural)\b',
                text, re.IGNORECASE):
        return ''
    # Preserve articles belonging to town names ("La Florida", "La Banda").
    if re.match(r'^parte\s+de\s+la\s+ciudad\s+de\s+', text, re.IGNORECASE):
        text = re.sub(r'^parte\s+de\s+la\s+ciudad\s+de\s+', '', text, flags=re.IGNORECASE)
    elif re.match(r'^parte\s+de\s+la\s+ciudad\s+capital\b', text, re.IGNORECASE):
        text = re.sub(r'^parte\s+de\s+la\s+', '', text, flags=re.IGNORECASE)
    else:
        text = re.sub(r'^parte\s+de\s+|^parte\s+del\s+|^parte\s+de\s+los\s+',
                      '', text, flags=re.IGNORECASE)
    text = re.sub(r'^ciudad\s+de\s+|^ciudad\s+del\s+', '', text, flags=re.IGNORECASE).strip()
    if re.fullmatch(r'ciudad\s+capital|capital', text, re.IGNORECASE):
        # Explicit provincial capital in the ENRESE bulletin.
        return 'Santiago del Estero'
    if not text or len(text) > 100 or re.match(
            r'^(?:barrio|b[°º]|ruta|zona|calle|sector|rural)\b', text, re.IGNORECASE):
        return ''
    return text


def _parse_edese(html, now):
    """Read only dated table columns (date, hours, work, zone) on ENRESE.

    The sixth column contains consumers' names, meter IDs and, sometimes,
    electrodependence information. Never retain or emit that column.
    """
    dom, visible = _visible(html)
    low = visible.casefold()
    if 'cortes de servicio programados' not in low or 'edese' not in low:
        return [], 0, None
    items, seen, newest = [], 0, None
    for event, row in dom.events:
        if event != 'row' or not isinstance(row, list) or len(row) < 5:
            continue
        date_raw, start_raw, end_raw, task, zone = row[:5]
        if not re.fullmatch(r'\d{1,2}/\d{1,2}/20\d{2}', date_raw):
            continue
        try:
            day = datetime.strptime(date_raw, '%d/%m/%Y').date()
        except ValueError:
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        if not (re.fullmatch(r'\d{1,2}:\d{2}', start_raw) and
                re.fullmatch(r'\d{1,2}:\d{2}', end_raw)):
            continue
        try:
            start, end = _datetime(day, start_raw), _datetime(day, end_raw)
        except ValueError:
            continue
        if start >= end or not _clean(task) or not _clean(zone):
            continue
        locality = _edese_locality(zone)
        if not locality:
            continue
        items.append(_notice('EDESE', 'Santiago del Estero',
                             PROVIDERS['edese_santiago_del_estero'][2],
                             locality, start, end, zone, task))
    return _filter_window(items, now), seen, newest



# EPEN publishes dated WordPress notices. RSS is an official publication index,
# NOT proof of any outage. Each scheduled item must independently corroborate
# the date and hours written in its body. This intentionally rejects occasional
# EPEN posts where the headline dates disagree with the actual article.
_EPEN_MONTHS = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
                'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
                'septiembre': 9, 'setiembre': 9, 'octubre': 10,
                'noviembre': 11, 'diciembre': 12}
_EPEN_TOWNS_NORTH = (
    'Chos Malal', 'Taquimilán', 'Tricao Malal', 'Andacollo',
    'Huinganco', 'Los Miches', 'Las Ovejas', 'Varvarco',
    'Manzano Amargo', 'Los Guañacos', 'Villa del Nahueve',
    'Buta Ranquil', 'Barrancas', 'Cerro Mayal', 'El Alamito',
    'La Primavera', 'Villa Curi Leuvú',
)
_EPEN_DATE_TITLE = re.compile(r'\bel\s+(\d{1,2})/(\d{1,2})/(20\d{2}|\d{2})\s*$', re.I)
_EPEN_BODY_DATE = re.compile(
    r'\b(\d{1,2})\s+de\s+(' + '|'.join(_EPEN_MONTHS) + r')\b', re.I)
_EPEN_HOURS = re.compile(
    r'\b(?:de|desde)\s+(\d{1,2})(?::(\d{2}))?\s*'
    r'(?:a|hasta|[-–])\s*(\d{1,2})(?::(\d{2}))?\s*'
    r'(?:h(?:s|oras)?\.?|$|[,.;])', re.I)


def _epen_article_url(link):
    """Reject arbitrary RSS links, redirects and external domains."""
    try:
        parts = urlsplit(link)
    except ValueError:
        return False
    return (parts.scheme == 'https' and parts.hostname in
            ('www.epen.gov.ar', 'epen.gov.ar') and not parts.username and
            not parts.password and not parts.query and not parts.fragment and
            bool(re.fullmatch(r'/index\.php/20\d{2}/\d{2}/\d{2}/[a-z0-9-]+/',
                              parts.path)))


def _epen_feed_items(xml):
    if not isinstance(xml, str) or len(xml.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Boletín inválido o demasiado grande')
    root = ElementTree.fromstring(xml)
    if root.tag != 'rss':
        raise ValueError('La respuesta no es un RSS reconocible')
    channel = root.find('channel')
    if channel is None:
        raise ValueError('RSS sin canal')
    records = []
    for item in channel.findall('item')[:35]:
        title = _clean(unescape(item.findtext('title') or ''), 250)
        link = _clean(item.findtext('link') or '', 380)
        content = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or ''
        if not content:
            content = item.findtext('description') or ''
        if ('corte' in title.casefold() and 'programad' in title.casefold()
                and _EPEN_DATE_TITLE.search(title) and _epen_article_url(link)):
            records.append((title, link, content[:30000]))
    return records


def _epen_post_body(html):
    _, visible = _visible(html)
    # WordPress pages append unrelated 'Últimas noticias' titles after the post.
    # Extract ONLY the actual EPEN bulletin, not those unrelated dates.
    m = re.search(r'\bEl Ente Provincial de Energ[ií]a del Neuqu[eé]n\b',
                  visible, re.I)
    if not m:
        return ''
    body = visible[m.start():m.start() + 3500]
    cutoff = re.search(r'\b(?:Por Prensa EPEN|Published On|Compart[ií] la noticia|'
                       r'[UÚ]ltimas Noticias)\b', body, re.I)
    return _clean(body[:cutoff.start() if cutoff else None], 3000)


def _epen_headline_locality(title):
    # Explicit named town only. "zona Norte" and similar broad regions are
    # expanded solely from towns stated explicitly in the official 'Afecta'.
    m = re.search(r'\ben\s+(?:sectores?\s+de\s+|zona\s+rural\s+de\s+|'
                  r'la\s+zona\s+rural\s+de\s+|la\s+zona\s+)'
                  r'(.+?)\s+el\s+\d{1,2}/', title, re.I)
    if not m:
        return ''
    town = _clean(m.group(1), 100)
    if re.match(r'^(?:la\s+)?zona\b|^sectores\b|^norte\b', town, re.I):
        return ''
    return town


def _parse_epen_article(title, link, html, now):
    """Parse only *one-day* notices with corroborating body date and hours."""
    m = _EPEN_DATE_TITLE.search(title)
    if not m or not _epen_article_url(link):
        return []
    year = int(m.group(3))
    if year < 100:
        year += 2000
    try:
        day = datetime(year, int(m.group(2)), int(m.group(1))).date()
    except ValueError:
        return []
    body = _epen_post_body(html)
    if not body or 'EPEN' not in body or 'corte' not in body.casefold():
        return []
    dates = {(int(d), _EPEN_MONTHS[month.casefold()])
             for d, month in _EPEN_BODY_DATE.findall(body)}
    # A date in the title alone is never enough. Contradictions are rejected.
    if dates != {(day.day, day.month)}:
        return []
    windows = set()
    for a, amin, b, bmin in _EPEN_HOURS.findall(body):
        try:
            start = _datetime(day, f'{int(a):02d}:{int(amin or 0):02d}')
            end = _datetime(day, f'{int(b):02d}:{int(bmin or 0):02d}')
            if start < end:
                windows.add((start, end))
        except ValueError:
            continue
    if len(windows) != 1:
        return []
    start, end = next(iter(windows))
    if not (now <= start <= now + timedelta(days=MAX_DAYS)):
        return []
    affected = re.search(r'\bAfecta\s*:\s*(.*?)(?=\b(?:A partir de|'
                         r'Se solicita|Solicitamos|Por Prensa)\b|$)', body, re.I | re.S)
    if not affected:
        return []
    zone = _clean(affected.group(1), 700).rstrip('. ')
    if len(zone) < 8:
        return []
    town = _epen_headline_locality(title)
    if town:
        localities = [town]
    elif re.search(r'\bzona\s+norte\b', title, re.I):
        localities = [name for name in _EPEN_TOWNS_NORTH if re.search(
            r'(?<!\w)' + re.escape(name) + r'(?!\w)', zone, re.I)]
    else:
        localities = []
    if not localities:
        return []
    task_m = re.search(r'\bpara\s+(?:realizar|efectuar)\s+([^.;]{8,190})', body, re.I)
    task = _clean(task_m.group(1), 180) if task_m else 'Corte programado anunciado por EPEN'
    return [_notice('EPEN', 'Neuquén', link, locality, start, end, zone, task)
            for locality in localities[:25]]


def _collect_epen(checked_at, now, fetch):
    key = 'epen_neuquen'
    company, province, official = PROVIDERS[key]
    output = {
        'status': 'unverified', 'province': province, 'country': 'Argentina',
        'company': company, 'source_url': official, 'checked_at': checked_at,
        'coverage_kind': 'planned_outages_only', 'notices': [],
        'parser_revision': 'EPEN-RSS-v5.22',
        'message': 'Sin publicaciones verificadas; no implica suministro normal.',
        'source_attempts': [],
    }
    attempt = {'url': EPEN_RSS}
    output['source_attempts'].append(attempt)
    try:
        records = _epen_feed_items(fetch(EPEN_RSS))
    except Exception as exc:
        attempt.update(result='fetch_or_parse_error', error_type=type(exc).__name__)
        output['message'] = 'No se pudo verificar el boletín oficial de EPEN.'
        return output
    attempt['candidate_posts'] = len(records)
    if not records:
        attempt['result'] = 'no_relevant_posts'
        return output

    all_notices, accepted_posts, rejected_posts = [], 0, 0
    newest = None
    # On a normal WordPress RSS, content:encoded contains the article body.
    # Fetch full article only when that body is absent/incomplete, at most 8.
    extra_fetches = 0
    for title, link, content in records[:20]:
        date_match = _EPEN_DATE_TITLE.search(title)
        if not date_match:
            continue
        try:
            year = int(date_match.group(3))
            year = (year + 2000) if year < 100 else year
            published_day = datetime(year, int(date_match.group(2)), int(date_match.group(1))).date()
        except ValueError:
            continue
        if published_day < (now - timedelta(days=3)).date() or \
                published_day > (now + timedelta(days=MAX_DAYS)).date():
            continue
        parsed = _parse_epen_article(title, link, content, now)
        if not parsed and extra_fetches < 8:
            extra_fetches += 1
            try:
                article = fetch(link)
                parsed = _parse_epen_article(title, link, article, now)
            except Exception:
                # A failed article should not prevent verified other posts.
                pass
        if parsed:
            accepted_posts += 1
            newest = published_day if newest is None else max(newest, published_day)
            all_notices.extend(parsed)
        else:
            rejected_posts += 1
    attempt.update(result=('verified' if accepted_posts else 'no_complete_records'),
                   posts_verified=accepted_posts, posts_rejected=rejected_posts,
                   extra_article_fetches=extra_fetches)
    if not accepted_posts:
        output['message'] = ('No hay avisos completos con fecha, horario y zona '
                             'coincidentes entre titular y publicación. No se infiere estado normal.')
        return output
    notices = _filter_window(all_notices, now)
    output.update(status='ok', notices=notices, records_checked=accepted_posts,
                  latest_published_date=newest.isoformat(),
                  message='Cortes programados publicados por EPEN; NO confirman cortes en curso.',
                  rejected_article_count=rejected_posts)
    return output


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
        'Accept': 'text/html,application/xhtml+xml,application/rss+xml,application/xml',
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
        'edese_santiago_del_estero': r'(?<!\d)\d{1,2}/\d{1,2}/20\d\d(?!\d)',
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
    if key == 'epen_neuquen':
        return _collect_epen(checked_at, now, fetcher or fetch_html)
    output = {'status': 'unverified', 'province': province, 'country': 'Argentina',
              'company': company, 'source_url': url, 'checked_at': checked_at,
              'coverage_kind': 'planned_outages_only', 'notices': [],
              'message': 'Sin verificación de publicaciones; no implica suministro normal.',
              'source_attempts': []}
    if key == 'edersa_rio_negro':
        output['parser_revision'] = 'EDERSA-v5.18.1'
    if key == 'edese_santiago_del_estero':
        output['parser_revision'] = 'EDESE-ENRESE-v5.21'
        output['published_by'] = 'ENRESE (ente regulador provincial)'
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
            elif key == 'edese_santiago_del_estero':
                notices, count, newest = _parse_edese(html, now)
            else:
                notices, count, newest = _parse_epec(html, now)
            attempt['records_checked'] = count
            if key == 'edersa_rio_negro':
                # This is a *source-content* warning, not a parsing failure.
                attempt['source_zone_conflict_count'] = sum(
                    1 for notice in notices if notice.get('source_zone_conflict'))
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
            if key == 'edersa_rio_negro':
                conflict_count = attempt['source_zone_conflict_count']
                output['source_zone_conflict_count'] = conflict_count
                if conflict_count:
                    output['message'] = (f'Trabajos programados; {conflict_count} avisos tienen '
                                         'zona no verificada por contradicción en la fuente. '
                                         'NO confirma cortes en curso.')
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

"""Conservative scheduled electricity work collectors for Argentine provinces.

The three sources are public web pages, not documented APIs. Record only
published, date-verified future schedules; never infer an outage in progress.
Remote failures, empty JavaScript shells and stale archives are NOT "no outages".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
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
    'ejesa_jujuy': ('EJESA', 'Jujuy', 'https://www.ejesa.com.ar/gestion/pwa/tareasprogramadas/mejora-y-mantenimiento'),
    'edet_tucuman': ('EDET', 'Tucumán', 'https://www.edetsa.com/gestion/pwa/tareasprogramadas/cortes-de-luz'),
    'edemsa_mendoza': ('EDEMSA', 'Mendoza', 'https://www.epremendoza.gob.ar/mantenimientos.php'),
    'copelco_neuquen': ('COPELCO', 'Neuquén', 'https://www.copelnet.com.ar/'),
    'cpe_la_pampa': ('CPE', 'La Pampa', 'https://cpe.coop.ar/estado-servicios'),
    'edelap_la_plata': ('EDELAP', 'Buenos Aires', 'https://www.edelap.com.ar/obras-en-tu-barrio/'),
    'coopelec_concordia': ('COOPELEC', 'Entre Ríos', 'https://www.coopelec.com.ar/cortes-programados/'),
    # Public-source batch v5.29: a provider is NOT automatically verified just
    # because its URL answers. Only complete, date/zone-checked records count.
    'corpico_general_pico': ('CORPICO', 'La Pampa', 'https://www.corpico.com.ar/cortesprogramados'),
    'calf_neuquen': ('CALF', 'Neuquén', 'https://www.cooperativacalf.com.ar/category/cortes-programados/'),
    'energia_misiones': ('Energía de Misiones', 'Misiones', 'https://www.energiademisiones.com.ar/fuera-de-servicio/'),
    'edelar_la_rioja': ('EDELAR', 'La Rioja', 'https://www.edelar.com.ar/cortes-programados'),
    'scpl_comodoro': ('SCPL', 'Chubut', 'https://www.scpl.coop/'),
    'ceb_bariloche': ('CEB', 'Río Negro', 'https://www.ceb.coop/category/cortes-programados/'),
    # v5.30: public official portals, not outage-confirmation services.
    'cepa_punta_alta': ('CEPA', 'Buenos Aires', 'https://www.cepa.com.ar/cortes/Cortes.aspx'),
    'spse_santa_cruz': ('SPSE', 'Santa Cruz', 'https://spse.ar/suspension-servicios'),
    'servicoop_puerto_madryn': ('Servicoop', 'Chubut', 'https://web.servicoop.com/category/cortes-programados/'),
    'usina_tandil': ('Usina de Tandil', 'Buenos Aires', 'https://www.usinatandil.com.ar/'),
}
EPE_LEGACY = 'https://www.epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPE_LEGACY_ALT = 'https://epe.santafe.gov.ar/reclamosweb/cortes.php/cortes.php'
EPEC_ALTERNATE = 'https://epec.com.ar/actualidad/trabajos-mejoras'
EPEN_RSS = 'https://www.epen.gov.ar/index.php/feed/'
EPEN_ARCHIVE = 'https://www.epen.gov.ar/index.php/cortes-programados/'
EDESE_ALTERNATE = 'https://enrese.com.ar/CortesProgramados.html'
CPE_ALTERNATE = 'https://sitionuevo.cpe.coop.ar/estado-servicios'
SCPL_ALTERNATE = 'https://scpl.coop/'


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


class _EpenArchiveLinks(HTMLParser):
    """Read links, not just their labels: EPEN often puts titles outside anchors.

    Every link is later checked against the official host/path and the article's
    own body. A "read more" label does not mean there is no linked bulletin.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.records = []
        self.links = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignore += 1
            return
        if self.ignore:
            return
        attributes = dict(attrs)
        for key in ('href', 'data-href', 'data-url', 'data-link'):
            value = attributes.get(key, '')
            if isinstance(value, str) and value and len(value) < 500:
                self.links.append(value)
        if tag == 'a':
            self.current = (attributes.get('href', ''), [])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignore = max(0, self.ignore - 1)
            return
        if self.ignore:
            return
        if tag == 'a' and self.current:
            href, parts = self.current
            self.records.append((href, _clean(' '.join(parts), 260)))
            self.current = None

    def handle_data(self, data):
        if not self.ignore and self.current is not None:
            self.current[1].append(data[:500])


def _epen_title_from_slug(link):
    """Reconstruct only explicitly dated 'corte programado' titles from a URL.

    The slug supplies a *candidate*, not verification: its article must agree
    on the calendar day, hours and affected locality before an alert is created.
    """
    slug = urlsplit(link).path.rstrip('/').rsplit('/', 1)[-1]
    match = re.fullmatch(r'(corte-programado-[a-z0-9-]+-el)-'
                         r'(\d{1,2})-(\d{1,2})-(20\d{2}|\d{2})', slug, re.I)
    if not match:
        return ''
    prefix, day, month, year = match.groups()
    return prefix.replace('-', ' ') + f' {day}/{month}/{year}'


def _epen_archive_items(html):
    """Collect validated candidate links from the public EPEN archive.

    The original v5.22.1 parser required anchor text to contain a perfect title;
    the real archive returned 0 posts even though the other EPEN collector found
    eight items. Read official permalinks and derive the candidate's title only
    when its URL has an unambiguous full-day date. Never trust titles as proof.
    """
    if not isinstance(html, str) or not html.strip() or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Archivo EPEN inválido o demasiado grande')
    dom = _EpenArchiveLinks()
    dom.feed(html)
    unique = {}
    # A misleading visible title is a source conflict, even if the same link
    # appears again on a thumbnail or in an unrelated embedded card.
    conflicts = set()
    for href, label in dom.records:
        link = urljoin(EPEN_ARCHIVE, unescape(href))
        if not _epen_article_url(link):
            continue
        derived = _epen_title_from_slug(link)
        if not derived:
            continue
        explicit = re.search(r'(?i)\bcorte\s+programado\b.{0,180}?'
                             r'\bel\s+\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2})\b',
                             label)
        if explicit and _EPEN_DATE_TITLE.search(explicit.group(0)).group(0).casefold() != \
                _EPEN_DATE_TITLE.search(derived).group(0).casefold():
            conflicts.add(link)
    # Prefer visible linked titles, but also recognize anchors with generic
    # labels and images/data-url cards. Only dated official permalinks qualify.
    for href, label in dom.records + [(href, '') for href in dom.links]:
        if not isinstance(href, str) or len(href) > 500:
            continue
        link = urljoin(EPEN_ARCHIVE, unescape(href))
        if not _epen_article_url(link) or link in conflicts:
            continue
        derived = _epen_title_from_slug(link)
        if not derived:
            continue
        dated_label = re.search(r'(?i)\bcorte\s+programado\b.{0,180}?'
                                r'\bel\s+\d{1,2}/\d{1,2}/(?:20\d{2}|\d{2})\b',
                                label)
        title = dated_label.group(0) if dated_label else derived
        # If the visible label and URL name different days, ignore it.
        if _EPEN_DATE_TITLE.search(title).group(0).casefold() != \
                _EPEN_DATE_TITLE.search(derived).group(0).casefold():
            continue
        unique.setdefault(link, (title, link, ''))
        if len(unique) >= 35:
            break
    # Bounded fallback for EPEN links embedded in card markup instead of hrefs;
    # these candidates must still pass strict full-article validation.
    if not unique:
        for match in re.finditer(
                r'(?:https://(?:www\.)?epen\.gov\.ar)?'
                r'/index\.php/20\d{2}/\d{2}/\d{2}/[a-z0-9-]+/', html, re.I):
            link = urljoin(EPEN_ARCHIVE, match.group(0))
            if _epen_article_url(link) and link not in conflicts:
                title = _epen_title_from_slug(link)
                if title:
                    unique.setdefault(link, (title, link, ''))
                if len(unique) >= 35:
                    break
    return list(unique.values())


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
        'parser_revision': 'EPEN-RSS-ARCHIVE-v5.22.2',
        'message': 'Sin publicaciones verificadas; no implica suministro normal.',
        'source_attempts': [],
    }
    rss_attempt = {'url': EPEN_RSS}
    output['source_attempts'].append(rss_attempt)
    records = []
    try:
        records = _epen_feed_items(fetch(EPEN_RSS))
        rss_attempt.update(candidate_posts=len(records),
                           result='candidates_found' if records else 'no_relevant_posts')
    except Exception as exc:
        rss_attempt.update(result='fetch_or_parse_error', error_type=type(exc).__name__)

    # EPEN's public RSS may only contain the newest posts, excluding still-future
    # scheduled cuts published several days earlier. Fall back to its OFFICIAL
    # WordPress category archive; never infer a verified schedule from its title.
    if not records:
        archive_attempt = {'url': EPEN_ARCHIVE}
        output['source_attempts'].append(archive_attempt)
        try:
            records = _epen_archive_items(fetch(EPEN_ARCHIVE))
            archive_attempt.update(candidate_posts=len(records),
                                   result='candidates_found' if records else 'no_relevant_posts')
        except Exception as exc:
            archive_attempt.update(result='fetch_or_parse_error',
                                   error_type=type(exc).__name__)
    if not records:
        output['message'] = ('No se obtuvieron publicaciones oficiales verificables de EPEN. '
                             'No implica suministro normal.')
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
        try:
            parsed = _parse_epen_article(title, link, content, now) if content.strip() else []
        except (ValueError, TypeError):
            parsed = []
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
    # The last nonempty source selected above is the one we actually parsed.
    used_attempt = output['source_attempts'][-1]
    used_attempt.update(result=('verified' if accepted_posts else 'no_complete_records'),
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


# EJESA publishes a readable public task timetable with date, named town,
# exact hours, affected zone and task state. "Mapro sin afectar el servicio",
# completed tasks, and notices missing zones are NOT planned outages.
_EJESA_ISO_DAY = re.compile(r'(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)')
_EJESA_HOURS = re.compile(r'\bDesde\s+(\d{1,2}:\d{2})\s+hasta\s+'
                          r'(\d{1,2}:\d{2})\b', re.I)
_EJESA_BRIEF_HOURS = re.compile(r'(?<!\d)(\d{1,2}:\d{2})\s*(?:a|hasta)\s*'
                                r'(\d{1,2}:\d{2})(?!\d)', re.I)


def _parse_ejesa(html, now):
    """Parse only official APROBADA electrical interruptions, not other tasks.

    Each visible ISO date begins one task card. The card must explicitly
    repeat zone, locality, schedule and status labels; nearby cards cannot
    contribute missing fields. Date/time are used exactly as published.
    """
    _, visible = _visible(html)
    if 'Tareas Programadas' not in visible and 'Estado de la tarea' not in visible:
        return [], 0, None
    days = list(_EJESA_ISO_DAY.finditer(visible))
    notices, seen, newest = [], 0, None
    for idx, match in enumerate(days):
        try:
            day = datetime.strptime(match.group(1), '%Y-%m-%d').date()
        except ValueError:
            continue
        # A card is bounded by the next ISO date, never a free-text search
        # over the whole official page. Avoid mixing neighboring schedules.
        end_at = days[idx + 1].start() if idx + 1 < len(days) else len(visible)
        card = visible[match.end():end_at]
        if len(card) > 3500:
            continue
        # Official pages also repeat a dd/mm/yyyy date before the ISO date.
        # A conflicting printed date makes this item untrustworthy.
        pre = visible[max(0, match.start() - 120):match.start()]
        date_printed = re.search(r'(\d{1,2}/\d{1,2}/20\d{2})\s*$', pre)
        if date_printed:
            try:
                if datetime.strptime(date_printed.group(1), '%d/%m/%Y').date() != day:
                    continue
            except ValueError:
                continue
        status = re.search(r'\bEstado\s+de\s+la\s+tarea\s*:\s*'
                           r'(APROBADA|EJECUTADA|CANCELADA|SUSPENDIDA|PENDIENTE|PROGRAMADA)\b',
                           card, re.I)
        if not status:
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        if status.group(1).upper() != 'APROBADA':
            continue
        times = _EJESA_HOURS.search(card)
        if not times:
            continue
        # The cards have a short hours label too. Reject contradictions.
        briefs = _EJESA_BRIEF_HOURS.findall(card[:times.start()])
        if briefs and any(pair != times.groups() for pair in briefs):
            continue
        locality_match = re.search(
            r'\bLocalidad\s*:\s*(.*?)\s+(?:description\s+)?'
            r'Descripci[oó]n\s*:', card, re.I | re.S)
        zone_match = re.search(
            r'\bZona\s*:\s*(.*?)\s+(?:flag\s+)?Localidad\s*:',
            card, re.I | re.S)
        if not locality_match or not zone_match:
            continue
        locality = _clean(locality_match.group(1), 100)
        zone = _clean(zone_match.group(1), 700)
        if not locality or not zone or len(zone) < 14:
            continue
        low_zone = zone.casefold()
        if (re.search(r'\bsin\s+afect(?:ar|aci[oó]n)\s+(?:el\s+)?servicio\b', low_zone)
                or re.search(r'\bno\s+(?:se\s+)?(?:afecta|interrumpe)\b', low_zone)
                or not re.search(r'\b(?:interrupci[oó]n|corte)\s+'
                                 r'(?:de\s+)?(?:suministro|programad[oa]|energ[ií]a)\b',
                                 low_zone, re.I)):
            continue
        try:
            start, end = _datetime(day, times.group(1)), _datetime(day, times.group(2))
        except ValueError:
            continue
        if start >= end:
            continue
        task_match = re.search(r'\bDescripci[oó]n\s*:\s*(.*?)\s+'
                               r'(?:beenhere\s+)?Estado\s+de\s+la\s+tarea\s*:',
                               card, re.I | re.S)
        task = _clean(task_match.group(1), 250) if task_match else 'Interrupción programada EJESA'
        notices.append(_notice('EJESA', 'Jujuy', PROVIDERS['ejesa_jujuy'][2],
                               locality, start, end, zone, task))
    return _filter_window(notices, now), seen, newest


# EDET (Tucumán) publishes the same per-card ISO dates and clock intervals as
# EJESA, but labels its service area "Sucursal" and publishes the number of
# affected services. "APROBADA" alone is insufficient: never infer that a
# maintenance task interrupts power without an explicit affected-services count
# or an unambiguous interruption statement. No automatic alert is generated.
def _parse_edet(html, now):
    _, visible = _visible(html)
    if 'tareas programadas' not in visible.lower() and 'estado de la tarea' not in visible.lower():
        return [], 0, None
    days = list(_EJESA_ISO_DAY.finditer(visible))
    notices, seen, newest = [], 0, None
    for idx, match in enumerate(days):
        try:
            day = datetime.strptime(match.group(1), '%Y-%m-%d').date()
        except ValueError:
            continue
        end_at = days[idx+1].start() if idx+1 < len(days) else len(visible)
        card = visible[match.end():end_at]
        if len(card) > 3500:
            continue
        printed = re.search(r'(\d{1,2}/\d{1,2}/20\d{2})\s*$',
                            visible[max(0, match.start()-120):match.start()])
        if printed:
            try:
                if datetime.strptime(printed.group(1), '%d/%m/%Y').date() != day:
                    continue
            except ValueError:
                continue
        state = re.search(r'\bEstado\s+de\s+la\s+tarea\s*:\s*'
                          r'(APROBADA|EJECUTADA|CANCELADA|SUSPENDIDA|PENDIENTE|PROGRAMADA)\b',
                          card, re.I)
        if not state:
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        if state.group(1).upper() != 'APROBADA':
            continue
        hours = _EJESA_HOURS.search(card)
        if not hours:
            continue
        brief = _EJESA_BRIEF_HOURS.findall(card[:hours.start()])
        if brief and any(pair != hours.groups() for pair in brief):
            continue
        area_m = re.search(r'\bSucursal\s*:\s*(.*?)\s+(?:description\s+)?'
                           r'Descripci[oó]n\s*:', card, re.I | re.S)
        zone_m = re.search(r'\bZona\s*:\s*(.*?)\s+(?:flag\s+)?'
                           r'Sucursal\s*:', card, re.I | re.S)
        count_m = re.search(r'\bCantidad\s+de\s+servicios\s+afectados\s*:\s*'
                            r'([0-9]{1,7})\b', card, re.I)
        if not area_m or not zone_m or not count_m:
            continue
        branch = _clean(area_m.group(1), 100)
        zone = _clean(zone_m.group(1), 700)
        if (not branch or len(zone) < 8 or int(count_m.group(1)) <= 0 or
                re.search(r'\b(?:sin\s+afectar\s+(?:el\s+)?servicio|'
                          r'no\s+(?:se\s+)?interrumpe|no\s+(?:se\s+)?afecta)\b',
                          zone + ' ' + card, re.I)):
            continue
        try:
            start, end = _datetime(day, hours.group(1)), _datetime(day, hours.group(2))
        except ValueError:
            continue
        if start >= end:
            continue
        task_m = re.search(r'\bDescripci[oó]n\s*:\s*(.*?)\s+'
                           r'(?:format_list_numbered\s+)?Cantidad\s+de\s+servicios\s+afectados\s*:',
                           card, re.I | re.S)
        task = _clean(task_m.group(1), 250) if task_m else 'Tarea programada EDET'
        notices.append(_notice('EDET', 'Tucumán', PROVIDERS['edet_tucuman'][2],
                               branch, start, end, zone, task))
    return _filter_window(notices, now), seen, newest


# EPRE Mendoza (provincial regulator) publishes an HTML table with a
# distribution company, start date/time, duration, district, department and
# number of affected users. This connector ONLY accepts EDEMSA entries.
# No real-time outage is inferred from a maintenance timetable. The EPRE
# landing page embeds this public regulator-hosted table as an iframe.
# Read the iframe directly, not the surrounding JavaScript page.
def _parse_edemsa_epre(html, now):
    dom, _ = _visible(html)
    notices, seen, newest = [], 0, None
    regulator = PROVIDERS['edemsa_mendoza'][2]
    for kind, cells in dom.events:
        if kind != 'row' or not isinstance(cells, list) or len(cells) < 8:
            continue
        company, start_raw, hours_raw, reason, task, district, department, affected = [
            _clean(c, 600) for c in cells[:8]
        ]
        if company.upper() != 'EDEMSA':
            continue
        # EPRE uses dd-mm-yyyy HH:MM:SS for the scheduled start.
        try:
            start = datetime.strptime(start_raw, '%d-%m-%Y %H:%M:%S').replace(tzinfo=ART)
        except ValueError:
            continue
        seen += 1
        newest = max(newest, start.date()) if newest else start.date()
        try:
            duration = Decimal(hours_raw.replace(',', '.'))
            minutes = duration * Decimal(60)
            if not (Decimal(0) < duration <= Decimal(12)) or minutes != int(minutes):
                continue
            end = start + timedelta(minutes=int(minutes))
        except (InvalidOperation, ValueError, OverflowError):
            continue
        # EPRE may include rows with N/A zones or zero users. Those are
        # insufficient for a locally targeted interruption notice.
        if (not affected.isdigit() or not 0 < int(affected) <= 10000000 or
                not district or district.upper() in ('N/A', 'NA', '-') or
                not department or department.upper() in ('N/A', 'NA', '-')):
            continue
        # Only district is used as the locality hint to reduce accidental
        # matching of a department in an unrelated province. The province
        # and department are always spelled out in the published zone.
        locality = re.sub(r'^[A-Z]{2,3}-(?=[A-ZÁÉÍÓÚÑ])', '', district)
        zone = f'Distrito {district}; departamento {department}; Mendoza'
        detail = '; '.join(x for x in [reason, task] if x)
        detail = f'{detail}. Usuarios publicados como afectados: {affected}'
        notices.append(_notice('EDEMSA', 'Mendoza', regulator, locality,
                               start, end, zone, detail))
    return _filter_window(notices, now), seen, newest


# COPELCO is an electric cooperative with a public programme for Cutral Co
# and Plaza Huincul, distinct from EPEN's distribution area. Its home page
# prints dates without a year. A date is accepted only when the printed
# weekday matches this year's calendar and the work starts in the next 14 days.
_COP_MONTHS = {'ENE': 1, 'FEB': 2, 'MAR': 3, 'ABR': 4, 'MAY': 5,
               'JUN': 6, 'JUL': 7, 'AGO': 8, 'SEP': 9, 'OCT': 10,
               'NOV': 11, 'DIC': 12}
_COP_WEEKDAYS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes',
                 'sabado', 'domingo')
_COP_CARD = re.compile(
    r'(?<!\w)(?P<day>\d{1,2})\s+'
    r'(?P<month>ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\s+'
    r'(?P<weekday>lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+'
    r'(?P<start>\d{1,2}:\d{2})\s+a\s+'
    r'(?P<end>\d{1,2}:\d{2})\s+hs\b', re.I)


def _plain_fold(value):
    return (value.lower().replace('á', 'a').replace('é', 'e')
            .replace('í', 'i').replace('ó', 'o').replace('ú', 'u'))


def _parse_copelco(html, now):
    _, visible = _visible(html)
    header = re.search(r'\bCortes programados\b', visible, re.I)
    if not header:
        return [], 0, None
    region = visible[header.end():]
    footer = re.search(r'\bLos horarios son estimados\b|\bNuestros servicios\b',
                       region, re.I)
    if footer:
        region = region[:footer.start()]
    cards = list(_COP_CARD.finditer(region))
    records, seen, newest = [], 0, None
    for i, marker in enumerate(cards[:80]):
        mon = _COP_MONTHS[marker.group('month').upper()]
        date = None
        for year in (now.year, now.year + 1):
            try:
                candidate = datetime(year, mon, int(marker.group('day'))).date()
            except ValueError:
                continue
            if (candidate >= now.date() - timedelta(days=2) and
                    candidate <= now.date() + timedelta(days=MAX_DAYS) and
                    _COP_WEEKDAYS[candidate.weekday()] ==
                    _plain_fold(marker.group('weekday'))):
                date = candidate
                break
        if date is None:
            continue
        end_pos = cards[i + 1].start() if i + 1 < len(cards) else len(region)
        body = region[marker.end():end_pos]
        body = re.split(r'\bUsuarios singulares\s*:', body, maxsplit=1, flags=re.I)[0]
        locality_zone = re.search(r'\b(PLAZA\s+HUINCUL|CUTRAL[-\s]+CO)\s*[-–]?\s*[•]?\s*(.+)',
                                  body, re.I | re.S)
        if not locality_zone:
            continue
        locality = locality_zone.group(1).upper().replace('-', ' ')
        zone = _clean(locality_zone.group(2), 700).strip('-–• ')
        if len(zone) < 12:
            continue
        try:
            start, end = (_datetime(date, marker.group('start')),
                          _datetime(date, marker.group('end')))
        except ValueError:
            continue
        if start >= end:
            continue
        seen += 1
        newest = max(newest, date) if newest else date
        ref = re.match(r'\s*(SET\s+[\d-]{1,30})\b', body, re.I)
        task = ('Corte programado anunciado por COPELCO' +
                ('; ' + ref.group(1) if ref else ''))
        records.append(_notice('COPELCO', 'Neuquén', PROVIDERS['copelco_neuquen'][2],
                               locality, start, end, zone, task))
    return _filter_window(records, now), seen, newest


# CPE, the Santa Rosa electricity cooperative, explicitly separates its
# current programme from past bulletins. Dates must include a full year.
# The source may keep old posts under its "vigentes" heading; those remain
# stale, never a reason to announce that the electricity is normal.
_CPE_MONTHS = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
               'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
               'septiembre': 9, 'setiembre': 9, 'octubre': 10,
               'noviembre': 11, 'diciembre': 12}
_CPE_DAY = re.compile(
    r'\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+'
    r'(\d{1,2})\s+de\s+'
    r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|'
    r'setiembre|octubre|noviembre|diciembre)\s+de\s+(20\d\d)\b', re.I)


def _parse_cpe(html, now):
    _, visible = _visible(html)
    marker = re.search(r'\bCortes programados vigentes\b', visible, re.I)
    if not marker:
        return [], 0, None
    region = visible[marker.end():]
    end = re.search(r'\bCortes programados pasados\b', region, re.I)
    if end:
        region = region[:end.start()]
    # This means the official source is reachable and says its current
    # scheduled-work list is empty; it does NOT confirm normal supply.
    dates = list(_CPE_DAY.finditer(region))
    if not dates and re.search(r'\bNo hay cortes programados vigentes\b', region, re.I):
        return [], 1, now.date()
    records, seen, newest = [], 0, None
    for i, marker in enumerate(dates[:70]):
        _, number, month, year = marker.groups()
        try:
            date = datetime(int(year), _CPE_MONTHS[month.lower()], int(number)).date()
        except ValueError:
            continue
        if _COP_WEEKDAYS[date.weekday()] != _plain_fold(marker.group(1)):
            continue
        end_pos = dates[i+1].start() if i+1 < len(dates) else len(region)
        block = region[marker.end():end_pos]
        if not re.search(r'\bCORTE PROGRAMADO\b', block, re.I):
            continue
        hours = re.search(r'desde\s+las?\s+(\d{1,2}:\d{2})\s+'
                          r'hasta\s+las?\s+(\d{1,2}:\d{2})\b', block, re.I)
        zone_match = re.search(r'\bzona comprendida por\s+(.+?)'
                               r'(?=\.\s*Personal de la CPE|'
                               r'\.\s*Los trabajos|$)', block, re.I | re.S)
        if not hours or not zone_match:
            continue
        zone = _clean(zone_match.group(1), 700).strip(' .,;')
        if len(zone) < 15:
            continue
        try:
            start, stop = _datetime(date, hours.group(1)), _datetime(date, hours.group(2))
        except ValueError:
            continue
        if start >= stop:
            continue
        seen += 1
        newest = max(newest, date) if newest else date
        locality = ('TOAY' if re.search(r'\bToay\b', block, re.I) else
                    'LONQUIMAY' if re.search(r'\bLonquimay\b', block, re.I) else
                    'SANTA ROSA')
        records.append(_notice('CPE', 'La Pampa', PROVIDERS['cpe_la_pampa'][2],
                               locality, start, stop, zone,
                               'Corte programado comunicado por la cooperativa CPE'))
    return _filter_window(records, now), seen, newest


# EDELAP publishes an open schedule for La Plata and nearby towns. Entries
# are works which MAY interrupt supply, not verified live outages. The site
# prints a day and month (no year), so require agreement with the local
# calendar weekday and a +/-2 to +14-day publication window. Do not infer
# an affected locality from a street number alone.
_EDELAP_HEAD = re.compile(
    r'\b(?P<weekday>lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+'
    r'(?P<day>\d{1,2})\s+de\s+'
    r'(?P<month>enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|'
    r'setiembre|octubre|noviembre|diciembre)\b', re.I)
_EDELAP_SLOT = re.compile(
    r'\bde\s+(?P<start>\d{1,2}(?::\d{2})?)\s+a\s+'
    r'(?P<end>\d{1,2}(?::\d{2})?)\s*hs\.?\s*'
    r'en\s+la\s+zona\s+de\b', re.I)
_EDELAP_LOCALITIES = (
    'San Carlos', 'Manuel B. Gonnet', 'Melchor Romero', 'Los Hornos',
    'Villa Elvira', 'Villa Elisa', 'Villa Castells', 'City Bell',
    'La Plata', 'Lisandro Olmos', 'Tolosa', 'Ringuelet', 'Ensenada',
    'Berisso', 'Abasto', 'Gonnet', 'Gorina', 'Arana', 'Hernández',
    'Arturo Seguí', 'El Peligro', 'Magdalena', 'Punta Indio',
    'Villa Garibaldi', 'San Lorenzo', 'Altos de San Lorenzo',
)
_EDELAP_LOCALITY_RE = re.compile(
    r',\s*(' + '|'.join(re.escape(x) for x in _EDELAP_LOCALITIES) + r')\s*$', re.I)


def _parse_edelap(html, now):
    _, visible = _visible(html)
    header = re.search(r'\bObras\s+en\s+tu\s+barrio\b', visible, re.I)
    if not header:
        return [], 0, None
    region = visible[header.end():]
    footer = re.search(r'\bLos\s+trabajos\s+pueden\s+implicar\b|'
                       r'\bLos\s+usuarios\s+alcanzados\s+por\s+estas\s+obras\b', region, re.I)
    if footer:
        region = region[:footer.start()]
    dates = list(_EDELAP_HEAD.finditer(region))[:50]
    seen, newest, records = 0, None, []
    for i, heading in enumerate(dates):
        month = _CPE_MONTHS[heading.group('month').lower()]
        day = None
        for year in (now.year - 1, now.year, now.year + 1):
            try:
                candidate = datetime(year, month, int(heading.group('day'))).date()
            except ValueError:
                continue
            if (_plain_fold(heading.group('weekday')) == _COP_WEEKDAYS[candidate.weekday()]
                    and now.date() - timedelta(days=31) <= candidate
                    <= now.date() + timedelta(days=MAX_DAYS)):
                day = candidate
                break
        if day is None:
            continue
        end_pos = dates[i + 1].start() if i + 1 < len(dates) else len(region)
        section = region[heading.end():end_pos]
        entries = list(_EDELAP_SLOT.finditer(section))[:100]
        for j, entry in enumerate(entries):
            next_pos = entries[j + 1].start() if j + 1 < len(entries) else len(section)
            zone_text = section[entry.end():next_pos].split(';', 1)[0]
            zone = _clean(zone_text, 700).strip(' .,;:-')
            place = _EDELAP_LOCALITY_RE.search(zone)
            if not place or len(zone) < 18:
                continue
            if re.search(r'\b(?:suspendid[oa]|cancelad[oa]|reprogramad[oa])\b', zone, re.I):
                continue
            def normalize_hour(h):
                bits = h.split(':')
                if len(bits) == 1:
                    return f'{int(bits[0]):02}:00'
                return f'{int(bits[0]):02}:{bits[1]}'
            try:
                start = _datetime(day, normalize_hour(entry.group('start')))
                end = _datetime(day, normalize_hour(entry.group('end')))
            except ValueError:
                continue
            if start >= end:
                continue
            seen += 1
            newest = max(day, newest) if newest else day
            records.append(_notice(
                'EDELAP', 'Buenos Aires', PROVIDERS['edelap_la_plata'][2],
                place.group(1), start, end, zone,
                'Obra de mejora programada; puede requerir una interrupción del suministro'))
    return _filter_window(records, now), seen, newest




# Concordia's electric cooperative publishes a public four-column table:
# Fecha | Horario | Zona afectada | Motivo del corte. This source is limited
# to scheduled works in the cooperative's service area, NEVER live outages.
# Missing rows are unverified, and pages with only old schedules are stale.
_COOPELEC_DATE = re.compile(r'(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)')
_COOPELEC_WINDOW = re.compile(
    r'(?<!\d)(\d{1,2}:\d{2})\s*(?:a|hasta|[-–])\s*(\d{1,2}:\d{2})(?!\d)',
    re.I)


def _parse_coopelec(html, now):
    dom, visible = _visible(html)
    if not (re.search(r'\bcortes\s+programados\b', visible, re.I)
            and re.search(r'\bzona\s+afectada\b', visible, re.I)
            and re.search(r'\bmotivo\s+del\s+corte\b', visible, re.I)):
        return [], 0, None
    notices, seen, newest = [], 0, None
    for kind, cells in dom.events:
        if kind != 'row' or not isinstance(cells, list) or len(cells) != 4:
            continue
        date_raw, period_raw, zone_raw, task_raw = [_clean(x, 900) for x in cells]
        date_match = _COOPELEC_DATE.fullmatch(date_raw)
        if not date_match:
            continue
        try:
            day = datetime(int(date_match.group(3)), int(date_match.group(2)),
                           int(date_match.group(1))).date()
        except ValueError:
            continue
        # The date belongs to an actual schedule row, not a page footer.
        # Track older schedules as stale instead of treating them as current.
        seen += 1
        newest = max(newest, day) if newest else day
        hours = _COOPELEC_WINDOW.search(period_raw)
        if not hours or len(re.findall(r'(?<!\d)\d{1,2}:\d{2}(?!\d)', period_raw)) != 2:
            continue
        try:
            start, stop = _datetime(day, hours.group(1)), _datetime(day, hours.group(2))
        except ValueError:
            continue
        if not start < stop <= start + timedelta(hours=16):
            continue
        zone, task = _clean(zone_raw), _clean(task_raw, 240)
        if (len(zone) < 15 or not task or
                re.search(r'\b(?:suspendid[oa]|cancelad[oa]|reprogramad[oa]|sin corte)\b',
                          ' '.join([zone, task]), re.I)):
            continue
        notices.append(_notice('COOPELEC', 'Entre Ríos',
                               PROVIDERS['coopelec_concordia'][2],
                               'Concordia', start, stop, zone, task))
    return _filter_window(notices, now), seen, newest



# v5.29: Five public provincial/cooperative source candidates, intentionally
# conservative. A page heading, social post or publication date alone cannot
# establish a scheduled outage. The article collector reads only official HTTPS
# hosts and never labels past, cancelled or image-only notices as current.
_MONTHS_V529 = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
                'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
                'septiembre': 9, 'setiembre': 9, 'octubre': 10,
                'noviembre': 11, 'diciembre': 12}
_ABBR_MONTHS_V529 = {'ENE':1, 'FEB':2, 'MAR':3, 'ABR':4, 'MAY':5,
                     'JUN':6, 'JUL':7, 'AGO':8, 'SEP':9, 'OCT':10,
                     'NOV':11, 'DIC':12}
_V529_DATE = re.compile(r'(?<!\d)(\d{1,2})\s+de\s+'
                        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                        r'septiembre|setiembre|octubre|noviembre|diciembre)'
                        r'(?:\s+de\s+(20\d{2}))?', re.I)
_V529_HOURS = re.compile(
    r'(?:desde\s+las?\s+|de\s+|entre\s+las?\s+)?'
    r'(\d{1,2}[:.]\d{2})\s*(?:hs?\.?)?\s*'
    r'(?:y\s+hasta\s+las?\s+|hasta\s+las?\s+|a\s+las?\s+|[-–]|a\s+|y\s+las?\s+)'
    r'(\d{1,2}[:.]\d{2})\s*(?:hs?\.?)?', re.I)


def _parse_corpico_v529(html, now):
    _, visible = _visible(html)
    if not re.search(r'\bcortes?\s+programad', visible, re.I):
        return [], 0, None
    # The provider can explicitly state no planned outages; handled separately
    # by collect_one, not forged into a published date.
    notices, seen, newest = [], 0, None
    pattern = re.compile(r'(?<!\d)(\d{1,2})\s+'
                         r'(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)'
                         r'\.?\s+(20\d{2})', re.I)
    matches = list(pattern.finditer(visible))
    for i, m in enumerate(matches[:80]):
        section = visible[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(visible)]
        try:
            day = datetime(int(m.group(3)), _ABBR_MONTHS_V529[m.group(2).upper()], int(m.group(1))).date()
        except (ValueError, KeyError):
            continue
        times = _V529_HOURS.search(section)
        # A map/image is not a sufficiently detailed affected zone. Explicit
        # street or neighborhood text is required for each independent entry.
        zone_m = re.search(r'Zona\s+Afectada\s*:?\s*(.{18,220}?)'
                           r'(?=\s+(?:Ver\s+Mapa|Mantenimiento|Te\s+Comunicamos|$))',
                           section, re.I)
        if not times or not zone_m:
            continue
        zone = _clean(zone_m.group(1))
        if re.fullmatch(r'(?:Ver\s+Mapa|Imagen|Image|Zona\s+Afectada|\s|\W)+', zone, re.I):
            continue
        try:
            start = _datetime(day, times.group(1).replace('.', ':'))
            end = _datetime(day, times.group(2).replace('.', ':'))
        except ValueError:
            continue
        if not start < end <= start + timedelta(hours=16):
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        notices.append(_notice('CORPICO', 'La Pampa', PROVIDERS['corpico_general_pico'][2],
                               'General Pico', start, end, zone, 'Corte programado publicado por CORPICO'))
    return _filter_window(notices, now), seen, newest


def _parse_edelar_v529(html, now):
    # A maintenance plan listing REGIONS is not an outage schedule. EDELAR's
    # public interface normally requests an NIS; do not submit identifiers.
    _, visible = _visible(html)
    if not re.search(r'cortes?\s+programados?', visible, re.I):
        return [], 0, None
    notices, seen, newest = [], 0, None
    # Require rows containing explicit date, time range and affected street
    # or neighborhood in the SAME row; no global page-date association.
    dom, _ = _visible(html)
    for kind, cells in dom.events:
        if kind != 'row' or len(cells) < 3:
            continue
        line = ' | '.join(cells)
        dm = re.search(r'(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)', line)
        hours = _V529_HOURS.search(line)
        zone_cell = next((c for c in cells if re.search(r'\b(?:barrio|calle|sector|localidad|zona)\b', c, re.I)
                          and len(c) > 18 and c != cells[0]), None)
        if not (dm and hours and zone_cell):
            continue
        try:
            day = datetime(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).date()
            start = _datetime(day, hours.group(1).replace('.', ':'))
            end = _datetime(day, hours.group(2).replace('.', ':'))
        except ValueError:
            continue
        if not start < end <= start + timedelta(hours=16):
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        notices.append(_notice('EDELAR', 'La Rioja', PROVIDERS['edelar_la_rioja'][2],
                               'Zona informada por EDELAR', start, end,
                               zone_cell, 'Trabajo programado publicado'))
    return _filter_window(notices, now), seen, newest


def _parse_misiones_v529(html, now):
    # The province's public filter form may load schedules through JS. Only
    # actual HTML table rows with complete date/hours/zone may pass.
    dom, visible = _visible(html)
    if not re.search(r'cortes?\s*programados?', visible, re.I):
        return [], 0, None
    notices, seen, newest = [], 0, None
    for kind, cells in dom.events:
        if kind != 'row' or len(cells) < 3:
            continue
        line = ' | '.join(cells)
        dm = re.search(r'(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)', line)
        hours = _V529_HOURS.search(line)
        zone = next((c for c in cells if re.search(r'\b(?:localidad|barrio|zona|sector)\b', c, re.I)
                     and len(c) > 18), '')
        if not (dm and hours and zone):
            continue
        try:
            day = datetime(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).date()
            start = _datetime(day, hours.group(1).replace('.', ':'))
            end = _datetime(day, hours.group(2).replace('.', ':'))
        except ValueError:
            continue
        if not start < end <= start + timedelta(hours=16):
            continue
        seen += 1
        newest = max(newest, day) if newest else day
        notices.append(_notice('Energía de Misiones', 'Misiones',
                               PROVIDERS['energia_misiones'][2], 'Zona indicada en fuente',
                               start, end, zone, 'Trabajo programado publicado'))
    return _filter_window(notices, now), seen, newest


class _ArticleLinksV529(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.active = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.active = (dict(attrs).get('href', ''), [])

    def handle_data(self, value):
        if self.active is not None:
            self.active[1].append(value)

    def handle_endtag(self, tag):
        if tag == 'a' and self.active is not None:
            raw, pieces = self.active
            self.active = None
            link = urljoin(self.base, raw)
            if not link.startswith('https://') or len(link) > 250:
                return
            host = urlsplit(link).hostname or ''
            root = urlsplit(self.base).hostname or ''
            if host != root:
                return
            if not re.search(r'\b(?:corte|trabajo|programad|interrupci[oó]n)\b|(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d)',
                             _clean(' '.join(pieces)), re.I):
                return
            if link not in [u for u, _ in self.links]:
                self.links.append((link, _clean(' '.join(pieces))))


def _parse_official_article_v529(html, now, company, province, url):
    # Must be an announced future work, NOT a historic incident, a news-only
    # headline, a scheduled-water story, or an image with unreadable details.
    _, visible = _visible(html)
    if re.search(r'\b(?:suspendid[oa]s?|cancelad[oa]s?|se\s+suspende|reprogramad[oa]s?)\b',
                 visible, re.I):
        return [], 0, None
    if not re.search(r'\b(?:programad[oa]s?|previst[oa]s?|mantenimiento)\b', visible, re.I):
        return [], 0, None
    if company == 'SCPL':
        # A water bulletin may happen to mention electricity in a footer or
        # maintenance explanation. It must never enter the electric feed.
        if re.search(r'\b(?:corte|interrupci[oó]n)\s+(?:programad[oa]\s+)?de\s+agua\b', visible, re.I):
            return [], 0, None
        if not re.search(r'\b(?:corte|interrupci[oó]n)\s+(?:programad[oa]\s+)?de\s+energ[ií]a\b|'
                         r'\bsuministro\s+el[eé]ctrico\b', visible, re.I):
            return [], 0, None
    # Publication date supplies the year ONLY when the body names a precise
    # day/month and the year is close to that date. Publication alone is not
    # an event and cannot be used as the scheduled day.
    pub = re.search(r'(?<!\d)(\d{2})-(\d{2})-(20\d{2})(?!\d)', visible)
    if company == 'CALF' and not pub:
        pub_alt = re.search(r'\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                            r'septiembre|octubre|noviembre|diciembre)\s+\d{1,2},\s*20\d{2}', visible, re.I)
        if pub_alt:
            pub = None  # there is still no safely parsed event date from this marker
    daymatch = _V529_DATE.search(visible)
    hours = _V529_HOURS.search(visible)
    zone_m = re.search(r'\b(?:en\s+los\s+siguientes\s+barrios|zonas?\s+afectadas?|'
                       r'sectores?\s+afectados?)\s*:\s*(.{20,500}?)'
                       r'(?=\s+(?:con\s+el\s+objetivo|su\s+realizaci[oó]n|'
                       r'Depto\.|se\s+solicita|fin\s+del\s+comunicado|$))',
                       visible, re.I)
    if not (daymatch and hours and zone_m):
        return [], 0, None
    year_text = daymatch.group(3)
    if year_text:
        year = int(year_text)
    elif pub:
        year = int(pub.group(3))
    else:
        return [], 0, None
    try:
        day = datetime(year, _MONTHS_V529[daymatch.group(2).lower()], int(daymatch.group(1))).date()
        start = _datetime(day, hours.group(1).replace('.', ':'))
        end = _datetime(day, hours.group(2).replace('.', ':'))
    except (ValueError, KeyError):
        return [], 0, None
    if not start < end <= start + timedelta(hours=16):
        return [], 0, None
    zone = _clean(zone_m.group(1))
    if not zone or re.search(r'\b(?:imagen|image|ver\s+mapa|sin\s+datos)\b', zone, re.I):
        return [], 0, None
    item = _notice(company, province, url,
                   'Comodoro Rivadavia' if company == 'SCPL' else 'Neuquén capital',
                   start, end, zone, 'Interrupción programada publicada por la cooperativa')
    return _filter_window([item], now), 1, day



def _parse_ceb_article_v529(html, now, url):
    """CEB Bariloche: verify date in article heading/URL against body date.

    An anomalous archive title like 23/11/2026 for an article saying 23 de
    enero MUST NOT become a fictitious November notice.
    """
    _, visible = _visible(html)
    if re.search(r'\b(?:suspendid[oa]|cancelad[oa]|reprogramad[oa])\b', visible, re.I):
        return [], 0, None
    if not re.search(r'\b(?:corte programado|interrupci[oó]n programada|'
                     r'corte de energ[ií]a el[eé]ctrica)\b', visible, re.I):
        return [], 0, None
    # The official archive uses dd/mm/yyyy article titles and dated slugs.
    # Require exactly one distinct announced date, and verify it in the body.
    dates = re.findall(r'(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)', visible[:1100])
    if not dates:
        dates = re.findall(r'(?<!\d)(\d{1,2})-(\d{1,2})-(20\d{2})(?!\d)',
                           urlsplit(url).path)
    if len(set(dates)) != 1:
        return [], 0, None
    d, m, y = dates[0]
    try:
        title_day = datetime(int(y), int(m), int(d)).date()
    except ValueError:
        return [], 0, None
    event_dates = list(_V529_DATE.finditer(visible))
    # The date in prose must agree with the article's day/month, rather than
    # treating a misleading archive title as a second actual cut.
    matching_dates = [x for x in event_dates
                      if int(x.group(1)) == title_day.day
                      and _MONTHS_V529[x.group(2).lower()] == title_day.month
                      and (not x.group(3) or int(x.group(3)) == title_day.year)]
    if not matching_dates:
        return [], 0, None
    # If the text offers another specific day/month in the same announced-work
    # paragraph, it may be a multi-event publication: reject until disambiguated.
    for other in event_dates:
        if other.start() > matching_dates[0].start() and other.start() - matching_dates[0].start() < 250:
            if int(other.group(1)) != title_day.day or _MONTHS_V529[other.group(2).lower()] != title_day.month:
                return [], 0, None
    times = _V529_HOURS.search(visible)
    # The 11/11 official note puts a short affected zone directly before the
    # 'Invertir en mantenimiento' subsection. The old parser skipped it.
    # Stop before the next independent editorial heading, never swallow a
    # second notice or the site footer as if it were an affected street.
    zone = re.search(r'\bZona\s+afectada\s*:?\s*(.{12,500}?)'
                     r'(?=\s+(?:Invertir\s+en\s+mantenimiento|'
                     r'Mantenimiento\s+peri[oó]dico|'
                     r'Una\s+red|Las\s+tareas|Este\s+tipo|'
                     r'La\s+CEB\s+contin[uú]a|RED\s+CONFIABLE|'
                     r'\bPublicado\b|\bMotivo\b|$))', visible, re.I)
    if not times or not zone:
        return [], 0, None
    detail = _clean(zone.group(1))
    if len(detail) < 20 or re.search(r'\b(?:imagen|ver mapa|sin datos)\b', detail, re.I):
        return [], 0, None
    try:
        start = _datetime(title_day, times.group(1).replace('.', ':'))
        end = _datetime(title_day, times.group(2).replace('.', ':'))
    except ValueError:
        return [], 0, None
    if not start < end <= start + timedelta(hours=16):
        return [], 0, None
    notice = _notice('CEB', 'Río Negro', url, 'San Carlos de Bariloche',
                     start, end, detail, 'Mantenimiento programado anunciado por CEB')
    return _filter_window([notice], now), 1, title_day


def _collect_article_source_v529(key, checked_at, now, fetch):
    company, province, url = PROVIDERS[key]
    result = {'status': 'unverified', 'province': province, 'country': 'Argentina',
              'company': company, 'source_url': url, 'checked_at': checked_at,
              'coverage_kind': 'planned_outages_only', 'notices': [],
              'parser_revision': ('SCPL-ARTICLES-v5.30' if key == 'scpl_comodoro' else
                                  'CEB-ARTICLES-v5.30' if key == 'ceb_bariloche' else
                                  'ARTICLES-SAFE-v5.29'), 'source_attempts': [],
              'message': 'No se verificaron trabajos futuros con zona y horario.'}
    try:
        page, chosen = None, None
        for candidate in ([url, SCPL_ALTERNATE] if key == 'scpl_comodoro' else [url]):
            try:
                page = fetch(candidate)
                chosen = candidate
                break
            except Exception as exc:
                result['source_attempts'].append({'url': candidate,
                                                  'result': 'fetch_or_parse_error',
                                                  'error_type': type(exc).__name__})
        if chosen is None:
            result['message'] = 'No se pudo consultar ninguna dirección pública oficial.'
            return result
        result['source_url'] = chosen
        attempt = {'url': chosen, **_diagnose_html(page, chosen, key)}
        result['source_attempts'].append(attempt)
        links = _ArticleLinksV529(chosen)
        links.feed(page)
        # SCPL articles may also reference water or old incidents. Each article
        # is validated against full content; homepage alone never makes a notice.
        candidates = [(u, t) for (u, t) in links.links if (
            key == 'ceb_bariloche'
            and not urlsplit(u).path.startswith('/category/')
            and u != url
            and re.search(r'(?:corte|programad|(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d))', t, re.I)
            or key == 'calf_neuquen'
            and not urlsplit(u).path.startswith('/category/')
            and u != url
            and re.search(r'\b(?:corte|trabajos?)\b', t, re.I)
            or key == 'scpl_comodoro'
            and '/site/ver-nota' in urlsplit(u).path
            and re.search(r'\b(?:corte|trabajos?)\b', t, re.I)
        )]
        result['article_links_seen'] = len(candidates)
        seen, newest, notices = 0, None, []
        for article_url, title in candidates[:8]:
            if key == 'scpl_comodoro' and not re.search(r'\b(?:programad[oa]s?|mantenimiento)\b', title, re.I):
                continue
            try:
                article = fetch(article_url)
                if key == 'ceb_bariloche':
                    parsed, count, date = _parse_ceb_article_v529(article, now, article_url)
                else:
                    parsed, count, date = _parse_official_article_v529(
                        article, now, company, province, article_url)
                result['source_attempts'].append({'url': article_url, 'result': 'parsed' if count else 'no_complete_records'})
                seen += count
                if date:
                    newest = max(newest, date) if newest else date
                notices.extend(parsed)
            except Exception as exc:
                result['source_attempts'].append({'url': article_url, 'result': 'fetch_or_parse_error',
                                                  'error_type': type(exc).__name__})
        result['articles_checked'] = sum(1 for a in result['source_attempts'][1:] if a['result'] != 'fetch_or_parse_error')
        result['records_checked'] = seen
        if newest is not None:
            result['latest_published_date'] = newest.isoformat()
            if newest < (now - timedelta(days=2)).date():
                result['status'] = 'stale'
                result['message'] = 'Solo se verificaron trabajos antiguos; no hay avisos futuros completos.'
            else:
                result['status'] = 'ok'
                result['notices'] = _filter_window(notices, now)
                result['message'] = ('Trabajos previstos verificados; no confirman corte actual.' if result['notices']
                                     else 'No hay trabajos futuros completos reconocidos; no confirma servicio normal.')
        elif not candidates:
            result['message'] = 'No hay comunicados públicos con datos completos de cortes programados.'
        else:
            result['message'] = 'Comunicados revisados sin fecha, horario y zona verificables (pueden ser imágenes).'
    except Exception as exc:
        result['source_attempts'].append({'url': url, 'result': 'fetch_or_parse_error',
                                          'error_type': type(exc).__name__})
        result['message'] = 'No se pudo consultar la fuente oficial: ' + type(exc).__name__
    return result


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
        'ejesa_jujuy': r'(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)',
        'edet_tucuman': r'(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)',
        'edemsa_mendoza': r'(?<!\d)\d{2}-\d{2}-20\d{2}\s+\d{2}:\d{2}:\d{2}(?!\d)',
        'copelco_neuquen': r'\b\d{1,2}\s+(?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\b',
        'cpe_la_pampa': r'\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+20\d{2}\b',
        'edelap_la_plata': r'\b(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b',
        'coopelec_concordia': r'(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d)',
        'corpico_general_pico': r'(?<!\d)\d{1,2}\s+(?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)\.?\s+20\d{2}',
        'calf_neuquen': r'\b\d{1,2}\s+noviembre,?\s+20\d{2}',
        'energia_misiones': r'(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d)',
        'edelar_la_rioja': r'(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d)',
        'scpl_comodoro': r'(?<!\d)\d{2}-\d{2}-20\d{2}(?!\d)',
        'ceb_bariloche': r'(?<!\d)\d{1,2}/\d{1,2}/20\d{2}(?!\d)',
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



# v5.30: official public notices. No inference from a landing page, a generic
# service status, a publication without a specific scheduled day, or news of
# completed works.  A site can answer without giving verifiable future work.
_V530_MES = _MONTHS_V529
_V530_DMY = re.compile(r'(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)')
_V530_PUB = re.compile(r'\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                        r'septiembre|octubre|noviembre|diciembre)\s+(\d{1,2}),\s*(20\d{2})\b', re.I)


def _future_row_v530(html, now, company, province, url, locality):
    """Only truly independent table rows with date, two times, and zone.

    Generic page banners never become a scheduled outage. Deliberately do not
    parse broad prose here: rows provide structure needed for attribution.
    """
    parser, visible = _visible(html)
    found, newest, count = [], None, 0
    for kind, cells in parser.events:
        if kind != 'row' or not isinstance(cells, list):
            continue
        joined = ' '.join(cells)
        if company == 'SPSE' and not re.search(
                r'\b(?:energ[ií]a|el[eé]ctrico|electricidad)\b', joined, re.I):
            # SPSE also operates the public WATER service; never mislabel it.
            continue
        day_m = _V530_DMY.search(joined)
        hours = _V529_HOURS.search(joined)
        if not day_m or not hours or len(cells) < 3:
            continue
        try:
            day = datetime(int(day_m.group(3)), int(day_m.group(2)), int(day_m.group(1))).date()
            start = _datetime(day, hours.group(1).replace('.', ':'))
            end = _datetime(day, hours.group(2).replace('.', ':'))
        except ValueError:
            continue
        if not start < end <= start + timedelta(hours=16):
            continue
        # Require a standalone free-text affected zone, never use the date or
        # a generic 'ver mapa' image in place of locality-specific information.
        zones = [z for z in cells if len(z) >= 16 and not _V530_DMY.search(z)
                 and not _V529_HOURS.search(z)
                 and not re.search(r'^(?:fecha|hora|zona|ver mapa|sin datos)', z, re.I)]
        if not zones:
            continue
        zone = max(zones, key=len)
        if company == 'SPSE':
            # Santa Cruz distributes across several independent municipalities.
            # A province-wide alert may NOT use a generic locality as a match.
            localities = ('Río Gallegos', 'Rio Gallegos', 'Caleta Olivia',
                          'Puerto San Julián', 'San Julián', 'El Calafate',
                          'Río Turbio', 'Rio Turbio', 'Puerto Santa Cruz',
                          'Piedra Buena', 'Puerto Deseado', 'Los Antiguos',
                          'Perito Moreno', 'Las Heras', '28 de Noviembre',
                          'Pico Truncado', 'Gobernador Gregores')
            matches = [place for place in localities if re.search(
                r'(?<!\w)' + re.escape(place) + r'(?!\w)', zone, re.I)]
            if len(matches) != 1:
                continue
            locality = matches[0]
        if re.search(r'\b(?:imagen|image|ver\s+mapa|sin datos)\b', zone, re.I):
            continue
        if re.search(r'\b(?:cancelad[oa]|suspendid[oa]|reprogramad[oa])\b', joined, re.I):
            continue
        count += 1
        newest = max(newest, day) if newest else day
        found.append(_notice(company, province, url, locality, start, end, zone,
                             'Trabajo programado según tabla oficial'))
    return _filter_window(found, now), count, newest


def _pub_date_v530(text):
    match = _V530_PUB.search(text)
    if match:
        try:
            return datetime(int(match.group(3)), _V530_MES[match.group(1).lower()],
                            int(match.group(2))).date()
        except (ValueError, KeyError):
            return None
    match = re.search(r'(?<!\d)(\d{1,2})\s+de\s+'
                      r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                      r'septiembre|octubre|noviembre|diciembre)\s+de\s+(20\d{2})(?!\d)', text, re.I)
    if match:
        try:
            return datetime(int(match.group(3)), _V530_MES[match.group(2).lower()],
                            int(match.group(1))).date()
        except (ValueError, KeyError):
            return None
    return None




def _scope_official_article_v530(html):
    # WordPress themes include a navigation menu listing both energy and
    # water. Check the article body only; do not reject an electric work
    # merely because the site's navbar says 'Agua potable'.
    for tag in ('article', 'main'):
        match = re.search(r'(?is)<' + tag + r'\b[^>]*>.*?</' + tag + r'\s*>', html)
        if match:
            return match.group(0)
    return html

def _parse_servicoop_article_v530(html, now, url):
    """Future *electricity* interruption only, not water nor incident reports."""
    _, text = _visible(_scope_official_article_v530(html))
    _, whole = _visible(html)
    if re.search(r'\b(?:cancelad[oa]|suspendid[oa]|finalizaron|normaliz[oó]|restableci[oó]|'
                 r'reprogramad[oa])\b', text, re.I):
        return [], 0, None
    # Reject any article that discusses water interruption; never classify a
    # desalination or aqueduct maintenance note as an electricity outage.
    if re.search(r'\b(?:agua potable|acueductos?|saneamiento|bombeo presurizadora)\b', text, re.I):
        return [], 0, None
    if not re.search(r'\b(?:suministro\s+(?:el[eé]ctrico|de\s+energ[ií]a)|'
                     r'corte\s+de\s+energ[ií]a|interrumpir\s+el\s+servicio\s+de\s+energ[ií]a|'
                     r'personal\s+de\s+energ[ií]a)\b', text, re.I):
        return [], 0, None
    if not re.search(r'\b(?:corte|interrupci[oó]n|desafectar|interrumpir|'
                     r'falta\s+de\s+(?:servicio|suministro))\b', text, re.I):
        return [], 0, None
    published = _pub_date_v530(text[:1500]) or _pub_date_v530(whole[:2500])
    # body dates are explicit day+month; year may come ONLY from a specific
    # publication date within 7 calendar days of the announced event.
    # A street such as '25 de Mayo' is not a second event date. Read the
    # announced day only before the affected-zone description begins.
    zone_start = re.search(r'\b(?:falta\s+de\s+(?:servicio|suministro|energ[ií]a)\s+'
                           r'(?:afectar[aá]|afecta)|zonas?\s+afectad[oa]s?)\b', text, re.I)
    date_scope = text[:zone_start.start()] if zone_start else text
    dates = list(_V529_DATE.finditer(date_scope))
    if len({(m.group(1), m.group(2).lower(), m.group(3)) for m in dates}) != 1:
        return [], 0, None
    m = dates[0]
    year = int(m.group(3)) if m.group(3) else (published.year if published else None)
    if not year:
        return [], 0, None
    try:
        day = datetime(year, _V530_MES[m.group(2).lower()], int(m.group(1))).date()
    except (ValueError, KeyError):
        return [], 0, None
    if published and not timedelta(0) <= day - published <= timedelta(days=7):
        return [], 0, None
    hours = _V529_HOURS.search(text)
    # Mark a named or bounded service area, not a general network claim.
    zone = re.search(r'\b(?:falta\s+de\s+(?:servicio|suministro|energ[ií]a)\s+'
                     r'(?:afectar[aá]|afecta)\s+(?:a\s+)?(?:los\s+)?(?:usuarios\s+)?|'
                     r'(?:zonas?|barrios|sectores?)\s+afectad[oa]s?\s*:?\s*)'
                     r'(.{16,340}?)(?=\s+(?:Desconecte\s+los|'
                     r'este\s+corte\s+queda|Depto\.|Se\s+solicita|Compartir|$))', text, re.I)
    if not (hours and zone):
        return [], 0, None
    area = _clean(zone.group(1), 340)
    if re.search(r'\b(?:imagen|image|ver\s+mapa|sin\s+datos)\b', area, re.I):
        return [], 0, None
    try:
        start = _datetime(day, hours.group(1).replace('.', ':'))
        end = _datetime(day, hours.group(2).replace('.', ':'))
    except ValueError:
        return [], 0, None
    if not start < end <= start + timedelta(hours=16):
        return [], 0, None
    item = _notice('Servicoop', 'Chubut', url, 'Puerto Madryn', start, end,
                   area, 'Mantenimiento eléctrico programado informado por Servicoop')
    return _filter_window([item], now), 1, day


def _collect_servicoop_v530(key, checked_at, now, fetch):
    company, province, url = PROVIDERS[key]
    result = {'status': 'unverified', 'province': province, 'country': 'Argentina',
              'company': company, 'source_url': url, 'checked_at': checked_at,
              'coverage_kind': 'planned_outages_only', 'notices': [],
              'parser_revision': 'SERVICOOP-ARTICLES-v5.30', 'source_attempts': [],
              'coverage_area': 'Puerto Madryn y área servida, electricidad solamente',
              'message': 'Sin trabajos eléctricos futuros completos verificados.'}
    try:
        page = fetch(url)
        result['source_attempts'].append({'url': url, 'result': 'page_read'})
        links = _ArticleLinksV529(url)
        links.feed(page)
        # WordPress archive titles often say 'mantenimiento' rather than 'corte'.
        # A link still must have the exact official Servicoop hostname.
        class PostLinks(HTMLParser):
            def __init__(self):
                super().__init__(); self.u=None; self.t=[]; self.found=[]
            def handle_starttag(self, tag, attrs):
                if tag == 'a': self.u = dict(attrs).get('href',''); self.t=[]
            def handle_data(self, data):
                if self.u is not None: self.t.append(data)
            def handle_endtag(self, tag):
                if tag == 'a' and self.u is not None:
                    link = urljoin(url,self.u); title = _clean(' '.join(self.t))
                    if (urlsplit(link).scheme == 'https' and urlsplit(link).hostname ==
                            urlsplit(url).hostname and link not in self.found and
                            re.search(r'\b(?:corte|mantenimiento|subestaci[oó]n|'
                                      r'reconfiguraci[oó]n|modernizaci[oó]n)\b', title, re.I) and
                            not re.search(r'\b(?:agua|acueducto|finaliz|normaliz|restablec|'
                                          r'reprogramad|suspendid|cancelad)\b', title, re.I) and
                            '/category/' not in urlsplit(link).path and
                            '/page/' not in urlsplit(link).path):
                        self.found.append(link)
                    self.u = None
        finder=PostLinks(); finder.feed(page)
        # Do not fetch hundreds of archived articles; only top most recent.
        found, seen, newest=[], 0, None
        for link in finder.found[:8]:
            try:
                html=fetch(link)
                items,count,day=_parse_servicoop_article_v530(html,now,link)
                result['source_attempts'].append({'url':link,'result':'parsed' if count else 'no_complete_records'})
                seen+=count; found.extend(items)
                if day: newest=max(newest,day) if newest else day
            except Exception as exc:
                result['source_attempts'].append({'url':link,'result':'fetch_or_parse_error',
                                                  'error_type':type(exc).__name__})
        result['article_links_seen']=len(finder.found)
        result['articles_checked']=min(len(finder.found),8)
        result['records_checked']=seen
        if newest is not None:
            result['latest_published_date']=newest.isoformat()
            result['status']='stale' if newest < (now-timedelta(days=2)).date() else 'ok'
            result['notices']=_filter_window(found,now) if result['status']=='ok' else []
            result['message']=('Trabajos eléctricos publicados; NO son cortes confirmados.' if found
                               else 'Solo trabajos eléctricos antiguos; no significa suministro normal.')
    except Exception as exc:
        result['source_attempts'].append({'url':url,'result':'fetch_or_parse_error',
                                          'error_type':type(exc).__name__})
    return result


def _parse_usina_article_v530(html, now, url):
    """Full public official news item, not private office-virtual notices."""
    _,v=_visible(html)
    if re.search(r'\b(?:cancelad[oa]|suspendid[oa]|reprogramad[oa]|'
                 r'finaliz[oó]|restableci[oó]|se\s+normaliz[oó])\b',v,re.I):
        return [],0,None
    if not re.search(r'\bcorte\s+programado\b.*\bservicio\s+el[eé]ctrico\b',v,re.I):
        return [],0,None
    dated = re.search(r'/((?:20\d{2}))/(\d{2})/(\d{2})/',urlsplit(url).path)
    if not dated:
        return [],0,None
    try:
        pub=datetime(int(dated.group(1)),int(dated.group(2)),int(dated.group(3))).date()
    except ValueError:
        return [],0,None
    # Do not mistake a street called '4 de Abril' for an event date.
    boundary=re.search(r'Zona\s+comprendida\s*:',v,re.I)
    dates=list(_V529_DATE.finditer(v[:boundary.start()] if boundary else v))
    if len({(x.group(1),x.group(2).lower(),x.group(3)) for x in dates})!=1:
        return [],0,None
    m=dates[0]
    try:
        day=datetime(int(m.group(3)) if m.group(3) else pub.year,
                     _V530_MES[m.group(2).lower()],int(m.group(1))).date()
    except (ValueError,KeyError):
        return [],0,None
    if not timedelta(0) <= day-pub <= timedelta(days=7):
        return [],0,None
    times=re.search(r'\bentre\s+las?\s+(\d{1,2})(?::(\d{2}))?\s*(?:hs?)?\s+'
                    r'y\s+las?\s+(\d{1,2})(?::(\d{2}))?\s*hs?\b',v,re.I)
    if not times:
        return [],0,None
    try:
        start=_datetime(day,f'{int(times.group(1)):02d}:{times.group(2) or "00"}')
        end=_datetime(day,f'{int(times.group(3)):02d}:{times.group(4) or "00"}')
    except ValueError:
        return [],0,None
    if not start < end <= start+timedelta(hours=16):
        return [],0,None
    zone=re.search(r'Zona\s+comprendida\s*:\s*(.{18,350}?)'
                   r'(?=\s+(?:©|Solicit[aá]|$))',v,re.I)
    if not zone:
        return [],0,None
    detail=_clean(zone.group(1),350)
    if not re.search(r'\b(?:calle|avenida|av\.|barrio|poligonal|sector)\b',detail,re.I):
        return [],0,None
    n=_notice('Usina de Tandil','Buenos Aires',url,'Tandil',start,end,detail,
              'Corte programado publicado en noticias oficiales de la Usina')
    return _filter_window([n],now),1,day


def _collect_usina_v530(key, checked_at, now, fetch):
    company,province,url=PROVIDERS[key]
    out={'status':'unverified','province':province,'country':'Argentina',
         'company':company,'source_url':url,'checked_at':checked_at,
         'coverage_kind':'planned_outages_only','notices':[],
         'parser_revision':'USINA-PUBLIC-v5.30','source_attempts':[],
         'coverage_area':'Tandil (solamente noticias públicas)',
         'message':'No se verificaron comunicados recientes con horario y zona.'}
    try:
        html=fetch(url)
        out['source_attempts'].append({'url':url,'result':'page_read'})
        class Links(HTMLParser):
            def __init__(self): super().__init__();self.link=None;self.title=[];self.urls=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a': self.link=dict(attrs).get('href','');self.title=[]
            def handle_data(self,x):
                if self.link is not None:self.title.append(x)
            def handle_endtag(self,tag):
                if tag=='a' and self.link is not None:
                    u=urljoin(url,self.link)
                    if (urlsplit(u).scheme=='https' and
                            urlsplit(u).hostname==urlsplit(url).hostname and
                            re.search(r'/20\d{2}/\d{2}/\d{2}/',urlsplit(u).path) and
                            re.search(r'\bcorte\s+programado\b',_clean(' '.join(self.title)),re.I) and
                            u not in self.urls):self.urls.append(u)
                    self.link=None
        finder=Links();finder.feed(html)
        out['article_links_seen']=len(finder.urls)
        seen, newest, notices=0,None,[]
        for u in finder.urls[:6]:
            try:
                items,n,date=_parse_usina_article_v530(fetch(u),now,u)
                out['source_attempts'].append({'url':u,'result':'parsed' if n else 'no_complete_records'})
                seen+=n;notices.extend(items)
                if date:newest=max(newest,date) if newest else date
            except Exception as exc:
                out['source_attempts'].append({'url':u,'result':'fetch_or_parse_error',
                                               'error_type':type(exc).__name__})
        out['records_checked']=seen
        if newest:
            out.update(status='stale' if newest<(now-timedelta(days=2)).date() else 'ok',
                       latest_published_date=newest.isoformat())
            out['notices']=_filter_window(notices,now) if out['status']=='ok' else []
            out['message']=('Comunicados públicos verificables; no son cortes confirmados.' if notices
                            else 'Solo comunicados antiguos; no implica suministro normal.')
    except Exception as exc:
        out['source_attempts'].append({'url':url,'result':'fetch_or_parse_error',
                                      'error_type':type(exc).__name__})
    return out


def _collect_today_only_v530(key, checked_at, now, fetch):
    company, province, url=PROVIDERS[key]
    out={'status':'unverified','province':province,'country':'Argentina',
         'company':company,'source_url':url,'checked_at':checked_at,
         'coverage_kind':'planned_outages_only','notices':[],
         'parser_revision':'OFFICIAL-STATUS-v5.30','coverage_horizon':'today_only' if key=='cepa_punta_alta' else 'current_public_calendar',
         'source_attempts':[], 'message':'No se ha verificado un cronograma público completo.'}
    try:
        html=fetch(url)
        _,v=_visible(html)
        out['source_attempts'].append({'url':url,'html_bytes':len(html.encode('utf-8')),
                                       'result':'page_read'})
        if key=='cepa_punta_alta':
            explicit=bool(re.search(r'No\s+hay\s+trabajos\s+o\s+cortes\s+programados\s+en\s+el\s+d[ií]a\s+de\s+la\s+fecha',v,re.I))
        else:
            explicit=bool(re.search(r'Por\s+el\s+momento\s+no\s+se\s+encuentran\s+cortes?\s*/\s*interrupciones?\s+programad[oa]s?',v,re.I))
        if explicit:
            out.update(status='ok', records_checked=0,
                       message=('La fuente no publica trabajos programados HOY; '
                                'no confirma suministro normal ni ausencia de trabajos futuros.'
                                if key=='cepa_punta_alta' else
                                'La fuente declara no tener interrupciones programadas; '
                                'NO confirma servicio normal ni eventos imprevistos.'))
            out['source_attempts'][-1]['result']='explicit_no_planned_work'
            return out
        items,n,newest=_future_row_v530(html,now,company,province,url,
                     'Punta Alta' if key=='cepa_punta_alta' else 'Localidad indicada por SPSE')
        if n and newest:
            out.update(status='ok' if newest >= (now-timedelta(days=2)).date() else 'stale',
                       notices=items,records_checked=n,latest_published_date=newest.isoformat(),
                       message='Trabajos programados publicados, NO cortes confirmados.')
            out['source_attempts'][-1]['result']='verified_schedule'
    except Exception as exc:
        out['source_attempts'].append({'url':url,'result':'fetch_or_parse_error',
                                       'error_type':type(exc).__name__})
    return out


def collect_one(key, checked_at, fetcher=None, script_fetcher=None):
    if key not in PROVIDERS:
        raise KeyError(key)
    company, province, url = PROVIDERS[key]
    now = _instant(checked_at)
    if key == 'epen_neuquen':
        return _collect_epen(checked_at, now, fetcher or fetch_html)
    if key in ('cepa_punta_alta','spse_santa_cruz'):
        return _collect_today_only_v530(key, checked_at, now, fetcher or fetch_html)
    if key == 'servicoop_puerto_madryn':
        return _collect_servicoop_v530(key, checked_at, now, fetcher or fetch_html)
    if key == 'usina_tandil':
        return _collect_usina_v530(key, checked_at, now, fetcher or fetch_html)
    if key in ('calf_neuquen', 'scpl_comodoro', 'ceb_bariloche'):
        return _collect_article_source_v529(key, checked_at, now, fetcher or fetch_html)
    output = {'status': 'unverified', 'province': province, 'country': 'Argentina',
              'company': company, 'source_url': url, 'checked_at': checked_at,
              'coverage_kind': 'planned_outages_only', 'notices': [],
              'message': 'Sin verificación de publicaciones; no implica suministro normal.',
              'source_attempts': []}
    if key in ('corpico_general_pico', 'energia_misiones', 'edelar_la_rioja'):
        output['parser_revision'] = 'PUBLIC-WEB-v5.29'
        output['coverage_area'] = {'corpico_general_pico': 'General Pico',
                                   'energia_misiones': 'Zonas publicadas de Misiones',
                                   'edelar_la_rioja': 'Solo cronogramas públicos de La Rioja'}[key]
    if key == 'edersa_rio_negro':
        output['parser_revision'] = 'EDERSA-v5.18.1'
    if key == 'ejesa_jujuy':
        output['parser_revision'] = 'EJESA-WEB-v5.23'
    if key == 'edet_tucuman':
        output['parser_revision'] = 'EDET-WEB-v5.24'
    if key == 'coopelec_concordia':
        output['parser_revision'] = 'COOPELEC-WEB-v5.28'
        output['coverage_area'] = 'Concordia y zona de concesión de la cooperativa'
    if key == 'edelap_la_plata':
        output['parser_revision'] = 'EDELAP-WEB-v5.27'
        output['coverage_kind'] = 'planned_network_work_may_interrupt_only'
        output['coverage_area'] = 'La Plata y alrededores (jurisdicción EDELAP)'
    if key == 'copelco_neuquen':
        output['parser_revision'] = 'COPELCO-WEB-v5.26'
        output['coverage_area'] = 'Cutral Có y Plaza Huincul'
    if key == 'cpe_la_pampa':
        output['parser_revision'] = 'CPE-WEB-v5.26.1'
        output['coverage_area'] = 'Zona atendida por CPE, Santa Rosa'
    if key == 'edemsa_mendoza':
        output['parser_revision'] = 'EDEMSA-EPRE-v5.25'
        output['published_by'] = 'EPRE Mendoza (regulador provincial)'
    if key == 'edese_santiago_del_estero':
        output['parser_revision'] = 'EDESE-ENRESE-v5.21'
        output['published_by'] = 'ENRESE (ente regulador provincial)'
    fetch = fetcher or fetch_html
    if key == 'epe_santa_fe':
        pages = [url, EPE_LEGACY, EPE_LEGACY_ALT]
    elif key == 'epec_cordoba':
        pages = [url, EPEC_ALTERNATE]
    elif key == 'edese_santiago_del_estero':
        pages = [url, EDESE_ALTERNATE]
    elif key == 'cpe_la_pampa':
        # The old sitionuevo host returned HTTPError from GitHub Actions.
        # The official CPE service page is also published at cpe.coop.ar.
        # Both URLs are public CPE pages, and failures stay visible.
        pages = [url, CPE_ALTERNATE]
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
            elif key == 'ejesa_jujuy':
                notices, count, newest = _parse_ejesa(html, now)
            elif key == 'edet_tucuman':
                notices, count, newest = _parse_edet(html, now)
            elif key == 'edemsa_mendoza':
                notices, count, newest = _parse_edemsa_epre(html, now)
            elif key == 'copelco_neuquen':
                notices, count, newest = _parse_copelco(html, now)
            elif key == 'coopelec_concordia':
                notices, count, newest = _parse_coopelec(html, now)
            elif key == 'corpico_general_pico':
                _, corpo_visible = _visible(html)
                if re.search(r'\bno\s+hay\s+cortes?\s+programad', corpo_visible, re.I):
                    attempt.update(records_checked=0, result='explicit_no_planned_cuts')
                    output.update(status='ok', source_url=page, notices=[],
                                  records_checked=0, coverage_kind='planned_outages_only',
                                  message=('El sitio declara que no hay cortes PROGRAMADOS vigentes; '
                                           'NO confirma servicio eléctrico normal ni cortes imprevistos.'))
                    return output
                notices, count, newest = _parse_corpico_v529(html, now)
            elif key == 'energia_misiones':
                notices, count, newest = _parse_misiones_v529(html, now)
            elif key == 'edelar_la_rioja':
                notices, count, newest = _parse_edelar_v529(html, now)
            elif key == 'edelap_la_plata':
                notices, count, newest = _parse_edelap(html, now)
            elif key == 'cpe_la_pampa':
                notices, count, newest = _parse_cpe(html, now)
                # Keep each bulletin linked to the page actually read.
                for notice in notices:
                    notice['source_url'] = page
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
            if key == 'edelap_la_plata' and notices:
                output['message'] = ('Obras de red previstas que PUEDEN requerir interrupciones; '
                                     'NO confirman cortes actualmente en curso.')
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

"""Official dated EPEN bulletins for Neuquen, not confirmed active outages.

This source is the public EPEN Cortes Programados archive. Its article cards
contain dates and official links, but do NOT provide a live service status.
Only show plausible upcoming-date *bulletins*, never create electrical alerts,
notifications or assert that a scheduled cut is actually occurring.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

SOURCE_URL = 'https://www.epen.gov.ar/index.php/cortes-programados/'
RSS_URL = 'https://www.epen.gov.ar/index.php/feed/'
ART = timezone(timedelta(hours=-3))
MAX_BYTES = 700_000
MAX_LINKS = 200
MAX_AGE_DAYS = 21
MAX_FUTURE_DAYS = 14


def _normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower())
                   if not unicodedata.combining(c))


def _clean(value, limit=220):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _official_article(url):
    if not url:
        return None
    full = urljoin(SOURCE_URL, url.strip())
    parsed = urlsplit(full)
    if parsed.scheme != 'https' or (parsed.hostname or '').lower() not in ('epen.gov.ar', 'www.epen.gov.ar'):
        return None
    # Validate the WordPress permalink pattern; reject general pages and
    # user-controlled redirect/query parameters.
    m = re.fullmatch(r'/index\.php/(20\d\d)/(\d\d)/(\d\d)/[a-z0-9-]+/?', parsed.path, re.I)
    if not m:
        return None
    try:
        published = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return full.split('?')[0].split('#')[0], published


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignore = 0
        self.current = None
        self.depth = 0
        self.words = []
        self.link_attrs = {}
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignore += 1
            return
        if self.ignore:
            return
        if tag == 'a' and self.current is None:
            self.link_attrs = dict(attrs)
            self.current = self.link_attrs.get('href')
            self.words = []
            self.depth = 1
        elif self.current is not None:
            if tag == 'img':
                alternative = dict(attrs).get('alt', '')
                if alternative:
                    self.words.append(_clean(alternative, 350))
            self.depth += 1

    def handle_data(self, data):
        if not self.ignore and self.current is not None:
            word = _clean(data, 400)
            if word:
                self.words.append(word)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignore = max(self.ignore - 1, 0)
            return
        if self.ignore or self.current is None:
            return
        self.depth -= 1
        if tag == 'a' or self.depth <= 0:
            if len(self.links) < MAX_LINKS:
                title = _clean(' '.join(self.words), 350)
                if not title:
                    title = _clean(self.link_attrs.get('title') or self.link_attrs.get('aria-label') or '', 350)
                self.links.append((self.current, title))
            self.current = None
            self.words = []
            self.link_attrs = {}
            self.depth = 0


# The archive headlines publish ranges like "del 03 al 06/11/2026" or
# "del 3 al 5/11/26". The *last day* is used solely to filter old bulletins;
# do not infer daily schedules or a disruption in progress.
_RANGE_DATE = re.compile(r'\b(?:\d{1,2}\s*(?:al|y)\s*)?(\d{1,2})[/-](\d{1,2})[/-](20\d\d|\d\d)\b', re.I)


def _last_day_in_title(title):
    candidates = []
    for match in _RANGE_DATE.finditer(title):
        d, m, y = map(int, match.groups())
        y = y + 2000 if y < 100 else y
        try:
            candidates.append(date(y, m, d))
        except ValueError:
            continue
    return max(candidates) if candidates else None


def _extract_official_pairs(links, checked_at):
    """Only keep dated, upcoming bulletins with verifiable EPEN article URLs."""
    now = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('Comprobación sin zona horaria')
    today = now.astimezone(ART).date()
    notices = {}
    eligible = 0
    future_ends = 0
    for href, title in links:
        valid = _official_article(href)
        if valid is None:
            continue
        url, published = valid
        # Strict classification: refuse general news, suspended and canceled
        # announcements, future publication dates and old archive entries.
        ntitle = _normal(title)
        if (not any(k in ntitle for k in ('corte programado', 'cortes programados',
                                          'mantenimiento programado')) or
            any(k in ntitle for k in ('suspendid', 'cancelad', 'anulad', 'reprogramad'))):
            continue
        if not (today - timedelta(days=MAX_AGE_DAYS) <= published <= today):
            continue
        eligible += 1
        scheduled_last_day = _last_day_in_title(title)
        if scheduled_last_day is None:
            continue
        if not (today <= scheduled_last_day <= today + timedelta(days=MAX_FUTURE_DAYS)):
            continue
        future_ends += 1
        # Do not guess locality or hour from the title: one bulletin can list
        # many localities and different schedules within its body.
        notices[url] = {
            'id': 'epen-' + sha256(url.encode('utf-8')).hexdigest()[:18],
            'country': 'Argentina', 'province': 'Neuquén', 'company': 'EPEN',
            'kind': 'dated_official_planned_work_bulletin',
            'status': 'publication_only_not_current_outage',
            'title': title, 'published_on': published.isoformat(),
            'scheduled_last_day': scheduled_last_day.isoformat(),
            'source_url': url,
            'message': 'Comunicado oficial fechado; el estado y las zonas afectadas deben comprobarse en la fuente. No confirma un corte actual.',
        }
    return sorted(notices.values(), key=lambda n: (n['scheduled_last_day'], n['published_on'], n['title'])), eligible, future_ends



def extract_dated_bulletins(html, checked_at):
    """Read official archive article links; never infer outages in progress."""
    if not isinstance(html, str) or not html.strip() or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('HTML de EPEN vacío o demasiado grande')
    parser = _Links()
    parser.feed(html)
    return _extract_official_pairs(parser.links, checked_at)


def extract_rss_bulletins(xml, checked_at):
    """Read EPEN official RSS. RSS is a fallback when archive cards lack titles."""
    if not isinstance(xml, str) or not xml.strip() or len(xml.encode('utf-8')) > MAX_BYTES:
        raise ValueError('RSS de EPEN vacío o demasiado grande')
    root = ET.fromstring(xml)
    if root.tag not in ('rss', '{http://www.w3.org/2005/Atom}feed'):
        raise ValueError('La respuesta de EPEN no es RSS/Atom')
    pairs = []
    for item in root.findall('./channel/item')[:MAX_LINKS]:
        title = item.findtext('title', default='')
        url = item.findtext('link', default='')
        pairs.append((url, title))
    # A valid but empty RSS is not proof of normal electrical service.
    return _extract_official_pairs(pairs, checked_at)


def fetch_html(url=SOURCE_URL):
    if url not in (SOURCE_URL, RSS_URL):
        raise ValueError('Solo se permiten las páginas públicas oficiales de EPEN')
    req = Request(url, headers={'User-Agent':'HoyMeAfecta/0.5 (comunicados oficiales fechados)',
                                'Accept': 'text/html,application/xhtml+xml,application/rss+xml,application/xml',
                                'Accept-Language': 'es-AR,es;q=0.9'})
    with urlopen(req, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Respuesta de EPEN excesiva')
    return data.decode('utf-8-sig', errors='replace')


def collect_epen(checked_at, fetcher=None):
    output = {
        'status': 'unverified', 'country': 'Argentina', 'province': 'Neuquén',
        'company': 'EPEN', 'source_url': SOURCE_URL, 'checked_at': checked_at,
        'coverage_kind': 'dated_planned_work_bulletins_only', 'notices': [],
        'message': 'No se verificaron comunicados futuros; no significa servicio normal.',
    }
    try:
        html = (fetcher or fetch_html)(SOURCE_URL)
        items, eligible, future_ends = extract_dated_bulletins(html, checked_at)
        output['records_checked'] = eligible
        output['archive_candidates'] = eligible
        output['fallback_rss'] = 'not_needed'
        if not items:
            # EPEN publishes an official WordPress RSS feed. Its <item> fields
            # carry article titles even if the archive uses image-only links.
            # This is NOT an outage-status API and it never triggers push alerts.
            try:
                rss = (fetcher or fetch_html)(RSS_URL)
                rss_items, rss_eligible, _ = extract_rss_bulletins(rss, checked_at)
                output['rss_candidates'] = rss_eligible
                output['records_checked'] += rss_eligible
                if rss_items:
                    items = rss_items
                    output['fallback_rss'] = 'verified'
                else:
                    output['fallback_rss'] = 'no_upcoming_bulletins'
            except (OSError, UnicodeError, ValueError, TimeoutError, ET.ParseError) as exc:
                output['fallback_rss'] = 'unverified'
                output['rss_error_type'] = type(exc).__name__
        if items:
            output['notices'] = items
            output['status'] = 'ok'
            output['message'] = 'Comunicados oficiales fechados de trabajos previstos; NO son cortes en tiempo real ni alertas automáticas.'
        elif eligible:
            output['status'] = 'stale'
            output['message'] = 'Se encontraron comunicados fechados pero ninguno con fecha de trabajo futura verificable.'
    except (OSError, UnicodeError, ValueError, TimeoutError) as exc:
        output['message'] = 'Error al consultar EPEN: ' + type(exc).__name__
    return output

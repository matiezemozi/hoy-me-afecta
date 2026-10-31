"""Dated news from Trenes Argentinos, NEVER a live line status.

The public BA Transport API is currently described as suspended; do not infer
service availability from its documentation or from undated status pages.
If the official site changes its markup, this module fails closed.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request

SOURCE_URL = "https://www.argentina.gob.ar/transporte/trenes-argentinos"
MAX_BYTES = 700_000
MAX_AGE_DAYS = 21
MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9,
    'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}
DATE_PATTERN = re.compile(r'\b(\d{1,2})\s+de\s+(' + '|'.join(MONTHS) + r')\s+de\s+(20\d\d)\b', re.I)
LINES = ("Belgrano Sur", "San Martín", "Tren de la Costa", "Sarmiento", "Mitre", "Roca")
KEYWORDS = ('servicio', 'servicios', 'circul', 'interrump', 'demora', 'cancel',
            'reanud', 'retoma', 'frecuencia', 'horario', 'anden', 'parada', 'suspend',
            'restablec', 'modific', 'limitad')


def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower())
                   if not unicodedata.combining(c))


def _safe_article_href(href):
    if not href or href.startswith(('#', 'javascript:', 'mailto:')):
        return None
    full = urljoin(SOURCE_URL, href)
    p = urlparse(full)
    if p.scheme != 'https' or p.netloc != 'www.argentina.gob.ar':
        return None
    # An individual article, not an index, source link, or app link.
    if not (p.path.startswith('/noticias/') or re.fullmatch(r'/node/\d+', p.path)):
        return None
    return full.split('#')[0].split('?')[0]


class _Tokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.link = None
        self.tokens = []
        self.article_links = []
        self._link_parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if self.skip:
            return
        if tag == 'time' and a.get('datetime'):
            self.tokens.append((a['datetime'], None))
        if tag == 'a':
            self.link = _safe_article_href(a.get('href'))
            self._link_parts = []

    def handle_data(self, data):
        if self.skip:
            return
        text = ' '.join(data.split())
        if not text:
            return
        self.tokens.append((text, self.link))
        if self.link:
            self._link_parts.append(text)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == 'a':
            if self.link and self._link_parts:
                self.article_links.append((len(self.tokens) - 1,
                                          ' '.join(self._link_parts), self.link))
            self.link = None
            self._link_parts = []


def _published_date(tokens, end):
    # Dates on the listing are normally immediately before the article title.
    # Strict local window: do not inherit an unrelated earlier card's date.
    context = ' '.join(piece for piece, _ in tokens[max(0, end - 12):end + 1])
    matches = list(DATE_PATTERN.finditer(norm(context)))
    if matches:
        m = matches[-1]
        if len(context) - m.end() > 160:
            return None
        return datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=timezone.utc).date()
    # Support explicit HTML <time datetime="YYYY-MM-DD"> markup.
    for text, _ in reversed(tokens[max(0, end - 12):end + 1]):
        m = re.fullmatch(r'(20\d\d)-(\d\d)-(\d\d)(?:T.*)?', text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            except ValueError:
                return None
    return None


def parse_official_news(html, checked_at, max_age_days=MAX_AGE_DAYS):
    """Return (articles_with_valid_dates, relevant_currently_recent_articles).

    Publication date is *not* an outage or disruption start/end time.
    """
    checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if checked.tzinfo is None:
        raise ValueError('Fecha de revisión sin zona horaria')
    checked = checked.astimezone(timezone.utc)
    parser = _Tokens()
    parser.feed(html)
    found = 0
    relevant = []
    seen = set()
    for index, raw_title, url in parser.article_links:
        title = ' '.join(raw_title.split())
        if not 20 <= len(title) <= 200:
            continue
        published = _published_date(parser.tokens, index)
        if published is None:
            continue
        found += 1
        age_days = (checked.date() - published).days
        if not 0 <= age_days <= max_age_days:
            continue
        nt = norm(title)
        if not any(keyword in nt for keyword in KEYWORDS):
            continue
        matched = [line for line in LINES if norm(line) in nt]
        if not matched or url in seen:
            continue
        seen.add(url)
        relevant.append({
            'title': title,
            'line': matched[0] if len(matched) == 1 else 'Varias líneas',
            'published_on': published.isoformat(),
            'source_url': url,
            'kind': 'comunicado_oficial',
        })
    relevant.sort(key=lambda a: (a['published_on'], a['source_url']), reverse=True)
    return found, relevant[:10]


def fetch_official_html():
    request = Request(SOURCE_URL, headers={'User-Agent': 'HoyMeAfecta/0.5 (public notices; no live status)'})
    with urlopen(request, timeout=16) as response:
        if response.geturl().split('/')[2] != 'www.argentina.gob.ar':
            raise ValueError('Redirección a un dominio no oficial')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Página oficial demasiado grande')
    return raw.decode('utf-8-sig', errors='replace')


def collect_rail_notices(checked_at, fetch_html=None):
    """Never return alleged live service status; include error/unverified clearly."""
    output = {
        'status': 'unverified', 'checked_at': checked_at, 'source_url': SOURCE_URL,
        'message': 'Comunicados fechados, NO estado en tiempo real. Confirmá antes de viajar.',
        'notices': [],
    }
    try:
        body = fetch_html() if fetch_html is not None else fetch_official_html()
        if not isinstance(body, str):
            raise ValueError('Contenido HTML inválido')
        dated, notices = parse_official_news(body, checked_at)
        if dated == 0:
            output['message'] = 'No se pudo verificar fecha y enlace de los comunicados oficiales.'
        else:
            output['status'] = 'ok'
            output['notices'] = notices
            output['dated_items_checked'] = dated
    except (OSError, UnicodeError, ValueError) as exc:
        output['status'] = 'error'
        output['message'] = 'No se pudo consultar o verificar la fuente oficial: ' + type(exc).__name__
    return output

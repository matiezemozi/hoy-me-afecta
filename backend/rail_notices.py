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
NEWS_INDEX_URL = SOURCE_URL + "/noticias"
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
    """Read dated news links even when a *whole card* is a single <a>.

    On the official Drupal website the card link may contain date, heading
    and teaser together, not just the title. The older parser rejected these
    links because the combined text exceeded 200 characters.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.link = None
        self.tokens = []
        self.article_links = []
        self._link_parts = []
        self._heading_parts = []
        self._heading_depth = 0
        self._link_first_token = 0

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
            self._link_first_token = len(self.tokens)
            self._link_parts = []
            self._heading_parts = []
            self._heading_depth = 0
        if tag in ('h2', 'h3', 'h4', 'h5', 'h6') and self.link:
            self._heading_depth += 1

    def handle_data(self, data):
        if self.skip:
            return
        value = ' '.join(data.split())
        if not value:
            return
        self.tokens.append((value, self.link))
        if self.link:
            self._link_parts.append(value)
            if self._heading_depth:
                self._heading_parts.append(value)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag in ('h2', 'h3', 'h4', 'h5', 'h6') and self._heading_depth:
            self._heading_depth -= 1
        if tag == 'a':
            if self.link and self._link_parts:
                self.article_links.append((self._link_first_token,
                                           list(self._link_parts),
                                           ' '.join(self._heading_parts), self.link))
            self.link = None
            self._link_parts = []
            self._heading_parts = []
            self._heading_depth = 0


def _read_date(text):
    match = DATE_PATTERN.search(norm(text))
    if match:
        try:
            return datetime(int(match.group(3)), MONTHS[match.group(2)],
                            int(match.group(1)), tzinfo=timezone.utc).date()
        except ValueError:
            return None
    return None


def _published_date(tokens, first_token, link_parts):
    # Official card dates sometimes appear WITHIN the clickable <a>, before
    # its title. Accept them only at the start, not in a body excerpt about
    # a future/past event, to avoid confusing event and publication dates.
    combined = ' '.join(link_parts)
    in_link = DATE_PATTERN.match(norm(combined))
    if in_link:
        return _read_date(in_link.group())
    # Otherwise require a date immediately before the link, within the same
    # listing card. Never inherit a distant date from an unrelated article.
    pieces = []
    for text, url in reversed(tokens[max(0, first_token - 5):first_token]):
        if url is not None:  # Never borrow a date across a previous article link.
            break
        pieces.insert(0, text)
    if pieces:
        prev = ' '.join(pieces)
        match = list(DATE_PATTERN.finditer(norm(prev)))
        if match and len(prev) - match[-1].end() <= 70:
            return _read_date(match[-1].group())
    for text in reversed(pieces):
        match = re.fullmatch(r'(20\d\d)-(\d\d)-(\d\d)(?:T.*)?', text)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)),
                                int(match.group(3))).date()
            except ValueError:
                return None
    return None


def _link_title(parts, heading):
    # If a heading is present inside the link, use it (not the teaser).
    if 20 <= len(heading.strip()) <= 200:
        return heading.strip()
    # The usual structure is date / title / summary inside one linked card.
    for part in parts:
        candidate = DATE_PATTERN.sub('', norm(part), count=1).strip()
        if not candidate or len(candidate) < 20 or len(candidate) > 200:
            continue
        if any(norm(line) in candidate for line in LINES) or \
           any(kw in candidate for kw in KEYWORDS):
            return part.strip()
    # Last resort: an ordinary title-only <a>, not a long teaser card.
    joined = ' '.join(parts).strip()
    joined = DATE_PATTERN.sub('', joined, count=1).strip()
    return joined if 20 <= len(joined) <= 200 else ''


def _article_line(title):
    title_norm = norm(title)
    found = [line for line in LINES if norm(line) in title_norm]
    # Precise aliases for lines whose official notices may name a ramal only.
    aliases = {
        'Mitre': ('ramal tigre', 'ramales suarez', 'ramales j. l. suarez',
                  'ramal jose leon suarez', 'ramal bme. mitre'),
        'Sarmiento': ('ramal once-moreno', 'ramal moreno-mercedes',
                     'ramal merlo-lobos'),
    }
    for line, patterns in aliases.items():
        if line not in found and any(p in title_norm for p in patterns):
            found.append(line)
    return (found[0] if len(found) == 1 else 'Varias líneas') if found else None


def parse_official_news(html, checked_at, max_age_days=MAX_AGE_DAYS):
    """Return (officially dated article count, recent railway notices).

    Never claim live train status; a publication date does not prove an
    interruption is happening now, or that it has ended.
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
    for first_token, parts, heading, url in parser.article_links:
        date = _published_date(parser.tokens, first_token, parts)
        if date is None:
            continue
        found += 1
        age = (checked.date() - date).days
        if not 0 <= age <= max_age_days:
            continue
        title = _link_title(parts, heading)
        if not title:
            continue
        nt = norm(title)
        if not any(keyword in nt for keyword in KEYWORDS):
            continue
        line = _article_line(title)
        if not line or url in seen:
            continue
        seen.add(url)
        relevant.append({
            'title': title, 'line': line, 'published_on': date.isoformat(),
            'source_url': url, 'kind': 'comunicado_oficial',
        })
    relevant.sort(key=lambda a: (a['published_on'], a['source_url']), reverse=True)
    return found, relevant[:10]


def fetch_official_html(url=SOURCE_URL):
    if url not in (SOURCE_URL, NEWS_INDEX_URL):
        raise ValueError('URL de consulta no permitida')
    request = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; HoyMeAfectaPilot/0.5; public articles)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urlopen(request, timeout=16) as response:
        target = urlparse(response.geturl())
        if target.scheme != 'https' or target.hostname != 'www.argentina.gob.ar':
            raise ValueError('Redirección a un dominio no oficial')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Página oficial demasiado grande')
    return raw.decode('utf-8-sig', errors='replace')


def collect_rail_notices(checked_at, fetch_html=None):
    """Dated official articles only. No claims about current train status."""
    output = {
        'status': 'unverified', 'checked_at': checked_at,
        'source_url': SOURCE_URL,
        'message': 'Comunicados fechados, NO estado en tiempo real. Confirmá antes de viajar.',
        'notices': [],
    }
    # In production try both official listings. Tests injecting HTML must not
    # unexpectedly access the network, so an injected fetch is single-source.
    urls = (SOURCE_URL,) if fetch_html else (SOURCE_URL, NEWS_INDEX_URL)
    failures = 0
    output['pages_attempted'] = []
    for url in urls:
        output['pages_attempted'].append(url)
        try:
            body = fetch_html() if fetch_html is not None else fetch_official_html(url)
            if not isinstance(body, str):
                raise ValueError('Contenido HTML inválido')
            dated, notices = parse_official_news(body, checked_at)
            if dated:
                output['status'] = 'ok'
                output['notices'] = notices
                output['dated_items_checked'] = dated
                output['source_url'] = url
                return output
        except (OSError, UnicodeError, ValueError) as exc:
            failures += 1
            output['message'] = 'No se pudo consultar o verificar la fuente oficial: ' + type(exc).__name__
    if failures == len(urls):
        output['status'] = 'error'
    else:
        output['message'] = 'No se pudo verificar fecha y enlace de los comunicados oficiales.'
    return output

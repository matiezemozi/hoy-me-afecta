"""DPEC Corrientes official planned-electricity-work announcements.

Only dated official articles linked from the DPEC public planned-outage
archive are eligible. These are NOT verified active outages. Never emit
ENRE-style live alerts or Android notification events from this source.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

SOURCE_URL = 'https://www.dpec.com.ar/comercial/cortes-programados/'
ART = timezone(timedelta(hours=-3))
MAX_BYTES = 1_200_000
MAX_LINKS = 700
MAX_FUTURE_DAYS = 21


def _normal(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text or '').lower())
                   if not unicodedata.combining(c))


def _clean(text, limit=480):
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:limit]


class _ArchiveLinks(HTMLParser):
    """Collect text-bearing anchors and preserve text inside nested elements."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.inside = False
        self.href = ''
        self.words = []
        self.ignored = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.ignored += 1
            return
        if self.ignored:
            return
        if tag == 'a':
            self._flush()
            self.inside = True
            self.href = attrs.get('href', '')
            self.words = []
            self.depth = 0
        elif self.inside:
            self.depth += 1
            if tag == 'img' and attrs.get('alt'):
                self.words.append(attrs['alt'])

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignored = max(self.ignored - 1, 0)
            return
        if self.ignored or not self.inside:
            return
        if tag == 'a':
            self._flush()
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.inside and not self.ignored:
            self.words.append(data)

    def _flush(self):
        if self.inside and len(self.links) < MAX_LINKS:
            self.links.append((self.href, _clean(' '.join(self.words))))
        self.inside = False
        self.href = ''
        self.words = []
        self.depth = 0


def _official_article(href):
    if not isinstance(href, str) or not href or len(href) > 500:
        return None
    full = urljoin(SOURCE_URL, href.strip())
    parts = urlsplit(full)
    if (parts.scheme != 'https' or parts.username or parts.password or
            parts.query or parts.fragment or parts.port or
            (parts.hostname or '').lower() not in ('www.dpec.com.ar', 'dpec.com.ar')):
        return None
    # Official DPEC article URLs: /8869 or /8869/title-of-article.
    if not re.fullmatch(r'/\d{3,7}(?:/[a-zA-Z0-9%_.-]{1,300})?/?', parts.path):
        return None
    return full


_DATE = re.compile(r'(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(20\d\d|\d\d)(?!\d)')
_TIME = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\b')
_STOP = ('suspendid', 'cancelad', 'anulad', 'reprogramad', 'postergad')


def _latest_date(title):
    dates = []
    for m in _DATE.finditer(title):
        day, month, year = map(int, m.groups())
        if year < 100:
            year += 2000
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue
    return max(dates) if dates else None


def extract_dpec_bulletins(html, checked_at):
    """Return (upcoming_bulletins, dated_article_count, archive_links)."""
    if not isinstance(html, str) or not html.strip() or len(html.encode('utf-8')) > MAX_BYTES:
        raise ValueError('DPEC HTML empty or too large')
    now = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    today = now.astimezone(ART).date()
    parser = _ArchiveLinks()
    parser.feed(html)
    parser._flush()
    notices = {}
    checked = 0
    candidate_links = 0
    for href, headline in parser.links:
        url = _official_article(href)
        if url is None:
            continue
        candidate_links += 1
        cleaned = _clean(headline, 350)
        if not cleaned or len(cleaned) < 18:
            continue
        when = _latest_date(cleaned)
        if when is None or not _TIME.search(cleaned):
            continue
        checked += 1
        if any(word in _normal(cleaned) for word in _STOP):
            continue
        if not (today <= when <= today + timedelta(days=MAX_FUTURE_DAYS)):
            continue
        # Title often names several cities or intervals. Do not infer unique
        # locality or a per-address schedule from the archive headline.
        notices[url] = {
            'id': 'dpec-' + sha256(url.encode('utf-8')).hexdigest()[:18],
            'country': 'Argentina', 'province': 'Corrientes', 'company': 'DPEC',
            'kind': 'dated_official_planned_work_bulletin',
            'status': 'publication_only_not_current_outage',
            'title': cleaned, 'scheduled_last_day': when.isoformat(),
            'source_url': url,
            'message': 'Comunicado oficial fechado; confirmar detalles en la fuente. No acredita un corte en curso.',
        }
    return sorted(notices.values(), key=lambda x: (x['scheduled_last_day'], x['title'])), checked, candidate_links


def fetch_dpec_html(url=SOURCE_URL):
    if url != SOURCE_URL:
        raise ValueError('Only official DPEC archive URL is allowed')
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (dated public electricity bulletins)',
        'Accept': 'text/html,application/xhtml+xml', 'Accept-Language': 'es-AR,es;q=0.9',
    })
    with urlopen(req, timeout=18) as response:
        if (urlsplit(response.geturl()).hostname or '').lower() not in ('www.dpec.com.ar', 'dpec.com.ar'):
            raise ValueError('DPEC redirected outside its official domain')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('DPEC archive too large')
    return data.decode('utf-8-sig', errors='replace')


def collect_dpec(checked_at, fetcher=None):
    output = {
        'status': 'unverified', 'country': 'Argentina', 'province': 'Corrientes',
        'company': 'DPEC', 'source_url': SOURCE_URL, 'checked_at': checked_at,
        'coverage_kind': 'dated_planned_work_bulletins_only', 'notices': [],
        'message': 'No se verificaron publicaciones; NO significa servicio normal.',
    }
    try:
        html = (fetcher or fetch_dpec_html)(SOURCE_URL)
        items, checked, candidates = extract_dpec_bulletins(html, checked_at)
    except Exception as exc:
        output['message'] = 'Consulta sin verificar: ' + type(exc).__name__
        return output
    output['records_checked'] = checked
    output['article_links_seen'] = candidates
    output['notices'] = items
    if items:
        output['status'] = 'ok'
        output['message'] = 'Comunicados oficiales de cortes previstos; no representan cortes activos ni generan notificaciones.'
    elif checked:
        output['status'] = 'stale'
        output['message'] = 'Se reconocieron publicaciones fechadas, pero ninguna futura. NO confirma servicio normal.'
    else:
        output['message'] = 'La pagina consultada no proporciono comunicados completos con enlace, fecha y horario.'
    return output

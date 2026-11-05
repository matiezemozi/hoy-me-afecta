"""Conservative monitoring of ENERSA's official dated WordPress bulletins.

No real-time outage data is inferred. Only publications whose headline describes
scheduled electricity work and whose text supplies a complete, still-relevant
calendar date can become bulletin notices. Nothing goes into live alerts/push.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

TAG_RSS = 'https://www.enersa.com.ar/tag/cortes/feed/'
GENERAL_RSS = 'https://www.enersa.com.ar/feed/'
SOURCE_URL = 'https://www.enersa.com.ar/tag/cortes/'
ART = timezone(timedelta(hours=-3))
MAX_BYTES = 700_000
MAX_ITEMS = 60
MAX_AGE_DAYS = 30
MAX_FUTURE_DAYS = 21
_ALLOWED_HOSTS = ('www.enersa.com.ar', 'enersa.com.ar')
_DATES = re.compile(r'(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(20\d\d)(?!\d)')
_MONTHS = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5,
    'junio': 6, 'julio': 7, 'agosto': 8, 'septiembre': 9,
    'setiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
}
_WORD_DATE = re.compile(r'\b(\d{1,2})\s+de\s+(' + '|'.join(_MONTHS) + r')\s+de\s+(20\d\d)\b')
_STOP = ('suspendid', 'cancelad', 'anulad', 'reprogramad', 'postergad',
         'se realizo', 'realizo trabajos', 'finalizo', 'termino')
_CONTEXT = ('corte programado', 'cortes programados', 'interrupcion programada',
            'interrupciones programadas', 'trabajos programados con corte',
            'suspension programada del suministro')


def _normal(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text or '').lower())
                   if not unicodedata.combining(c))


def _clean(text, maximum=400):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(text or ''))).strip()[:maximum]


def _official_article(url):
    if not isinstance(url, str) or not url.strip() or len(url) > 700:
        return None
    parts = urlsplit(url.strip())
    if (parts.scheme != 'https' or parts.username or parts.password or parts.port or
            parts.query or parts.fragment or
            (parts.hostname or '').lower() not in _ALLOWED_HOSTS):
        return None
    # A real post permalink, not home, feed, query, admin, or a directory.
    path = parts.path
    if not re.fullmatch(r'/[a-z0-9][a-z0-9-]{9,180}/?', path, flags=re.I):
        return None
    if path.strip('/').lower() in ('feed', 'category', 'tag', 'noticias', 'contacto'):
        return None
    return url.strip()


def _date_in_text(text):
    values = []
    normalized = _normal(text)
    for m in _DATES.finditer(normalized):
        day, month, year = map(int, m.groups())
        try:
            values.append(date(year, month, day))
        except ValueError:
            pass
    for m in _WORD_DATE.finditer(normalized):
        try:
            values.append(date(int(m[3]), _MONTHS[m[2]], int(m[1])))
        except ValueError:
            pass
    return max(values) if values else None


def _pub_date(item):
    pub = item.findtext('pubDate')
    if not pub:
        return None
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            return None
        return dt.astimezone(ART).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def extract_enersa_rss(xml, checked_at):
    """Return upcoming official bulletins, relevant dated entries, RSS item count."""
    if not isinstance(xml, str) or not xml.strip() or len(xml.encode('utf-8')) > MAX_BYTES:
        raise ValueError('RSS vacio o demasiado grande')
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ValueError('No se admiten definiciones externas XML')
    now = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    if now.tzinfo is None:
        raise ValueError('Fecha de comprobacion sin zona horaria')
    today = now.astimezone(ART).date()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError('XML RSS malformado') from exc
    if root.tag != 'rss':
        raise ValueError('La respuesta no es un RSS de WordPress')
    items = root.findall('./channel/item')[:MAX_ITEMS]
    notices = {}
    eligible = 0
    for item in items:
        title = _clean(item.findtext('title'), 250)
        link = _official_article(item.findtext('link'))
        published = _pub_date(item)
        ntitle = _normal(title)
        if not (link and published and title and any(term in ntitle for term in _CONTEXT)):
            continue
        if any(word in ntitle for word in _STOP):
            continue
        # Reject pages with stale or future-dated publication timestamps.
        if not (today - timedelta(days=MAX_AGE_DAYS) <= published <= today):
            continue
        description = _clean(item.findtext('description'), 650)
        # Explicit complete date required, never fill missing year with current year.
        scheduled = _date_in_text(title + ' ' + description)
        if scheduled is None:
            continue
        eligible += 1
        if not (today <= scheduled <= today + timedelta(days=MAX_FUTURE_DAYS)):
            continue
        notices[link] = {
            'id': 'enersa-' + sha256(link.encode('utf-8')).hexdigest()[:18],
            'country': 'Argentina', 'province': 'Entre Rios', 'company': 'ENERSA',
            'kind': 'dated_official_planned_work_bulletin',
            'status': 'publication_only_not_current_outage',
            'title': title, 'published_on': published.isoformat(),
            'scheduled_last_day': scheduled.isoformat(), 'source_url': link,
            'message': 'Comunicado oficial fechado. Consultar zonas y horario en la fuente; no confirma corte actual.',
        }
    return sorted(notices.values(), key=lambda n: (n['scheduled_last_day'], n['title'])), eligible, len(items)


def fetch_enersa_rss(url):
    if url not in (TAG_RSS, GENERAL_RSS):
        raise ValueError('Solo se permiten los feeds publicos oficiales de ENERSA')
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (official published bulletin monitor)',
        'Accept': 'application/rss+xml,application/xml,text/xml',
        'Accept-Language': 'es-AR,es;q=0.9',
    })
    with urlopen(req, timeout=17) as response:
        actual = urlsplit(response.geturl())
        if actual.scheme != 'https' or (actual.hostname or '').lower() not in _ALLOWED_HOSTS:
            raise ValueError('ENERSA redirigio a un dominio no autorizado')
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Respuesta RSS demasiado grande')
    return data.decode('utf-8-sig', errors='replace')


def collect_enersa(checked_at, fetcher=None):
    result = {
        'status': 'unverified', 'country': 'Argentina', 'province': 'Entre Rios',
        'company': 'ENERSA', 'source_url': SOURCE_URL, 'checked_at': checked_at,
        'coverage_kind': 'dated_planned_work_bulletins_only', 'notices': [],
        'message': 'Sin comunicados futuros verificables. No significa servicio normal.',
        'source_attempts': [],
    }
    fetch = fetcher or fetch_enersa_rss
    checked_total = 0
    for url in (TAG_RSS, GENERAL_RSS):
        attempt = {'url': url}
        try:
            xml = fetch(url)
            notices, checked, rss_items = extract_enersa_rss(xml, checked_at)
            attempt.update({'result': 'parsed', 'rss_items_seen': rss_items,
                            'dated_relevant_articles': checked,
                            'upcoming_count': len(notices)})
            checked_total += checked
            if notices:
                result['status'] = 'ok'
                result['notices'] = notices
                result['source_used'] = url
                result['message'] = ('Comunicados oficiales de cortes programados; '
                                     'NO son cortes en curso ni notificaciones automaticas.')
                result['source_attempts'].append(attempt)
                break
        except Exception as exc:
            attempt.update({'result': 'fetch_or_parse_error', 'error_type': type(exc).__name__})
        result['source_attempts'].append(attempt)
    result['records_checked'] = checked_total
    if result['status'] != 'ok' and checked_total:
        result['status'] = 'stale'
        result['message'] = 'Comunicados fechados reconocidos, ninguno futuro; no confirma suministro normal.'
    return result

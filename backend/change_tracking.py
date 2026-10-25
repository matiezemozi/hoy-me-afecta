"""Conservative comparison of successive ENRE snapshots.

'New' means first appearing in our consecutive published snapshots, NOT a newly
started outage. Never treat disappearance from a feed as confirmed restoration.
The result is intended for a future opt-in notification system, not for push.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import unicodedata

MAX_BASELINE_AGE = timedelta(hours=6)
ARG_TIMEZONE = ZoneInfo('America/Argentina/Buenos_Aires')
MAX_DETAILS = 50


def _utc(value):
    if not isinstance(value, str):
        raise ValueError('Missing date')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp without time zone')
    return parsed.astimezone(timezone.utc)


def _normalized(value):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', str(value or '').casefold())
                   if not unicodedata.combining(ch)).strip()


def _key(alert):
    """Stable across changes in users affected or predicted restoration time.

    It groups co-located incidents conservatively when the source lacks its own
    incident identifier; such groups are *not* proof that each outage is unique.
    """
    if alert.get('category') != 'electricidad':
        return None
    return tuple(_normalized(alert.get(k)) for k in
                 ('company', 'partido', 'localidad', 'title', 'zone_detail'))


def _events(feed, provider):
    return [a for a in feed.get('alerts', []) if
            a.get('category') == 'electricidad' and
            _normalized(a.get('company')) == _normalized(provider)]


def _late_restoration(alert, now):
    original = alert.get('expected_restoration')
    if not isinstance(original, str) or not original.strip():
        return False
    try:
        try:
            when = datetime.strptime(original.strip(), '%Y-%m-%d %H:%M')
            when = when.replace(tzinfo=ARG_TIMEZONE)
        except ValueError:
            when = datetime.fromisoformat(original.replace('Z', '+00:00'))
            if when.tzinfo is None:
                return False
        return when.astimezone(timezone.utc) < now
    except ValueError:
        return False


def compare_feeds(previous, current):
    """Return metadata to support future notifications, with strict caveats."""
    output = {
        'status': 'no_recent_baseline',
        'meaning': ('Las novedades indican cambios respecto del informe anterior; '
                    'no prueban cuándo comenzó un corte ni que uno ausente esté resuelto.'),
        'compared_to': None,
        'new_in_publication_count': 0,
        'new_in_publication': [],
        'no_longer_listed_count': 0,
        'providers_compared': [],
        'providers_skipped': [],
        'past_estimated_restoration_count': 0,
        'past_estimated_restoration': [],
    }
    try:
        now = _utc(current['generated_at'])
    except (KeyError, TypeError, ValueError):
        output['status'] = 'invalid_current_timestamp'
        return output
    for alert in current.get('alerts', []):
        if _key(alert) and _late_restoration(alert, now):
            output['past_estimated_restoration_count'] += 1
            if len(output['past_estimated_restoration']) < MAX_DETAILS:
                output['past_estimated_restoration'].append({
                    'id': alert.get('id'), 'company': alert.get('company'),
                    'partido': alert.get('partido'), 'localidad': alert.get('localidad'),
                    'expected_restoration': alert.get('expected_restoration'),
                    'message': 'La hora estimada ya pasó; la fuente aún publica el aviso.',
                })
    if not isinstance(previous, dict):
        return output
    try:
        older = _utc(previous['generated_at'])
    except (KeyError, TypeError, ValueError):
        return output
    if not timedelta(0) <= now - older <= MAX_BASELINE_AGE:
        return output
    output['compared_to'] = previous['generated_at']
    for provider in ('edenor', 'edesur'):
        current_source = current.get('sources', {}).get(provider, {})
        previous_source = previous.get('sources', {}).get(provider, {})
        if current_source.get('status') != 'ok' or previous_source.get('status') != 'ok':
            output['providers_skipped'].append(provider)
            continue
        output['providers_compared'].append(provider)
        old_counts = Counter(_key(a) for a in _events(previous, provider))
        new_counts = Counter(_key(a) for a in _events(current, provider))
        fresh_count = new_counts - old_counts
        absent_count = old_counts - new_counts
        output['no_longer_listed_count'] += sum(absent_count.values())
        for alert in _events(current, provider):
            key = _key(alert)
            if fresh_count[key] > 0:
                fresh_count[key] -= 1
                output['new_in_publication_count'] += 1
                if len(output['new_in_publication']) < MAX_DETAILS:
                    output['new_in_publication'].append({
                        'id': alert.get('id'), 'company': alert.get('company'),
                        'title': alert.get('title'), 'partido': alert.get('partido'),
                        'localidad': alert.get('localidad'),
                        'observed_at': current['generated_at'],
                        'source_url': alert.get('source_url'),
                        'meaning': 'No figuraba en el informe anterior; inicio real desconocido.',
                    })
    if output['providers_compared']:
        output['status'] = 'ok' if not output['providers_skipped'] else 'partial'
    else:
        output['status'] = 'sources_unavailable'
    return output

"""Short-lived publication-change journal for opt-in Android notifications.

A journal entry means a NEW RECORD IN OUR COMPARISON OF ENRE PUBLICATIONS.
It never proves that an outage started at that moment. The journal lets a
periodically scheduled phone check see changes between its own checks.
"""
from datetime import timedelta
import hashlib
import json
from change_tracking import _normalized, _utc

RETENTION = timedelta(hours=3)
MAX_ITEMS = 160


def event_key(item):
    # Do not include changing restoration time, counts, or the ENRE snapshot id.
    parts = [_normalized(item.get(k)) for k in
             ('company', 'partido', 'localidad', 'title')]
    if not all(parts):
        return None
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()[:24]


def journal(previous, current):
    output = {
        'status': 'ready',
        'retention_hours': 3,
        'meaning': 'Apareció en una publicación nueva; no prueba inicio del corte.',
        'events': [],
    }
    try:
        now = _utc(current['generated_at'])
    except (KeyError, ValueError, TypeError):
        output['status'] = 'invalid_timestamp'
        return output

    seen = set()
    old_journal = previous.get('notification_events', {}) if isinstance(previous, dict) else {}
    for event in old_journal.get('events', []) if isinstance(old_journal, dict) else []:
        if not isinstance(event, dict) or event.get('kind') != 'electricity_publication_added':
            continue
        try:
            age = now - _utc(event.get('first_seen_at'))
        except (ValueError, TypeError):
            continue
        key = event_key(event)
        if key and timedelta(0) <= age < RETENTION and key not in seen:
            # Never blindly copy an event with an unknown provider.
            if _normalized(event.get('company')) in ('edenor', 'edesur'):
                seen.add(key)
                output['events'].append(event)

    changes = current.get('change_tracking', {})
    if changes.get('status') in ('ok', 'partial'):
        for item in changes.get('new_in_publication', []):
            if not isinstance(item, dict) or _normalized(item.get('company')) not in ('edenor', 'edesur'):
                continue
            key = event_key(item)
            if not key or key in seen:
                continue
            # Verified by the ENRE source, but no exact start time is known.
            provider = _normalized(item['company'])
            if current.get('sources', {}).get(provider, {}).get('status') != 'ok':
                continue
            seen.add(key)
            output['events'].append({
                'event_id': key,
                'kind': 'electricity_publication_added',
                'country': 'Argentina',
                'company': item['company'],
                'title': item['title'],
                'partido': item['partido'],
                'localidad': item['localidad'],
                'first_seen_at': current['generated_at'],
                'source_url': item.get('source_url', ''),
            })
    # Keep a bounded rolling journal, newer entries first, no duplicates.
    output['events'].sort(key=lambda item: item.get('first_seen_at', ''), reverse=True)
    output['events'] = output['events'][:MAX_ITEMS]
    return output

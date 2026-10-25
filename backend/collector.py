"""Collect ENRE electricity outages and optional documented bus notices.

Important: data_EDN.js/data_EDS.js are *undocumented* sources. Their schema and
availability can change; the program records errors instead of guessing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import Request, urlopen

import json5

from bank_calendar import banking_calendar
from public_notices import import_public_notices
from subte_status import collect_subte

BASE = 'https://www.enre.gov.ar/paginacorte/js/'
FEEDS = {'edenor': BASE + 'data_EDN.js', 'edesur': BASE + 'data_EDS.js'}
MAX_BYTES = 4_000_000


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def unpack_js(js):
    """Reject executable JS; only accept a single assignment to data."""
    text = js.lstrip('\ufeff').strip()
    match = re.match(r'^(?:var|let|const)\s+data\s*=\s*', text)
    if not match:
        raise ValueError('Se esperaba una asignación var data = …')
    payload = text[match.end():].strip().rstrip(';').strip()
    parsed = json5.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError('El contenido del ENRE no es un objeto')
    return parsed


def fetch_js(url):
    request = Request(url, headers={'User-Agent': 'HoyMeAfecta/0.1 (pilot; source citation)'})
    with urlopen(request, timeout=18) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Fuente demasiado grande')
    return unpack_js(raw.decode('utf-8-sig', errors='replace'))


def normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower())
                   if not unicodedata.combining(c))


def label_for(path):
    p = normal(path)
    if 'programad' in p: return 'Corte programado'
    if 'preventiv' in p: return 'Corte preventivo'
    if 'baja' in p: return 'Interrupción de baja tensión'
    if 'media' in p: return 'Interrupción de media tensión'
    return 'Corte informado'


def incident_lists(document):
    """Discover incident arrays conservatively, tolerating minor key variations."""
    def walk(value, trail=()):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from walk(item, trail + (str(key),))
        elif isinstance(value, list):
            path = ' '.join(trail)
            if any(word in normal(path) for word in ('cortes', 'interrup', 'preventiv')):
                yield path, value
            # Nested arrays can be present; only inspect nested dictionaries.
            for item in value:
                if isinstance(item, dict):
                    yield from walk(item, trail)
    return list(walk(document))


def parse_enre(document, company, fetched_at):
    lists = incident_lists(document)
    if not lists:
        raise ValueError('No se reconocieron listas de cortes; revisar formato ENRE')
    seen = set()
    alerts = []
    for path, items in lists:
        for item in items:
            if not isinstance(item, dict):
                continue
            lower = {normal(k): v for k, v in item.items()}
            partido = lower.get('partido', '')
            localidad = lower.get('localidad') or lower.get('barrio', '')
            if not partido and not localidad:
                continue
            title = label_for(path)
            normalizacion = lower.get('normalizacion') or lower.get('horaestimadadenormalizacion') or ''
            users = lower.get('usuarios') or lower.get('usuariosafectados') or ''
            zone = lower.get('calles') or ''
            if isinstance(zone, (list, dict)):
                zone = json.dumps(zone, ensure_ascii=False)
            entry = {
                'category': 'electricidad',
                'title': title,
                'company': company.title(),
                'partido': str(partido).strip(),
                'localidad': str(localidad).strip(),
                'users_affected': str(users).strip() if users != '' else None,
                'expected_restoration': str(normalizacion).strip() if normalizacion else None,
                'zone_detail': str(zone).strip() if zone else None,
                'source_url': f'https://www.enre.gov.ar/paginacorte/tabla_cortes_{company}.html',
                'observed_at': fetched_at,
                'confirmation': 'Publicado por ENRE',
            }
            compact = json.dumps([company, title, partido, localidad, normalizacion, users, zone],
                                 ensure_ascii=False, sort_keys=True)
            entry['id'] = hashlib.sha256(compact.encode('utf-8')).hexdigest()[:16]
            if entry['id'] not in seen:
                seen.add(entry['id'])
                alerts.append(entry)
    return alerts


def checked_datetime(value):
    if not isinstance(value, str):
        raise ValueError('Fecha inexistente')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Se requiere zona horaria')
    return date.astimezone(timezone.utc)


def load_bus_alerts(path, generated_at):
    if not path.exists():
        return []
    notices = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(notices, list):
        raise ValueError('El archivo manual de colectivos debe ser una lista')
    output = []
    current = checked_datetime(generated_at)
    for item in notices:
        try:
            line = str(item['line']).strip()
            if not re.fullmatch(r'[0-9A-Za-z-]{1,12}', line):
                continue
            if item.get('country', 'Argentina') != 'Argentina':
                continue
            date = checked_datetime(item['verified_at'])
            end = checked_datetime(item['ends_at'])
            source = item['source_url']
            if not isinstance(source, str) or not source.startswith('https://'):
                continue
            if not (date <= current and (current - date).total_seconds() <= 86400 and end > current):
                continue
            if not item.get('title') or not item.get('description'):
                continue
            entry = {
                'id': 'bus-' + hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()[:14],
                'category': 'colectivo', 'country': 'Argentina', 'line': line,
                'branch': str(item.get('branch','')).strip(),
                'title': str(item['title']), 'description': str(item['description']),
                'observed_at': item['verified_at'], 'valid_until': item['ends_at'],
                'source_url': source, 'confirmation': 'Aviso documental cargado manualmente; verificar en la fuente',
            }
            output.append(entry)
        except (KeyError, ValueError, TypeError):
            continue
    return output


def collect(dest, manual, public_manual=None, *, fetch_subte=None):
    timestamp = now_utc()
    output = {
        'schema_version': 1, 'generated_at': timestamp, 'alerts': [],
        'sources': {},
        'banking': banking_calendar(),
        'coverage': {
            'trains': 'manual_notices_only', 'bank_holidays': 'published_reference_2026',
            'bank_incidents': 'manual_notices_only', 'water': 'manual_notices_only',
            'traffic': 'manual_notices_only', 'public_operations': 'manual_public_impacts_only',
        },
        'transport': {'57': {
            'status': 'not_connected',
            'message': 'No hay conexión verificada con una fuente automática de estado de la línea 57.',
            'reference_url': 'https://www.argentina.gob.ar/sube/cuandosubo',
            'checked_at': timestamp,
        }},
    }
    # Existing tests do not perform network calls to the experimental subte source.
    # The CLI explicitly passes a fetcher; failures never become 'normal'.
    try:
        output['subte'] = (fetch_subte(timestamp) if fetch_subte is not None else {
            'status': 'not_checked', 'lines': [], 'checked_at': timestamp})
    except Exception as exc:
        output['subte'] = {'status': 'error', 'lines': [], 'checked_at': timestamp,
                           'message': f'{type(exc).__name__}: {str(exc)[:170]}'}
    for company, url in FEEDS.items():
        try:
            doc = fetch_js(url)
            items = parse_enre(doc, company, timestamp)
            output['alerts'].extend(items)
            output['sources'][company] = {'status': 'ok', 'url': url,
                                          'checked_at': timestamp, 'event_count': len(items)}
        except Exception as exc:
            output['sources'][company] = {'status': 'error', 'url': url,
                                          'checked_at': timestamp,
                                          'message': f'{type(exc).__name__}: {str(exc)[:180]}'}
    try:
        manual_alerts = load_bus_alerts(manual, timestamp)
        output['alerts'].extend(manual_alerts)
        for notice in manual_alerts:
            line = notice['line']
            if line not in output['transport']:
                output['transport'][line] = {
                    'status': 'not_connected',
                    'message': 'Sin conexión automática verificada con este operador.',
                    'checked_at': timestamp,
                }
            output['transport'][line]['documented_notices'] = (
                output['transport'][line].get('documented_notices', 0) + 1
            )
            # 'documented_notices' does not imply live vehicle data.
    except (ValueError, OSError) as exc:
        output['transport']['57']['manual_error'] = str(exc)[:150]
    try:
        notices = import_public_notices(
            public_manual or Path('manual/avisos_publicos.json'), timestamp)
        output['alerts'].extend(notices)
        output['public_notice_count'] = len(notices)
    except (ValueError, OSError) as exc:
        output['public_notice_error'] = str(exc)[:180]
        output['public_notice_count'] = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Feed written to {dest}: {len(output["alerts"])} alerts')
    for company, source in output['sources'].items():
        print(f'{company}: {source["status"]}, {source.get("event_count", source.get("message"))}')
    status = output['subte']
    print(f'subte CABA: {status["status"]}; {status.get("message", status.get("event_count", 0))}')
    # Workflow remains successful when a provider is down so that the last
    # attempt is visible. No failure is converted to "no incidents".


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='docs/feed.json')
    parser.add_argument('--manual', default='manual/linea57_alertas.json')
    parser.add_argument('--public-manual', default='manual/avisos_publicos.json')
    args = parser.parse_args()
    collect(Path(args.output), Path(args.manual), Path(args.public_manual),
            fetch_subte=collect_subte)

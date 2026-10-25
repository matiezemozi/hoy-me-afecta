"""Conservative importer of dated, source-backed public-service impacts.

Items are added by a human reviewer after checking an official public notice.
This does NOT scrape, infer, or expose locations of police/checkpoints/patrols.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

CATEGORIES = {'tren', 'agua', 'transito', 'banco', 'operativo_publico'}
PUBLIC_IMPACTS = {'corte_de_calle', 'desvio', 'acceso_restringido', 'evento_publico'}
OFFICIAL_BANK_DOMAINS = {'bna.com.ar', 'www.bna.com.ar',
                         'bancoprovincia.com.ar', 'www.bancoprovincia.com.ar'}


def aware(iso):
    value = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Fecha sin zona horaria')
    return value.astimezone(timezone.utc)


def allowed_public_source(url, category=None):
    """For these manually-verified events require a public official .gob.ar URL."""
    if not isinstance(url, str) or len(url) > 2000:
        return False
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and ((category == 'banco' and host in OFFICIAL_BANK_DOMAINS) or
            host == 'argentina.gob.ar' or
           host.endswith('.argentina.gob.ar') or host == 'buenosaires.gob.ar' or
           host.endswith('.buenosaires.gob.ar') or host.endswith('.gob.ar'))


def import_public_notices(path: Path, generated_at: str):
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(items, list):
        raise ValueError('manual/avisos_publicos.json debe ser una lista')
    if len(items) > 300:
        raise ValueError('Demasiados avisos manuales')
    now = aware(generated_at)
    output = []
    for item in items:
        try:
            if not isinstance(item, dict) or item.get('country') != 'Argentina':
                continue
            cat = item['category']
            if cat not in CATEGORIES:
                continue
            if cat == 'operativo_publico' and item.get('impact_type') not in PUBLIC_IMPACTS:
                continue
            source = item['source_url']
            if not allowed_public_source(source, cat):
                continue
            verified = aware(item['verified_at'])
            end = aware(item['ends_at'])
            start = aware(item.get('starts_at', item['verified_at']))
            if not (now-timedelta(hours=24) <= verified <= now+timedelta(minutes=1)):
                continue
            if not (start <= end and now < end and start <= now + timedelta(days=7)):
                continue
            title = str(item['title']).strip()[:140]
            description = str(item['description']).strip()[:600]
            locality = str(item.get('localidad', '')).strip()[:100]
            partido = str(item.get('partido', '')).strip()[:100]
            if not title or not description or not (locality or partido):
                continue  # avoid unsafely broadcasting an unspecific local notice
            if cat == 'tren' and not str(item.get('line', '')).strip():
                continue
            normalized = {
                'category': cat, 'country': 'Argentina', 'title': title,
                'description': description, 'partido': partido, 'localidad': locality,
                'line': str(item.get('line', '')).strip()[:60],
                'bank': str(item.get('bank', '')).strip()[:90],
                'observed_at': item['verified_at'], 'starts_at': item.get('starts_at', item['verified_at']),
                'valid_until': item['ends_at'], 'source_url': source,
                'confirmation': 'Aviso público verificado manualmente; consultar fuente original',
            }
            if cat == 'operativo_publico':
                normalized['impact_type'] = item['impact_type']
                # We publish ONLY the public impact, not tactical detail or checkpoint positions.
            normalized['id'] = 'public-' + hashlib.sha256(
                json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode('utf-8')
            ).hexdigest()[:16]
            output.append(normalized)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return output

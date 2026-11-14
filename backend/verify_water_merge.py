"""Pre-commit validation of the read-only water pilot integration."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

class WaterMergeError(ValueError):
    """An incomplete/unsafe water-to-electricity merge."""

def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def verify(before, after, water):
    if not all(isinstance(v, dict) for v in (before, after, water)):
        raise WaterMergeError('Los informes deben ser objetos JSON')
    if before.get('schema_version') != 1 or after.get('schema_version') != 1:
        raise WaterMergeError('Esquema electrico inesperado')
    if not isinstance(before.get('alerts'), list) or not isinstance(after.get('alerts'), list):
        raise WaterMergeError('Falta lista de alertas electricas')
    if after.get('water_services') != water:
        raise WaterMergeError('water_services difiere de water_feed.json')
    old = dict(before); old.pop('water_services', None)
    new = dict(after); new.pop('water_services', None)
    if old != new:
        raise WaterMergeError('La union altero datos ajenos a water_services')
    if water.get('schema_version') != 1 or water.get('category') != 'agua' or water.get('country') != 'Argentina':
        raise WaterMergeError('Esquema de agua inesperado')
    if not isinstance(water.get('generated_at'), str) or not water['generated_at']:
        raise WaterMergeError('Falta marca de tiempo del agua')
    if water.get('notifications_enabled') is not False or water.get('android_display_enabled') is not False:
        raise WaterMergeError('Piloto de agua: notificaciones y Android deben permanecer desactivados')
    sources, notices = water.get('sources'), water.get('notices')
    if not isinstance(sources, dict) or not sources or not isinstance(notices, list):
        raise WaterMergeError('Lista de fuentes o avisos de agua invalida')
    per_source_ids = set()
    for key, src in sources.items():
        if not key or not isinstance(src, dict):
            raise WaterMergeError('Fuente mal identificada')
        if src.get('status') not in ('ok', 'stale', 'unverified'):
            raise WaterMergeError('Estado de fuente no reconocido: ' + key)
        if src.get('notifications_enabled') is not False:
            raise WaterMergeError('Notificaciones habilitadas en fuente: ' + key)
        entries = src.get('notices')
        if not isinstance(entries, list):
            raise WaterMergeError('Lista de fuente invalida: ' + key)
        for item in entries:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                raise WaterMergeError('Aviso de fuente mal formado: ' + key)
            per_source_ids.add(item['id'])
    ids = set()
    for n in notices:
        if not isinstance(n, dict) or not isinstance(n.get('id'), str) or not n['id'].startswith('agua-') or n['id'] in ids:
            raise WaterMergeError('ID de aviso duplicado o invalido')
        ids.add(n['id'])
        if n.get('notification_allowed') is not False:
            raise WaterMergeError('Aviso marcado para notificacion')
        if n.get('category') != 'agua' or n.get('country') != 'Argentina':
            raise WaterMergeError('Aviso fuera de la categoria o pais')
        if not n.get('locality_hint') or not n.get('published_on'):
            raise WaterMergeError('Aviso sin localidad o fecha de publicacion')
        parsed = urlsplit(str(n.get('source_url') or ''))
        if parsed.scheme != 'https' or not parsed.hostname:
            raise WaterMergeError('Aviso sin URL oficial HTTPS')
    if ids != per_source_ids:
        raise WaterMergeError('Avisos agregados no coinciden con avisos de las fuentes')
    return {'electric_alerts_unchanged': len(before['alerts']), 'water_sources': len(sources),
            'water_notices': len(notices), 'water_checked_at': water['generated_at'],
            'electric_checked_at': after.get('generated_at')}

def main(argv=None):
    parser = argparse.ArgumentParser(description='Valida agua integrada sin modificar electricidad')
    parser.add_argument('--before', required=True)
    parser.add_argument('--feed', required=True)
    parser.add_argument('--water', required=True)
    args = parser.parse_args(argv)
    summary = verify(_load(args.before), _load(args.feed), _load(args.water))
    print('MERGE DE AGUA VALIDADO (notificaciones desactivadas)')
    for key, val in summary.items():
        print(f'{key}: {val}')
    return summary

if __name__ == '__main__':
    main()

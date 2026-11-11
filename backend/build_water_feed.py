"""Build independent water_feed.json and optionally merge diagnostics in feed.json.

Existing feed keys, alerts, and Android capabilities are never modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import tempfile
from water_notices import collect_water


def atomic_json(path,data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                     prefix='.water-',suffix='.json',delete=False) as out:
        tmp=out.name
        json.dump(data,out,ensure_ascii=False,indent=2)
        out.write('\n')
    os.replace(tmp,path)


def main(args=None,collector=collect_water):
    parser=argparse.ArgumentParser(description='Pilot water notices, no push notifications')
    parser.add_argument('--out',default='docs/water_feed.json')
    parser.add_argument('--merge',default=None,help='Existing docs/feed.json; preserve all prior fields')
    parsed=parser.parse_args(args)
    now=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    result=collector(now)
    if not isinstance(result,dict) or result.get('category')!='agua':
        raise ValueError('Salida inesperada del recolector de agua')
    if parsed.merge:
        existing=Path(parsed.merge)
        if not existing.is_file():
            raise FileNotFoundError(f'El feed base no existe: {existing}')
        data=json.loads(existing.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('alerts'),list):
            raise ValueError('Esquema de feed.json inesperado; no se sobrescribe')
        data['water_services']=result
        # Do not touch the original generated_at, alerts, provincial_electricity,
        # or coverage.water: v5.23 Android does not support water notices yet.
        atomic_json(parsed.out,result)
        atomic_json(existing,data)
    else:
        atomic_json(parsed.out,result)
    return result


if __name__=='__main__':
    result=main()
    print('water_sources:',{key:v['status'] for key,v in result['sources'].items()})
    print('water_notices:',len(result['notices']),'notifications_enabled:',result['notifications_enabled'])

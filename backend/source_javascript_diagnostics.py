"""Bounded, read-only inspection of publicly served provider JavaScript bundles.

Never execute JS, call an inferred endpoint, retain source code, or include
query strings, tokens, cookies or response bodies in generated diagnostics.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

MAX_JS_BYTES = 6_000_000


def _trusted_script_url(page: str, script_path: str, provider: str) -> str | None:
    """Only one preidentified official application bundle per provider."""
    url = urljoin(page, script_path)
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    if provider == 'epec_cordoba':
        return url if (parsed.hostname in ('epec.com.ar', 'www.epec.com.ar')
                       and re.fullmatch(r'/actualidad/main\.[a-zA-Z0-9]+\.js', parsed.path)) else None
    if provider == 'epe_santa_fe':
        return url if (parsed.hostname == 'www.epe.santafe.gov.ar'
                       and re.fullmatch(r'/institucional/_astro/TrabajosProgramados\.[a-zA-Z0-9_.-]+\.js', parsed.path)) else None
    return None


def fetch_public_script(url: str) -> str:
    """Read a public asset with strict timeout and byte limit, no cookies/auth."""
    req = Request(url, headers={'User-Agent':'HoyMeAfecta/0.5 (source diagnostics)',
                                'Accept':'application/javascript,text/javascript,*/*'})
    with urlopen(req, timeout=12) as response:
        # Do not silently fetch an unrelated redirected host.
        final = urlsplit(response.geturl())
        initial = urlsplit(url)
        if final.scheme != 'https' or final.hostname != initial.hostname:
            raise ValueError('External redirect rejected')
        content_type = (response.headers.get('Content-Type', '') or '').lower()
        if 'text/html' in content_type:
            raise ValueError('Expected JavaScript but server returned HTML')
        payload = response.read(MAX_JS_BYTES + 1)
    if len(payload) > MAX_JS_BYTES:
        raise ValueError('JavaScript asset exceeds maximum size')
    return payload.decode('utf-8-sig', errors='replace')


def _safely_extract_hints(js: str, provider: str) -> dict:
    """Summarize possible PUBLIC request paths; no source text or query params."""
    if not isinstance(js, str) or len(js.encode('utf-8')) > MAX_JS_BYTES:
        raise ValueError('Script invalid or too large')
    content = js.replace('\\/', '/')
    keywords = ('corte', 'trabajo', 'program', 'interrup', 'servicio', 'api', 'mantenim')
    # A path can be an API route even if it does not include a keyword.
    absolute = re.findall(r'https?://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~/%-]{1,160})?', content)
    public_hosts = []
    candidate_paths = []
    for raw in absolute:
        parsed = urlsplit(raw)
        host = (parsed.hostname or '').lower()
        allowed = (host.endswith('.epec.com.ar') or host == 'epec.com.ar') if provider == 'epec_cordoba' else (
            host.endswith('.santafe.gov.ar') or host == 'santafe.gov.ar')
        if not allowed:
            continue
        if host not in public_hosts:
            public_hosts.append(host)
        if parsed.path and any(x in parsed.path.lower() for x in keywords):
            path = parsed.path[:160]
            if path not in candidate_paths:
                candidate_paths.append(path)
    # Quoted relative routes e.g. '/api/cortes', 'api/trabajos-programados'.
    for match in re.finditer(r'''["'`]((?:/|api/)[A-Za-z0-9_./:~-]{3,160})["'`]''', content):
        path = match.group(1)
        if not any(x in path.lower() for x in keywords):
            continue
        if any(x in path.lower() for x in ('token', 'secret', 'key=', 'auth', 'password', '..')):
            continue
        if path not in candidate_paths:
            candidate_paths.append(path)
    lower = content.lower()
    return {
        'asset_bytes': len(js.encode('utf-8')),
        'javascript_requests_found': {
            'fetch': len(re.findall(r'\bfetch\s*\(', lower)),
            'axios': lower.count('axios'),
            'httpclient': lower.count('httpclient'),
        },
        'keyword_counts': {word: min(lower.count(word), 999) for word in ('corte', 'trabajo', 'api')},
        'official_hosts_seen': public_hosts[:8],
        'candidate_public_paths': candidate_paths[:15],
        'note': 'Solo pistas del código público; NO son API verificadas ni se consultaron sus rutas.',
    }


def probe_official_scripts(page: str, provider: str, script_paths: list[str], fetcher=None) -> list[dict]:
    """Inspect at most one matching script per source, never arbitrary script URLs."""
    if provider not in ('epec_cordoba', 'epe_santa_fe'):
        return []
    read = fetcher or fetch_public_script
    selected = None
    for relative in script_paths[:12]:
        candidate = _trusted_script_url(page, relative, provider)
        if candidate:
            selected = candidate
            break
    if not selected:
        return [{'status':'no_target_bundle_found',
                 'note':'No se identificó el paquete oficial esperado.'}]
    result = {'script_path':urlsplit(selected).path, 'status':'unverified'}
    try:
        raw = read(selected)
        result.update(_safely_extract_hints(raw, provider))
        result['status'] = 'scanned'
    except Exception as exc:
        result['status'] = 'fetch_or_scan_error'
        result['error_type'] = type(exc).__name__
    return [result]

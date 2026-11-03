"""Bounded, read-only diagnosis of two public electricity-provider JS bundles.

No JS execution, guessed endpoint requests, raw JS excerpts, credentials or
query strings are emitted. The diagnostic is intended for a *manual* workflow.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

MAX_JS_BYTES = 6_000_000


class ScriptProbeError(ValueError):
    """A safe, fixed reason code for a public asset that could not be scanned."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ScriptSample(str):
    """Text obtained by a bounded download, which might be a partial sample."""

    def __new__(cls, content, truncated=False):
        obj = super().__new__(cls, content)
        obj.truncated = bool(truncated)
        return obj


def _trusted_script_url(page: str, script_path: str, provider: str) -> str | None:
    """Only the previously identified official bundle for a given provider."""
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


def fetch_public_script(url: str) -> ScriptSample:
    """Read a bounded public sample, recording truncation instead of failing."""
    req = Request(url, headers={
        'User-Agent': 'HoyMeAfecta/0.5 (public source diagnostics)',
        'Accept': 'application/javascript,text/javascript,*/*',
    })
    with urlopen(req, timeout=12) as response:
        initial = urlsplit(url)
        final = urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname != initial.hostname:
            raise ScriptProbeError('redirect_to_other_host')
        content_type = (response.headers.get('Content-Type', '') or '').lower()
        if 'text/html' in content_type:
            raise ScriptProbeError('returned_html_instead_of_js')
        raw = response.read(MAX_JS_BYTES + 1)
    truncated = len(raw) > MAX_JS_BYTES
    # The end of a partial sample may split a UTF-8 code point; ignoring that
    # incomplete last point avoids treating the sample as a complete bundle.
    return ScriptSample(raw[:MAX_JS_BYTES].decode('utf-8-sig', errors='ignore'),
                        truncated=truncated)


def _safe_path(raw, provider):
    """Allow only inert, non-sensitive public-looking paths, never parameters."""
    if not raw or '?' in raw or '#' in raw or '\\' in raw:
        return None
    if any(ch in raw for ch in ('<', '>', '{', '}', '$', '@')):
        return None
    if raw.startswith('https://'):
        parsed = urlsplit(raw)
        host = (parsed.hostname or '').lower()
        if provider == 'epec_cordoba':
            allowed = host == 'epec.com.ar' or host.endswith('.epec.com.ar')
        else:
            allowed = host == 'santafe.gov.ar' or host.endswith('.santafe.gov.ar')
        if not allowed:
            return None
        path = parsed.path
    elif raw.startswith('/') or raw.startswith('api/'):
        path = raw
    else:
        return None
    if not re.fullmatch(r'[a-zA-Z0-9_./~%-]{4,160}', path) or '..' in path:
        return None
    if any(word in path.lower() for word in ('token', 'secret', 'password', 'authorize', 'auth/', 'apikey')):
        return None
    return path[:160]


def _safely_extract_hints(js: str, provider: str) -> dict:
    """Emit counts and paths only; never save the JS source or raw URL strings."""
    if provider not in ('epec_cordoba', 'epe_santa_fe'):
        raise ScriptProbeError('unknown_provider')
    if not isinstance(js, str) or len(js.encode('utf-8')) > MAX_JS_BYTES:
        raise ScriptProbeError('invalid_or_oversized_sample')
    content = js.replace('\\/', '/')
    lower = content.lower()
    keywords = ('corte', 'trabajo', 'program', 'interrup', 'servicio', 'api', 'mantenim')
    hosts = []
    candidates = []
    # URLs are never emitted verbatim: query strings, values and foreign hosts
    # are ignored. A candidate is not a verified endpoint.
    for m in re.finditer(r'https?://[a-zA-Z0-9.-]+(?::\d{1,5})?(?:/[a-zA-Z0-9._~/%-]{1,160})?', content):
        parsed = urlsplit(m.group(0))
        host = (parsed.hostname or '').lower()
        if provider == 'epec_cordoba':
            allowed = host == 'epec.com.ar' or host.endswith('.epec.com.ar')
        else:
            allowed = host == 'santafe.gov.ar' or host.endswith('.santafe.gov.ar')
        if not allowed or parsed.scheme != 'https':
            continue
        if host not in hosts:
            hosts.append(host)
        path = _safe_path(m.group(0), provider)
        if path and any(w in path.lower() for w in keywords) and path not in candidates:
            candidates.append(path)
    for m in re.finditer(r'''["'`]((?:/|api/)[a-zA-Z0-9_./:~-]{3,160})["'`]''', content):
        path = _safe_path(m.group(1), provider)
        if path and any(w in path.lower() for w in keywords) and path not in candidates:
            candidates.append(path)
    # Also search for static route literals adjacent to a real method call.
    # Count 'HttpClient' as a method call only if .get/.post/... follows;
    # its mere presence as an imported class isn't an API request.
    http_calls = list(re.finditer(r'\bhttpclient\s*\.\s*(?:get|post|request|put|delete)\s*\(', content, re.I))
    for call in http_calls[:25]:
        fragment = content[call.end(): call.end() + 200]
        match = re.match(r'''\s*["'`]([^"'`]{1,170})["'`]''', fragment)
        if not match:
            continue
        path = _safe_path(match.group(1), provider)
        if path and path not in candidates:
            candidates.append(path)
    return {
        'asset_bytes_sampled': len(js.encode('utf-8')),
        'javascript_requests_found': {
            'fetch': len(re.findall(r'\bfetch\s*\(', lower)),
            'axios_mentions': lower.count('axios'),
            'httpclient_mentions': lower.count('httpclient'),
            'httpclient_method_calls': len(http_calls),
        },
        'keyword_counts': {w: min(lower.count(w), 999) for w in ('corte', 'trabajo', 'api')},
        'official_hosts_seen': hosts[:8],
        'candidate_public_paths': candidates[:15],
        'note': 'Pistas estáticas, NO API verificadas; no se consultaron las rutas inferidas.',
    }


def probe_official_scripts(page: str, provider: str, script_paths: list[str], fetcher=None) -> list[dict]:
    """Read at most one officially hosted bundle during manual data refresh."""
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
        truncated = bool(getattr(raw, 'truncated', False))
        result['status'] = 'scanned_partial' if truncated else 'scanned'
        result['asset_sample_truncated'] = truncated
        if truncated:
            result['note'] = ('Muestra inicial limitada a 6 MB; no demuestra que la ruta '
                              'no exista en el resto del paquete. Ninguna ruta fue consultada.')
    except Exception as exc:
        result['status'] = 'fetch_or_scan_error'
        result['error_type'] = type(exc).__name__
        # Fixed reason codes only: never dump exception strings or response data.
        if isinstance(exc, ScriptProbeError):
            result['error_code'] = exc.code
        elif isinstance(exc, ValueError):
            result['error_code'] = 'other_value_error'
    return [result]

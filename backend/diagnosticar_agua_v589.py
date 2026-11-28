"""HMA v5.89: read-only diagnostic of eight public water sources per batch.
Runs the existing production collectors, never publishes or modifies feeds.
No private account queries, anti-bot bypass, cookies or alternative user agents.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import ssl
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from xml.etree import ElementTree

REVISION = 'WATER-DIAGNOSTIC-v5.89'
PRIORITY = (
    'aguas_rionegrinas_arsa', 'aguas_santafesinas', 'epas_neuquen_noticias',
    'sat_tucuman_noticias', 'santa_rosa_municipal_lp', 'aosc_corrientes_regulador',
    'parana_radio_municipal_agua', 'aysa_amba',
)

class Probe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.text = []
        self.anchors = 0
        self.scripts = 0
        self.headings = 0
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.scripts += 1
        if tag in ('script', 'style', 'svg', 'noscript'):
            self.ignored += 1
        elif not self.ignored:
            if tag == 'a' and dict(attrs).get('href'):
                self.anchors += 1
            if re.fullmatch(r'h[1-6]', tag):
                self.headings += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'svg', 'noscript'):
            self.ignored = max(0, self.ignored - 1)
    def handle_data(self, data):
        if not self.ignored:
            self.text.append(data)


def inspect_document(body):
    """Structural evidence only. No raw HTML or user data in the report."""
    raw = body.encode('utf-8', errors='replace')
    stats = {'decoded_utf8_bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
    if not body.strip():
        return dict(stats, document_kind='empty', anchors=0, visible_characters=0)
    if re.match(r'\s*(?:<\?xml[^>]*\?>\s*)?<(?:rss\b|feed\b|rdf:RDF\b)', body, re.I):
        try:
            root = ElementTree.fromstring(body)
            count = sum(x.tag.rsplit('}', 1)[-1] in ('item', 'entry') for x in root.iter())
            return dict(stats, document_kind='xml_feed', feed_items=count)
        except ElementTree.ParseError:
            return dict(stats, document_kind='invalid_xml_feed')
    p = Probe()
    p.feed(body)
    p.close()
    visible = ' '.join(' '.join(p.text).split())
    low = visible.casefold()
    # Only short, unlinked pages can receive a possible interstitial label.
    # Never interpret a site's ordinary article mentioning a captcha as a block.
    guard = any(x in low for x in (
        'just a moment', 'checking your browser', 'verify you are human',
        'enable javascript and cookies', 'access denied', 'request blocked',
        'verifica que eres humano', 'verificá que sos humano', 'acceso denegado',
        'habilite javascript', 'enable javascript to continue',
    ))
    if len(visible) < 700 and p.anchors <= 2 and guard:
        kind = 'possible_access_interstitial'
    elif p.anchors == 0 and len(visible) < 200 and p.scripts:
        kind = 'possible_script_shell_or_interstitial'
    elif not p.anchors and len(visible) < 200:
        kind = 'little_visible_content'
    elif p.anchors:
        kind = 'html_with_links'
    else:
        kind = 'html_text_without_links'
    return dict(stats, document_kind=kind, anchors=p.anchors,
                visible_characters=len(visible), scripts=p.scripts, headings=p.headings)


def error_details(exc):
    data = {'error_type': type(exc).__name__}
    if isinstance(exc, HTTPError):
        data['http_status'] = exc.code
    elif isinstance(exc, URLError):
        reason = exc.reason
        data['reason_type'] = type(reason).__name__
        if isinstance(reason, socket.gaierror):
            data['reason_kind'] = 'dns'
        elif isinstance(reason, ssl.SSLError):
            data['reason_kind'] = 'tls'
        elif isinstance(reason, TimeoutError):
            data['reason_kind'] = 'timeout'
        elif isinstance(reason, ConnectionError):
            data['reason_kind'] = 'connection'
        else:
            data['reason_kind'] = 'other_url_error'
    elif isinstance(exc, TimeoutError):
        data['reason_kind'] = 'timeout'
    return data


class TracedFetcher:
    """Use the installed collector's fetcher unchanged; stop further calls on 429."""
    _production_network_fetch = True
    def __init__(self, fetch, clock=monotonic, max_requests=16, max_seconds=90):
        self.fetch = fetch
        self.clock = clock
        self.started = clock()
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self.attempts = []
        self.rate_limited = False
        self.budget_exhausted = False
    def __call__(self, url):
        if self.rate_limited:
            raise RuntimeError('Rate limited: no further requests in this source')
        if len(self.attempts) >= self.max_requests or self.clock() - self.started >= self.max_seconds:
            self.budget_exhausted = True
            raise RuntimeError('Source diagnostic budget exhausted')
        if urlsplit(url).scheme != 'https':
            raise ValueError('HTTPS required')
        started = self.clock()
        # Report only URLs without query values; do not print credentials or HTML.
        u = urlsplit(url)
        entry = {'url': f'{u.scheme}://{u.hostname}{u.path}', 'query_present': bool(u.query)}
        self.attempts.append(entry)
        try:
            body = self.fetch(url)
            entry['result'] = 'document_received'
            try:
                entry.update(inspect_document(body))
            except Exception as diagnostic_exc:
                entry['inspection_error'] = type(diagnostic_exc).__name__
            return body
        except Exception as exc:
            entry.update(result='fetch_error', **error_details(exc))
            if isinstance(exc, HTTPError) and exc.code == 429:
                self.rate_limited = True
            raise
        finally:
            entry['elapsed_ms'] = round((self.clock() - started) * 1000)


def ordered_batches(keys):
    keys = tuple(keys)
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate sources')
    missing = set(PRIORITY) - set(keys)
    if missing:
        raise ValueError('Missing priority sources: ' + ', '.join(sorted(missing)))
    order = PRIORITY + tuple(k for k in keys if k not in PRIORITY)
    return [order[i:i + 8] for i in range(0, len(order), 8)]


def disposition(result, trace):
    if result.get('coverage_kind') == 'address_account_lookup_only' or result.get('access_mode') == 'account_required':
        return 'account_only_not_public_status'
    if result.get('notices'):
        return 'public_bulletins_accepted_not_live'
    if trace.rate_limited:
        return 'rate_limited'
    if trace.budget_exhausted:
        return 'query_budget_exhausted'
    attempts = trace.attempts
    if attempts and all(a.get('http_status') == 403 for a in attempts):
        return 'all_requests_forbidden'
    if attempts and all(a.get('result') == 'fetch_error' for a in attempts):
        return 'all_requests_failed'
    if result.get('status') == 'stale':
        return 'old_bulletins_not_live'
    if result.get('article_links_seen', 0) or result.get('articles_checked', 0):
        return 'collector_read_links_no_accepted_bulletin'
    docs = [a for a in attempts if a.get('result') == 'document_received']
    if any(a.get('document_kind') == 'xml_feed' for a in docs):
        return 'feed_received_no_accepted_bulletin'
    if any(a.get('anchors', 0) > 0 for a in docs):
        return 'html_links_received_collector_no_accepted_bulletin'
    if any(a.get('document_kind', '').startswith('possible_') for a in docs):
        return 'possible_script_shell_or_access_interstitial'
    return 'unverified_no_accepted_bulletin'


def run_one(module, key, checked_at, fetch=None):
    trace = TracedFetcher(fetch or module.fetch_html,
        max_requests=min(16, getattr(module, 'MAX_NETWORK_FETCHES_PER_SOURCE', 16)),
        max_seconds=min(90, getattr(module, 'MAX_SOURCE_NETWORK_SECONDS', 90)))
    try:
        result = module._safe_source_result(key, module.collect_one(key, checked_at, fetcher=trace), checked_at)
    except Exception as exc:
        result = {'status': 'unverified', 'notices': [], 'notifications_enabled': False, 'message': 'Isolated collector failure: ' + type(exc).__name__}
    # Treat unsafe output as a test failure, not as a notice to publish.
    notices = result.get('notices', [])
    safety_errors = []
    if result.get('notifications_enabled') is not False:
        safety_errors.append('source_notifications_not_false')
    if any(n.get('notification_allowed') is not False for n in notices):
        safety_errors.append('notice_notifications_not_false')
    if key == 'aysa_amba' and notices:
        safety_errors.append('account_only_source_emitted_notices')
    if safety_errors:
        result = dict(result, notices=[], status='unverified')
    return {'source': key, 'diagnostic': disposition(result, trace),
            'collector_result': result, 'requests': trace.attempts,
            'rate_limited': trace.rate_limited, 'budget_exhausted': trace.budget_exhausted,
            'safety_errors': safety_errors}


def run_batch(module, batch):
    groups = ordered_batches(module.SOURCES)
    if not 1 <= batch <= len(groups):
        raise ValueError('Batch outside range')
    checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    selected = groups[batch - 1]
    # At most four independent providers simultaneously, as in production.
    with ThreadPoolExecutor(max_workers=min(4, max(1, getattr(module, 'MAX_PARALLEL_SOURCES', 4)))) as pool:
        reports = list(pool.map(lambda key: run_one(module, key, checked_at), selected))
    return {'revision': REVISION, 'generated_at': checked_at, 'batch': batch,
            'total_batches': len(groups), 'configured_sources': len(module.SOURCES),
            'sources_checked': len(reports), 'notifications_enabled': False,
            'production_feed_changed': False, 'results': reports,
            'interpretation': 'Public bulletins and technical diagnostics only; no live supply inference.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, default=1)
    parser.add_argument('--output', default='water_diagnostic_v589.json')
    args = parser.parse_args()
    import water_notices
    report = run_batch(water_notices, args.batch)
    output = Path(args.output)
    # Prevent accidental overwrites of production JSON, even if run manually.
    if output.name != 'water_diagnostic_v589.json':
        parser.error('Output filename must be water_diagnostic_v589.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('HMA', REVISION, 'batch', args.batch, 'sources', report['sources_checked'])
    for item in report['results']:
        print(f"{item['source']}: {item['diagnostic']}; requests={len(item['requests'])}; notices={len(item['collector_result'].get('notices', []))}")
    return 1 if any(x['safety_errors'] for x in report['results']) else 0


if __name__ == '__main__':
    raise SystemExit(main())

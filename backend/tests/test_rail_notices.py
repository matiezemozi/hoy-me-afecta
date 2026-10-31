import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import collector
from rail_notices import collect_rail_notices, parse_official_news, _safe_article_href

NOW = '2026-10-31T15:00:00Z'
HTML = '''<html><main><h2>Noticias</h2>
<div class="views-row"><div class="fecha">26 de octubre de 2026</div>
<h3><a href="/noticias/la-linea-mitre-retoma-los-servicios">
Con un avance en las vías, la línea Mitre retoma sus servicios</a></h3></div>
<div><span>23 de octubre de 2026</span><a href="/noticias/linea-sarmiento-andenes-centrales">
Línea Sarmiento: vuelven las paradas en los andenes centrales</a></div>
<div><span>17 de agosto de 2026</span><a href="/noticias/linea-roca-interrumpida">
Línea Roca: el servicio estará interrumpido</a></div>
<div><span>30 de octubre de 2026</span><a href="/noticias/linea-san-martin-locomotoras">
La línea San Martín repara una locomotora para mejorar el futuro</a></div>
<div><span>29 de octubre de 2026</span><a href="https://evil.example.com/noticias/linea-roca-interrumpida">
Línea Roca: el servicio está interrumpido</a></div>
</main></html>'''


class RailNoticesTests(unittest.TestCase):
    def test_dated_relevant_articles_not_old_or_maintenance(self):
        dated, notices = parse_official_news(HTML, NOW)
        self.assertGreaterEqual(dated, 3)
        self.assertEqual({n['line'] for n in notices}, {'Mitre', 'Sarmiento'})
        self.assertEqual(notices[0]['published_on'], '2026-10-26')
        self.assertEqual(notices[0]['kind'], 'comunicado_oficial')
        self.assertNotIn('status', notices[0])

    def test_missing_date_fails_closed(self):
        result = collect_rail_notices(NOW, fetch_html=lambda: '<a href="/noticias/linea-mitre">Línea Mitre: servicio interrumpido</a>')
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['notices'], [])

    def test_empty_recent_set_is_not_a_normal_status(self):
        page = '<span>17 de agosto de 2026</span><a href="/noticias/roca-interrumpida">Línea Roca: servicio interrumpido</a>'
        result = collect_rail_notices(NOW, fetch_html=lambda: page)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['notices'], [])
        self.assertIn('NO estado en tiempo real', result['message'])

    def test_does_not_trust_external_url(self):
        self.assertIsNone(_safe_article_href('https://fake.argentina.gob.ar.example.com/noticias/x'))
        self.assertIsNone(_safe_article_href('http://www.argentina.gob.ar/noticias/x'))
        self.assertIsNone(_safe_article_href('javascript:alert(1)'))
        self.assertIsNone(_safe_article_href('/transporte/trenes-argentinos/noticias'))

    def test_fetch_failure_does_not_claim_normal(self):
        def fail(): raise TimeoutError('network unreachable')
        result = collect_rail_notices(NOW, fetch_html=fail)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['notices'], [])

    def test_future_article_is_excluded(self):
        html = '<time datetime="2026-11-01"></time><a href="/noticias/roca">Línea Roca: servicio interrumpido</a>'
        _, items = parse_official_news(html, NOW)
        self.assertEqual(items, [])

    def test_integrated_feed_does_not_mix_news_and_active_outages(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'bus.json').write_text('[]', encoding='utf-8')
            (root/'pub.json').write_text('[]', encoding='utf-8')
            with patch.object(collector, 'now_utc', return_value=NOW), \
                 patch.object(collector, 'fetch_js', return_value={'cortesBaja': []}):
                collector.collect(root/'feed.json', root/'bus.json', root/'pub.json',
                                  fetch_rail=lambda stamp: collect_rail_notices(stamp, fetch_html=lambda: HTML))
            output = json.loads((root/'feed.json').read_text(encoding='utf-8'))
            self.assertEqual(len(output['rail_official']['notices']), 2)
            self.assertEqual(output['alerts'], [])
            self.assertEqual(output['coverage']['trains'], 'manual_notices_only')
            self.assertEqual(output['coverage']['train_publications'], 'dated_official_news_only')


if __name__ == '__main__': unittest.main()

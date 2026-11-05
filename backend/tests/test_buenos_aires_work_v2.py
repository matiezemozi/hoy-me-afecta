"""Regression checks against structures published by EDEN, EDEA and EDES (05 Nov 2026).

Fixtures use short examples, not copies of complete third-party pages. Offline tests
only: live extraction must still be checked by GitHub Actions.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buenos_aires_work import SOURCES, collect_buenos_aires, extract_works
from collector import collect

# The official pages posted work for Thursday November 5, 2026.
EDEN = '''<html><body><h2>Obras en tu barrio</h2>
<p>Jueves 5 de Noviembre</p>
<p>VEDIA</p><p>Zona por Av. Moreno, Las Heras y Pueyrredon, de 9.30 a 14.45 hs.</p>
<p>LOS CARDALES</p><p>Carlos Leeme, Av Arturo Frondizi e Irizar, de 10.00 a 16.00 hs.</p>
<p>Los trabajos pueden implicar la interrupción del servicio.</p>
</body></html>'''
EDEA = '''<html><body><h2>Obras en tu barrio</h2>
<p>Jueves 5 de noviembre</p>
<p>MAR DEL PLATA</p>
<p>de Fray Luis Beltran a Zeballos y de Pujia a Bautista en el horario de 10:00 hs a 11:00 hs.</p>
<p>SANTA CLARA DEL MAR</p>
<p>de Av. Montreal a Palma y de San Juan de Luz a Costanera en el horario de 07:30 hs a 14:30 hs.</p>
<p>Los trabajos pueden implicar la interrupción del servicio.</p>
</body></html>'''
EDES = '''<html><body><h2>Obras en tu barrio</h2>
<p>Jueves 5 de noviembre</p>
<p>BAHIA BLANCA</p>
<p>de 9 a a 11hs, afecta al cuadrante comprendido por las calles: Terrada, Sixto Laspiur, Biggio, Gonzalez.</p>
<p>de 9 a 11hs, afecta al cuadrante comprendido por las calles: Figueroa Alcorta, Canning, Lavalle y Reconquista.</p>
<p>de 8:30 a 13:30hs, afecta al cuadrante comprendido por las calles: Corrientes, San Lorenzo, Azara, Liniers.</p>
<p>de 8 a 12hs, afecta al cuadrante comprendido por las calles: Ruta Provincial 85, Juncal y Camino Rural.</p>
<p>Los trabajos pueden implicar la interrupción del servicio.</p>
</body></html>'''
EDELAP = '''<html><body><h1>Trabajamos todos los días para darte más energía</h1>
<h2>Obras en tu barrio</h2><p>Próximamente estaremos trabajando</p>
<h3>Jueves 5 de Noviembre</h3><ul>
<li>de 8 a 16 hs. en la zona de Austria y Almafuerte, Ensenada.</li>
<li>de 8 a 16 hs. en la zona de 44 a 46 y de 133 a 137, San Carlos.</li>
<li>de 8 a 17 hs. en la zona de 208 a 230 y de 460 a 492, Abasto.</li>
<li>de 8 a 11 hs. sobre 47 de 10 a 11, La Plata.</li>
<li>de 9 a 17 hs. en la zona de Costanera y Camino Negro, Punta Lara.</li></ul>
<p>Los trabajos pueden implicar la interrupción del servicio.</p>
</body></html>'''
EARLY = '2026-11-05T11:00:00Z'  # 08:00 in Argentina
LATE = '2026-11-05T19:53:43Z'   # 16:53 in Argentina
NIGHT = '2026-11-05T23:05:17Z'  # 20:05; all four sources finished
PAGES = {SOURCES[k][1]: v for k, v in zip(
    ['eden_buenos_aires', 'edea_buenos_aires', 'edes_buenos_aires', 'edelap_buenos_aires'],
    [EDEN, EDEA, EDES, EDELAP])}

class BuenosAiresWorkV2Tests(unittest.TestCase):
    def test_official_urls_and_three_keys(self):
        self.assertEqual(set(SOURCES), {'eden_buenos_aires', 'edea_buenos_aires', 'edes_buenos_aires', 'edelap_buenos_aires'})
        self.assertEqual(SOURCES['edes_buenos_aires'][1], 'https://www.infoedes.com/obras-en-tu-barrio/')

    def test_eden_current_page_early_and_late(self):
        early, days, areas = extract_works(EDEN, 'eden_buenos_aires', EARLY)
        late, _, _ = extract_works(EDEN, 'eden_buenos_aires', LATE)
        self.assertEqual((days, areas), (1, 2))
        self.assertEqual(len(early), 2)
        self.assertEqual(late, [])

    def test_edea_current_page_early_and_late(self):
        early, days, areas = extract_works(EDEA, 'edea_buenos_aires', EARLY)
        late, _, _ = extract_works(EDEA, 'edea_buenos_aires', LATE)
        self.assertEqual((days, areas), (1, 2))
        self.assertEqual(len(early), 2)
        self.assertEqual(late, [])

    def test_edes_hour_only_ranges_and_malformed_not_invented(self):
        early, days, areas = extract_works(EDES, 'edes_buenos_aires', EARLY)
        self.assertEqual((days, areas), (1, 1))
        self.assertEqual(len(early), 3)
        self.assertTrue(all(n['locality_hint'] == 'BAHIA BLANCA' for n in early))
        self.assertTrue(all(n['company'] == 'EDES' for n in early))
        self.assertEqual({n['scheduled_end'][11:16] for n in early}, {'11:00', '12:00', '13:30'})
        self.assertTrue(all('Terrada' not in n['zone_detail'] for n in early))
        self.assertTrue(all(n['status'] == 'scheduled_not_confirmed' for n in early))

    def test_all_finished_explained_not_misleading_absence(self):
        r = collect_buenos_aires(NIGHT, fetch=lambda url: PAGES[url])
        for item in r.values():
            self.assertEqual(item['status'], 'stale')
            self.assertEqual(item['schedule_state'], 'all_recognized_work_hours_finished')
            self.assertEqual(item['notices'], [])
            self.assertEqual(item['complete_work_entries'], item['already_finished_entries'])
            self.assertGreater(item['complete_work_entries'], 0)
            self.assertIn('ya terminaron', item['message'])
            self.assertIn('no significa servicio normal', item['message'].lower())

    def test_four_sources_independently_return_valid_work(self):
        r = collect_buenos_aires(EARLY, fetch=lambda url: PAGES[url])
        self.assertEqual([r[key]['status'] for key in SOURCES], ['ok', 'ok', 'ok', 'ok'])
        self.assertEqual([len(r[key]['notices']) for key in SOURCES], [2, 2, 3, 5])
        self.assertTrue(all(n['source_url'] in PAGES for x in r.values() for n in x['notices']))

    def test_edelap_five_localities_from_published_page(self):
        works, date_sections, localities = extract_works(EDELAP, 'edelap_buenos_aires', EARLY)
        self.assertEqual((date_sections, localities, len(works)), (1, 5, 5))
        self.assertEqual({w['locality_hint'] for w in works},
                         {'Ensenada', 'San Carlos', 'Abasto', 'La Plata', 'Punta Lara'})
        self.assertEqual(next(w for w in works if w['locality_hint']=='Ensenada')['scheduled_end'], '2026-11-05T16:00-03:00')
        self.assertTrue(all(w['company']=='EDELAP' for w in works))
        self.assertTrue(all(w['status']=='scheduled_not_confirmed' for w in works))

    def test_edelap_ignores_missing_locality_invalid_hours_and_canceled(self):
        page = EDELAP.replace(', Ensenada.', '.')
        page = page.replace('de 8 a 16 hs. en la zona de 44', 'de 16 a 8 hs. en la zona de 44')
        page = page.replace('de 8 a 17 hs. en la zona de 208', 'Suspendido: de 8 a 17 hs. en la zona de 208')
        page = page.replace(', Punta Lara.', ', localidad indeterminada.')
        works, _, _ = extract_works(page, 'edelap_buenos_aires', EARLY)
        self.assertEqual([w['locality_hint'] for w in works], ['La Plata'])

    def test_edelap_past_schedules_are_not_alerted(self):
        report = collect_buenos_aires(NIGHT, fetch=lambda url: PAGES[url])
        item = report['edelap_buenos_aires']
        self.assertEqual((item['status'], item['complete_work_entries'], item['already_finished_entries']),
                         ('stale', 5, 5))
        self.assertEqual(item['schedule_state'], 'all_recognized_work_hours_finished')
        self.assertEqual(item['parser_revision'], 'BA-v5.18')

    def test_edelap_date_or_city_not_inferred(self):
        page = EDELAP.replace('Jueves 5 de Noviembre', 'Sin fecha')
        self.assertEqual(extract_works(page, 'edelap_buenos_aires', EARLY)[0], [])
        self.assertEqual(extract_works(EDELAP, 'edelap_buenos_aires', '2026-11-20T11:00:00Z')[0], [])

    def test_only_edes_down_isolated(self):
        def fetch(url):
            if 'infoedes.com' in url:
                raise TimeoutError('temporary')
            return PAGES[url]
        r = collect_buenos_aires(EARLY, fetch=fetch)
        self.assertEqual(r['edes_buenos_aires']['status'], 'unverified')
        self.assertEqual(r['eden_buenos_aires']['status'], 'ok')
        self.assertEqual(r['edea_buenos_aires']['status'], 'ok')

    def test_canceled_edes_is_not_collected(self):
        html = EDES.replace('de 8 a 12hs, afecta', 'Suspendido: de 8 a 12hs, afecta')
        r, _, _ = extract_works(html, 'edes_buenos_aires', EARLY)
        self.assertEqual(len(r), 2)

    def test_new_source_remains_outside_live_alerts_and_push(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)
            with patch('collector.fetch_js', return_value={'cortes': []}):
                collect(path/'feed.json', path/'nomanual.json', path/'nopublic.json',
                        fetch_buenos_aires_work=lambda _: collect_buenos_aires(EARLY, fetch=lambda url: PAGES[url]))
            feed = json.loads((path/'feed.json').read_text(encoding='utf-8'))
            self.assertEqual(feed['alerts'], [])
            self.assertEqual(feed['notification_events']['events'], [])
            self.assertEqual(feed['buenos_aires_work']['edes_buenos_aires']['status'], 'ok')
            self.assertIn('EDES', [p['provider'] for p in feed['coverage_argentina']['electricity']])
            self.assertFalse(feed['coverage_argentina']['national_electricity_coverage'])

if __name__ == '__main__':
    unittest.main()

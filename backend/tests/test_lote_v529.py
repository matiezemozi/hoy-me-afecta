import unittest
from datetime import datetime

import provincial_outages as p

T = '2026-11-10T20:00:00Z'  # 17:00 Argentina
NOW = p._instant(T)


class LoteV529Tests(unittest.TestCase):
    def test_five_sources_registered(self):
        for key in ('corpico_general_pico', 'calf_neuquen', 'energia_misiones',
                    'edelar_la_rioja', 'scpl_comodoro'):
            self.assertIn(key, p.PROVIDERS)
            self.assertEqual(p.PROVIDERS[key][2].split(':')[0], 'https')

    def test_corpico_explicit_no_programmed_cuts_not_service_normal(self):
        html = '<h1>Cortes programados</h1><p>No hay cortes programadados</p>'
        r = p.collect_one('corpico_general_pico', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['notices'], [])
        self.assertIn('PROGRAMADOS', r['message'])
        self.assertIn('NO confirma servicio eléctrico normal', r['message'])
        self.assertNotIn('latest_published_date', r)

    def test_corpico_requires_real_zone_not_image(self):
        html = '<h1>Cortes programados</h1><p>11 NOV. 2026 Eléctrico 08:00 a 12:00 hs Ver Mapa <img src="zona.png">Mantenimiento</p>'
        r = p.collect_one('corpico_general_pico', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(r['notices'], [])

    def test_corpico_future_complete_entry(self):
        html = '<h1>Cortes programados</h1><p>11 NOV. 2026 Eléctrico 08:00 a 12:00 hs Zona Afectada: Barrio Villa Esperanza y calles 12 a 20 Ver Mapa Mantenimiento</p>'
        r = p.collect_one('corpico_general_pico', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)
        self.assertEqual(r['notices'][0]['scheduled_start'], '2026-11-11T08:00-03:00')

    def test_edelar_regional_general_page_no_fake_schedule(self):
        html = '<h1>Cortes programados</h1><h2>Región Capital & Sanagasta</h2><p>Trabajos de mejora en toda la provincia</p>'
        r = p.collect_one('edelar_la_rioja', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(len(r['notices']), 0)

    def test_edelar_complete_schedule_row(self):
        html = '<h1>Cortes programados</h1><table><tr><th>Fecha</th><th>Horario</th><th>Zona</th></tr><tr><td>11/11/2026</td><td>08:00 a 12:00</td><td>Barrio San Martín, calle Norte 123 a 456</td></tr></table>'
        r = p.collect_one('edelar_la_rioja', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)

    def test_misiones_only_form_is_unverified(self):
        html = '<h1>Cortes programados</h1><select><option>Localidad</option></select><input>'
        r = p.collect_one('energia_misiones', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(r['notices'], [])

    def test_misiones_table_if_published_as_html(self):
        html = '<h1>Cortes Programados</h1><table><tr><td>11/11/2026</td><td>08:00 a 11:00</td><td>Zona Barrio Norte y calles Tucumán a Sarmiento</td></tr></table>'
        r = p.collect_one('energia_misiones', T, fetcher=lambda url: html)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1)

    def test_scpl_valid_future_official_article(self):
        home = '<a href="/index.php/site/ver-nota?id=2919">CORTE PROGRAMADO DE ENERGÍA EN COMODORO</a>'
        article = ('<h1>CORTE PROGRAMADO DE ENERGÍA EN COMODORO</h1>'
                   '<p>10-11-2026</p><p>El miércoles 11 de noviembre, desde las 08:00hs. y hasta las 12:00hs., '
                   'se interrumpe el suministro eléctrico en los siguientes barrios: '
                   'Barrio Centro, calle Rivadavia entre 10 y 20 y zona industrial, '
                   'con el objetivo de realizar mantenimiento. Depto. Servicio Eléctrico</p>')
        def fetch(url):
            return article if 'ver-nota' in url else home
        r = p.collect_one('scpl_comodoro', T, fetcher=fetch)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['notices']), 1, r)
        self.assertEqual(r['notices'][0]['source_url'], 'https://www.scpl.coop/index.php/site/ver-nota?id=2919')

    def test_scpl_old_programmed_work_stale_not_alert(self):
        home = '<a href="/index.php/site/ver-nota?id=2904">CORTE PROGRAMADO DE ENERGÍA</a>'
        article = ('<h1>CORTE PROGRAMADO DE ENERGÍA</h1><p>23-10-2026</p>'
                   '<p>El domingo 25 de octubre, desde las 08:00hs. y hasta las 12:00hs., '
                   'se interrumpe el suministro eléctrico en los siguientes barrios: '
                   'Sector del Centro, barrio 25 de Mayo, Km 4 y Km 5, '
                   'con el objetivo de realizar mantenimiento eléctrico.</p>')
        r = p.collect_one('scpl_comodoro', T,
                          fetcher=lambda url: article if 'ver-nota' in url else home)
        self.assertEqual(r['status'], 'stale', r)
        self.assertEqual(r['notices'], [])

    def test_scpl_cancelled_article_never_notified(self):
        home = '<a href="/index.php/site/ver-nota?id=2917">CORTE PROGRAMADO DE ENERGÍA</a>'
        article = ('<h1>SE SUSPENDE CORTE PROGRAMADO DE ENERGÍA</h1><p>10-11-2026</p>'
                   '<p>El miércoles 11 de noviembre, desde las 08:00hs. y hasta las 12:00hs., '
                   'se interrumpe el suministro eléctrico en los siguientes barrios: '
                   'Barrio Centro, calle Rivadavia entre 10 y 20 y zona industrial, '
                   'con el objetivo de realizar mantenimiento. suspendido.</p>')
        r = p.collect_one('scpl_comodoro', T,
                          fetcher=lambda url: article if 'ver-nota' in url else home)
        self.assertEqual(r['notices'], [])
        self.assertEqual(r['status'], 'unverified')

    def test_scpl_water_event_not_mislabeled_electricity(self):
        home = '<a href="/index.php/site/ver-nota?id=2917">CORTE PROGRAMADO DE AGUA EN COMODORO</a>'
        article = ('<h1>CORTE PROGRAMADO DE AGUA EN COMODORO</h1><p>10-11-2026</p>'
                   '<p>El miércoles 11 de noviembre, desde las 08:00hs. y hasta las 12:00hs., '
                   'se interrumpe el suministro de agua en los siguientes barrios: '
                   'Barrio Centro, calle Rivadavia entre 10 y 20 y zona industrial, '
                   'con el objetivo de realizar mantenimiento eléctrico.</p>')
        r = p.collect_one('scpl_comodoro', T,
                          fetcher=lambda url: article if 'ver-nota' in url else home)
        self.assertEqual(r['notices'], [])

    def test_calf_image_only_unverified(self):
        home = ('<a href="https://www.cooperativacalf.com.ar/corte-programado-29/">'
                'Corte programado</a>')
        article = '<h1>Corte programado</h1><p>noviembre 10, 2026</p><img src="cartel.jpg">'
        r = p.collect_one('calf_neuquen', T,
                          fetcher=lambda url: article if 'corte-programado-29' in url else home)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(r['notices'], [])

    def test_foreign_article_host_ignored(self):
        home = ('<a href="https://evil.example/site/ver-nota?id=12">Corte programado</a>'
                '<a href="http://www.scpl.coop/index.php/site/ver-nota?id=13">Corte programado</a>')
        r = p.collect_one('scpl_comodoro', T, fetcher=lambda url: home)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(r.get('article_links_seen'), 0)

    def test_failure_isolation_from_old_provider(self):
        def fetch(url):
            raise ConnectionError('network')
        r = p.collect_one('scpl_comodoro', T, fetcher=fetch)
        self.assertEqual(r['status'], 'unverified')
        self.assertEqual(r['source_attempts'][0]['error_type'], 'ConnectionError')
        self.assertNotIn('network', str(r))


if __name__ == '__main__':
    unittest.main()

class BarilocheV529Tests(unittest.TestCase):
    def test_ceb_visible_future_complete_schedule(self):
        page = '<a href="/11-11-2026/">11/11/2026</a>'
        article = ('<h1>11/11/2026</h1><p>MEJORAS PROGRAMADAS. Corte programado de energía eléctrica.'
                   ' Este miércoles 11 de noviembre, de 09:30 a 14:00 hs., se realizarán tareas en la línea.'
                   ' Zona afectada: Barrio Lomas del Oeste, Ruta Provincial 82 y desde Lago Moreno hasta escuela 12. '
                   ' Una red más sólida y confiable. RED CONFIABLE.</p>')
        r = p.collect_one('ceb_bariloche', T, fetcher=lambda u: article if '/11-11-2026/' in u else page)
        self.assertEqual(r['status'], 'ok', r)
        self.assertEqual(len(r['notices']), 1)
        self.assertEqual(r['notices'][0]['province'], 'Río Negro')

    def test_ceb_archive_title_conflicts_with_article_date(self):
        page = '<a href="/23-11-2026/">Corte Programado 23/11/2026</a>'
        article = ('<h1>Corte Programado 23/11/2026</h1><p>Corte programado de energía eléctrica. '
                   'El viernes 23 de enero, de 09:30 a 12:30 hs., se interrumpirá la energía. '
                   'Zona afectada: Barrio Entre Pinos, todas las calles y escuela 20. Una red más sólida.</p>')
        r = p.collect_one('ceb_bariloche', T, fetcher=lambda u: article if '/23-11-2026/' in u else page)
        self.assertEqual(r['status'], 'unverified', r)
        self.assertEqual(r['notices'], [])

    def test_ceb_old_complete_article_is_stale(self):
        page = '<a href="/06-11-2026/">06/11/2026</a>'
        article = ('<h1>06/11/2026</h1><p>Corte programado de energía eléctrica. '
                   'Este viernes 6 de noviembre, de 09:30 a 14:00 hs. '
                   'Zona afectada: Barrio Villa Lago Gutiérrez, desde Ruta Nacional 40 hasta Villa Arelauquen. '
                   'Una red más sólida.</p>')
        r = p.collect_one('ceb_bariloche', T, fetcher=lambda u: article if '/06-11-2026/' in u else page)
        self.assertEqual(r['status'], 'stale', r)
        self.assertEqual(r['notices'], [])

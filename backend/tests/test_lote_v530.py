import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import provincial_outages as p

STAMP='2026-11-10T20:00:00Z'
NOW=p._instant(STAMP)

class BatchV530(unittest.TestCase):
    def test_new_sources_registered(self):
        for source in ('cepa_punta_alta','spse_santa_cruz',
                       'servicoop_puerto_madryn','usina_tandil'):
            self.assertIn(source,p.PROVIDERS)
            self.assertTrue(p.PROVIDERS[source][2].startswith('https://'))

    def test_cepa_today_only_no_cuts_is_not_full_coverage(self):
        html='<h2>Trabajos y cortes</h2><p>No hay trabajos o cortes programados en el día de la fecha</p>'
        r=p.collect_one('cepa_punta_alta',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['notices'],[])
        self.assertEqual(r['coverage_horizon'],'today_only')
        self.assertIn('HOY',r['message'])
        self.assertNotIn('latest_published_date',r)

    def test_cepa_landing_without_no_cuts_remains_unverified(self):
        r=p.collect_one('cepa_punta_alta',STAMP,fetcher=lambda u:'<h2>Trabajos para mejorar servicio</h2>')
        self.assertEqual(r['status'],'unverified')

    def test_spse_empty_public_calendar(self):
        html='<h1>Suspensión Servicios</h1><p>Por el momento no se encuentran cortes/interrupciones programadas.</p>'
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'ok')
        self.assertFalse(r['notices'])
        self.assertIn('no tener interrupciones programadas',r['message'])

    def test_spse_ambiguous_notice_no_fake_event(self):
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:'<h1>Cortes programados</h1><p>Trabajos de mantenimiento en Rio Gallegos</p>')
        self.assertEqual(r['status'],'unverified')

    def test_spse_table_future_complete(self):
        html='<table><tr><th>Fecha</th><th>Hora</th><th>Zona</th></tr><tr><td>11/11/2026</td><td>08:00 a 12:00</td><td>Barrio San Benito, calle 15 y 16, Río Gallegos</td><td>Energía eléctrica</td></tr></table>'
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1,r)

    def test_spse_water_event_not_electricity(self):
        html='<table><tr><td>11/11/2026</td><td>08:00 a 12:00</td><td>Barrio San Benito, Río Gallegos</td><td>Agua potable</td></tr></table>'
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])

    def test_spse_expired_table_never_notified(self):
        html='<table><tr><td>05/11/2026</td><td>08:00 a 12:00</td><td>Barrio San Benito, calle 15 y 16, Río Gallegos</td><td>Energía eléctrica</td></tr></table>'
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'stale',r)
        self.assertFalse(r['notices'])

    def test_spse_cancelled_table_never_notified(self):
        html='<table><tr><td>11/11/2026</td><td>08:00 a 12:00</td><td>Barrio San Benito, calle 15 y 16, Río Gallegos</td><td>Energía eléctrica - cancelado</td></tr></table>'
        r=p.collect_one('spse_santa_cruz',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'unverified')
        self.assertFalse(r['notices'])

    def test_usina_requires_public_work_schedule(self):
        html='<h1>Usina Tandil</h1><h2>OBRAS PROGRAMADAS</h2><p>Ingresar a Oficina Virtual</p>'
        r=p.collect_one('usina_tandil',STAMP,fetcher=lambda u:html)
        self.assertEqual(r['status'],'unverified',r)
        self.assertEqual(r['notices'],[])

    def test_usina_public_old_news_parses_but_is_expired(self):
        html='''<h1>Corte programado</h1><p>Ago 18, 2026</p><p>La Usina informa que
        el jueves 20 de agosto, entre las 8 y las 11hs, se realizará un corte programado
        del servicio eléctrico por obras y ampliaciones en la red.</p>
        <p>Zona comprendida: poligonal delimitada por las calles San Martín, Montiel,
        Belgrano, Combate de Obligado, Maipú, Alsina, 4 de Abril y Pinto.</p>
        <footer>© Usina de Tandil</footer>'''
        url='https://www.usinatandil.com.ar/2026/08/18/corte-programado/'
        items,n,day=p._parse_usina_article_v530(html,NOW,url)
        self.assertEqual(n,1)
        self.assertFalse(items)
        self.assertEqual(day.isoformat(),'2026-08-20')

    def test_usina_future_news_validates_street_named_date(self):
        home='<a href="/2026/11/10/corte-programado/">Corte programado</a>'
        html='''<h1>Corte programado</h1><p>Nov 10, 2026</p><p>La Usina informa que
        el miércoles 11 de noviembre, entre las 8 y las 11hs, se realizará un corte programado
        del servicio eléctrico por obras y ampliaciones en la red.</p>
        <p>Zona comprendida: poligonal delimitada por las calles San Martín, Montiel,
        Belgrano, Combate de Obligado, Maipú, Alsina, 4 de Abril y Pinto.</p>
        <footer>© Usina de Tandil</footer>'''
        r=p.collect_one('usina_tandil',STAMP,
            fetcher=lambda u:html if '/2026/11/10/' in u else home)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1)
        self.assertIn('4 de Abril',r['notices'][0]['zone_detail'])

    def test_ceb_actual_11_11_short_zone(self):
        home='<a href="/corte-programado-11-11-2026/">Corte Programado 11/11/2026</a>'
        article=('''<h1>Corte Programado 11/11/2026</h1>
        <h3>CORTE PROGRAMADO</h3><p>Este miércoles 11 de noviembre, de 09:30 a 11:30 hs.,
        se realizarán tareas de mantenimiento en una Subestación Transformadora que abastece al
        barrio Las Marías. Para llevar adelante los trabajos será necesario efectuar un corte
        programado de energía eléctrica.</p><h3>Zona afectada</h3><p>Barrio Las Marías, en su totalidad.</p>
        <h3>Invertir en mantenimiento es mejorar el servicio</h3><p>mantenimiento periódico.</p>''')
        r=p.collect_one('ceb_bariloche',STAMP,fetcher=lambda u:article if 'corte-programado-11' in u else home)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1,r)
        self.assertIn('Las Marías',r['notices'][0]['zone_detail'])
        self.assertNotIn('Invertir',r['notices'][0]['zone_detail'])

    def test_ceb_two_day_mismatch_not_alert(self):
        home='<a href="/corte-programado-11-11-2026/">Corte Programado 11/11/2026</a>'
        article=('''<h1>Corte Programado 11/11/2026</h1><p>El viernes 13 de noviembre,
        de 09:30 a 11:30 hs., se realizará un corte programado de energía eléctrica.</p>
        <p>Zona afectada: Barrio Las Marías, en su totalidad. Invertir en mantenimiento.</p>''')
        r=p.collect_one('ceb_bariloche',STAMP,fetcher=lambda u:article if 'corte-programado-11' in u else home)
        self.assertFalse(r['notices'])

    def test_scpl_www_failure_uses_only_official_apex(self):
        def f(url):
            if url=='https://www.scpl.coop/': raise OSError('down')
            return '<p>No hay noticias</p>'
        r=p.collect_one('scpl_comodoro',STAMP,fetcher=f)
        self.assertEqual(r['source_url'],'https://scpl.coop/')
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['source_attempts'][0]['error_type'],'OSError')
        self.assertNotIn('down',str(r))

    def test_scpl_same_host_protection_on_alt(self):
        def f(url):
            if url=='https://www.scpl.coop/': raise ValueError('down')
            return '<a href="https://malicious.example/index.php/site/ver-nota?id=9">CORTE PROGRAMADO DE ENERGÍA</a>'
        r=p.collect_one('scpl_comodoro',STAMP,fetcher=f)
        self.assertEqual(r.get('article_links_seen'),0)

    def test_servicoop_no_water_as_electricity(self):
        html=('<h1>Corte programado de agua</h1><p>noviembre 10, 2026</p>'
              '<p>Este miércoles 11 de noviembre, desde las 09:00 hasta las 12:00 horas. '
              'La falta de servicio afectará a los usuarios de Barrio Norte, calle 3 a 15. '
              'Desconecte los aparatos eléctricos</p>')
        self.assertEqual(p._parse_servicoop_article_v530(html,NOW,'https://web.servicoop.com/test/')[1],0)

    def test_servicoop_complete_future_electric_notice(self):
        home='<a href="/trabajos-en-subestacion/">Mantenimiento de subestación en zona norte</a>'
        article=('''<h1>Mantenimiento de subestación</h1><p>noviembre 10, 2026</p>
        <p>Informamos que este miércoles 11 de noviembre, desde las 09:00 hasta las 12:00 horas,
        se interrumpirá el suministro de energía para obras de mejora. La falta de servicio afectará
        a los usuarios residentes en Barrio Norte, desde las calles 12 a 20 y Av. Libertad.
        Desconecte los aparatos eléctricos que puedan dañarse.</p>''')
        r=p.collect_one('servicoop_puerto_madryn',STAMP,
              fetcher=lambda u:article if 'trabajos-en-subestacion' in u else home)
        self.assertEqual(r['status'],'ok',r)
        self.assertEqual(len(r['notices']),1,r)
        self.assertIn('Barrio Norte',r['notices'][0]['zone_detail'])

    def test_servicoop_old_notice_stale(self):
        home='<a href="/trabajos-en-subestacion/">Mantenimiento de subestación en zona norte</a>'
        article=('''<h1>Mantenimiento de subestación</h1><p>octubre 16, 2026</p>
        <p>Este sábado 17 de octubre, desde las 09:00 hasta las 12:00 horas,
        se interrumpirá el suministro eléctrico. La falta de servicio afectará a los usuarios residentes
        en Barrio Norte, desde las calles 12 a 20 y Av. Libertad.
        Desconecte los aparatos eléctricos.</p>''')
        r=p.collect_one('servicoop_puerto_madryn',STAMP,
              fetcher=lambda u:article if 'trabajos-en-subestacion' in u else home)
        self.assertEqual(r['status'],'stale',r)
        self.assertFalse(r['notices'])

    def test_servicoop_ignores_water_navigation(self):
        article=('''<nav>AGUA POTABLE - ENERGÍA ELÉCTRICA - Cortes</nav>
        <article><h1>Mantenimiento subestación</h1><p>noviembre 10, 2026</p>
        <p>El miércoles 11 de noviembre, desde las 09:00 hasta las 12:00 horas,
        se interrumpirá el suministro eléctrico. La falta de servicio afectará a los usuarios
        residentes en Barrio Norte y calles 25 de Mayo y San Martín entre dos avenidas.
        Desconecte los aparatos eléctricos.</p></article>''')
        _,n,_=p._parse_servicoop_article_v530(article,NOW,'https://web.servicoop.com/noticia/')
        self.assertEqual(n,1)

    def test_servicoop_publication_conflicting_date(self):
        html=('''<h1>Mantenimiento subestación</h1><p>noviembre 10, 2026</p>
                <p>Este lunes 21 de diciembre, desde las 09:00 hasta las 12:00 horas,
                se interrumpirá el suministro eléctrico. La falta de servicio afectará a los usuarios
                residentes en Barrio Norte, desde las calles 12 a 20 y Av. Libertad. Desconecte los aparatos.</p>''')
        self.assertFalse(p._parse_servicoop_article_v530(html,NOW,'https://web.servicoop.com/test/')[0])

if __name__ == '__main__': unittest.main()

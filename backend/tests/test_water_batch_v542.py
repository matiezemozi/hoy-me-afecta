"""Conservative public AySA news notices, separate from account lookup."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP='2026-11-14T17:00:00Z'
INDEX='''<html><body>
<a href="/usuarios/Novedades/2026/11/inspeccion_rios_subterraneos_oeste">Programa de Inspección de Ríos Subterráneos en el Oeste del AMBA 12 de noviembre de 2026</a>
<a href="https://evil.test/usuarios/Novedades/2026/11/inspeccion_rios_subterraneos_oeste">Interrupción del agua</a>
<a href="/usuarios/Novedades/2026/11/noche_museos">La Noche de los Museos</a>
<a href="/usuarios/Novedades/2026/11/inspeccion_rios_subterraneos_oeste">Programa de Inspección de Ríos Subterráneos en el Oeste del AMBA</a>
</body></html>'''
ARTICLE_URL='https://www.aysa.com.ar/usuarios/Novedades/2026/11/inspeccion_rios_subterraneos_oeste'
ARTICLE='''<html><body><nav><a href="/usuarios/interrupcion_servicio">Interrupcion de servicio</a></nav>
<div>12 de noviembre de 2026</div>
<h1>AySA inspeccionara el rio subterraneo del oeste</h1>
<p>Estas acciones modificarán la operatividad de distintas estaciones elevadoras del AMBA y permitirán mejorar la calidad de la red.</p>
<p>Como consecuencia, podría haber una afectación en el normal funcionamiento del servicio en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza.</p>
<p>También se ejecutan tareas en la planta de Tigre, que fortalece el abastecimiento de la red.</p>
<h3>Atención Comercial</h3><p>Lunes a Viernes de 8 a 18 hs.</p>
</body></html>'''

class AysaPublicNewsTests(unittest.TestCase):
    def test_ten_channels_in_total(self):
        self.assertGreaterEqual(len(w.SOURCES),10)
    def test_news_revision_and_isolation_from_account_lookup(self):
        self.assertIn('Novedades',w.SOURCES['aysa_public_bulletins_amba'][2])
        self.assertEqual(w.SOURCES['aysa_public_bulletins_amba'][0],'AySA')
        self.assertIn('interrupcion_servicio',w.SOURCES['aysa_amba'][2])
    def test_public_news_names_only_affected_cities(self):
        notes,pub=w._aysa_news_article(ARTICLE,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual(pub.isoformat(),'2026-11-12')
        self.assertEqual({n['locality_hint'] for n in notes},{'Moron','Hurlingham','Merlo','La Matanza'})
        self.assertNotIn('Tigre',{n['locality_hint'] for n in notes})
        self.assertTrue(all(n['notification_allowed'] is False for n in notes))
        self.assertTrue(all(n['status']=='publication_only_not_live' for n in notes))
        self.assertTrue(all(n.get('scheduled_start') is None for n in notes))
    def test_real_official_style_regional_notice_no_inferred_borough(self):
        phrase=('Como consecuencia de esta situacion, podria registrarse baja presion y/o falta de agua '
                'en algunas zonas de los partidos de Tigre, San Fernando, San Martin, Vicente Lopez y parte de San Isidro '
                'en el conurbano bonaerense; y barrios del centro y norte de la Ciudad de Buenos Aires.')
        html=ARTICLE.replace('Como consecuencia, podría haber una afectación en el normal funcionamiento del servicio en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza.',phrase)
        news,_=w._aysa_news_article(html,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual({n['locality_hint'] for n in news},{'Tigre','San Fernando','San Martin','Vicente Lopez','San Isidro'})
        self.assertNotIn('Recoleta',{n['locality_hint'] for n in news})
        self.assertNotIn('Pilar',{n['locality_hint'] for n in news})
    def test_broad_caba_area_is_not_recoleta_or_pilar(self):
        broad=ARTICLE.replace('en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza',
                              'en algunos barrios del centro y norte de la Ciudad de Buenos Aires')
        notices,_=w._aysa_news_article(broad,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual(notices,[])
    def test_exact_recoleta_named_is_a_borough_not_a_whole_caba(self):
        specific=ARTICLE.replace('en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza',
                                 'en algunos barrios de Recoleta')
        notices,_=w._aysa_news_article(specific,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual(len(notices),1)
        self.assertEqual(notices[0]['province'],'CABA')
        self.assertEqual(notices[0]['locality_hint'],'Recoleta')
    def test_barrio_without_de_still_precisely_matched(self):
        specific=ARTICLE.replace('en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza',
                                 'en el barrio Recoleta')
        notices,_=w._aysa_news_article(specific,ARTICLE_URL,w.checked_instant(STAMP))
        self.assertEqual([x['locality_hint'] for x in notices],['Recoleta'])
    def test_old_index_skips_article_calls_and_is_marked_stale(self):
        old='<a href="/usuarios/Novedades/2026/10/trabajos_agua">Trabajos de mantenimiento de agua 20 de octubre de 2026</a>'
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES['aysa_public_bulletins_amba'][2]:return old
            raise AssertionError('No se deberia visitar un articulo antiguo')
        source=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=fetch)
        self.assertEqual(source['status'],'stale')
        self.assertEqual(len(calls),1)
    def test_index_excludes_future_article(self):
        future='<a href="/usuarios/Novedades/2026/11/trabajos_agua">Trabajos de agua 20 de noviembre de 2026</a>'
        calls=[]
        source=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=lambda url: calls.append(url) or future)
        self.assertEqual(len(calls),1)
        self.assertFalse(source['notices'])
    def test_no_notification_for_negative_impact(self):
        negative=ARTICLE.replace('podría haber una afectación en el normal funcionamiento del servicio en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza',
                                 'no se verá afectado el servicio en algunos barrios de Recoleta')
        self.assertEqual(w._aysa_news_article(negative,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_recovery_headline_excluded(self):
        recovered=ARTICLE.replace('AySA inspeccionara el rio subterraneo del oeste','AySA finalizo reparaciones y normalizo el servicio')
        self.assertEqual(w._aysa_news_article(recovered,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_old_news_excluded(self):
        old=ARTICLE.replace('12 de noviembre de 2026','02 de noviembre de 2026')
        self.assertEqual(w._aysa_news_article(old,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_future_news_excluded(self):
        future=ARTICLE.replace('12 de noviembre de 2026','18 de noviembre de 2026')
        self.assertEqual(w._aysa_news_article(future,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_missing_publication_date_excluded(self):
        no_date=ARTICLE.replace('12 de noviembre de 2026','sin fecha')
        self.assertEqual(w._aysa_news_article(no_date,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_mere_article_about_plant_without_effect_excluded(self):
        text=ARTICLE.replace('podría haber una afectación en el normal funcionamiento del servicio en algunas localidades de Morón, Hurlingham, Merlo y zona norte de La Matanza',
                             'se reforzará el servicio en algunas localidades de Morón, Hurlingham, Merlo y La Matanza')
        self.assertEqual(w._aysa_news_article(text,ARTICLE_URL,w.checked_instant(STAMP))[0],[])
    def test_only_official_news_links_and_no_account(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==w.SOURCES['aysa_public_bulletins_amba'][2]:return INDEX
            if url==ARTICLE_URL:return ARTICLE
            raise AssertionError('Untrusted URL: '+url)
        result=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=fetch)
        self.assertEqual(calls,[w.SOURCES['aysa_public_bulletins_amba'][2],ARTICLE_URL])
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['parser_revision'],'AYSA-NEWS-v5.42')
        self.assertEqual(len(result['notices']),4)
        self.assertTrue(all(x['notification_allowed'] is False for x in result['notices']))
        self.assertTrue(result['account_lookup_required_for_address'])
    def test_broken_article_does_not_invent_notifications(self):
        result=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=lambda url: INDEX if url.endswith('/Novedades') else (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(result['status'],'unverified')
        self.assertFalse(result['notices'])
        self.assertEqual(result['source_attempts'][0]['error_type'],'TimeoutError')
    def test_missing_index_does_not_claim_normal_service(self):
        result=w.collect_one('aysa_public_bulletins_amba',STAMP,fetcher=lambda _: (_ for _ in ()).throw(ConnectionError()))
        self.assertEqual(result['status'],'unverified')
        self.assertFalse(result['notices'])
    def test_merge_has_ten_sources_and_keeps_disabled(self):
        result=w.collect_water(STAMP,fetcher=lambda _: '<h1>Ningun aviso</h1>')
        self.assertGreaterEqual(len(result['sources']),10)
        self.assertFalse(result['notifications_enabled'])
        self.assertFalse(result['android_display_enabled'])
        self.assertTrue(all(source['notifications_enabled'] is False for source in result['sources'].values()))

if __name__=='__main__':unittest.main()

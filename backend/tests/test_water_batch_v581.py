"""v5.81: precise future SCPL hours + honest public-source audit."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import water_notices as w

STAMP = '2026-11-24T21:04:46Z'
URL = 'https://scpl.coop/index.php/site/ver-nota?id=2935'
TITLE = 'Interrupción en el suministro de agua en barrios de Comodoro Rivadavia'
REPORT = ('Mañana, miércoles 25 de noviembre, desde las 00:00hs. y hasta las 18:00hs., '
          'se interrumpe el suministro de agua en los siguientes barrios: Ceferino, Las Flores, '
          'La Floresta, parte del San Martín y parte de Jorge Newbery; por la puesta en marcha '
          'de una nueva reguladora de presión que alimenta a dichos sectores.')

def article(body=REPORT, title=TITLE, pub='24-11-2026'):
    return f'<html><body><h1>{title}</h1><div>{pub}</div><p>{body}</p></body></html>'

class SCPLHoursV581(unittest.TestCase):
    def read(self, text=REPORT, now=STAMP, headline=TITLE):
        return w._scpl_article(article(text,headline),URL,w.checked_instant(now),date(2026,11,24))

    def test_exact_observed_scpl_hours_are_structured(self):
        note,pub,reason=self.read()
        self.assertEqual(reason,'parsed')
        self.assertEqual(pub,date(2026,11,24))
        self.assertEqual(note['scheduled_date'],'2026-11-25')
        self.assertEqual(note['scheduled_start'],'2026-11-25T00:00:00-03:00')
        self.assertEqual(note['scheduled_end'],'2026-11-25T18:00:00-03:00')
        self.assertEqual(note['time_precision'],'start_and_end_published')
        self.assertEqual(note['kind'],'planned_water_service_impact')
        self.assertEqual(note['status'],'scheduled_not_confirmed')
        self.assertFalse(note['notification_allowed'])
        self.assertEqual(note['area_precision'],'barrios_o_zonas_segun_comunicado_no_toda_la_ciudad')

    def test_same_event_day_retains_published_hours_without_live_claim(self):
        note,_,_=self.read(now='2026-11-25T17:30:00Z')
        self.assertEqual(note['scheduled_date'],'2026-11-25')
        self.assertIn('no acredita',note['message'])

    def test_elapsed_event_not_represented_as_current(self):
        note,_,why=self.read(now='2026-11-26T14:00:00Z')
        self.assertIsNone(note)
        self.assertEqual(why,'event_date_already_passed')

    def test_day_must_match_real_calendar(self):
        changed=REPORT.replace('miércoles 25','martes 25')
        note,_,_=self.read(changed)
        self.assertEqual(note['kind'],'water_service_bulletin')
        self.assertNotIn('scheduled_date',note)
        self.assertIsNone(note['scheduled_start'])

    def test_must_have_explicit_month(self):
        note,_,_=self.read(REPORT.replace('miércoles 25 de noviembre','miércoles 25'))
        self.assertEqual(note['kind'],'water_service_bulletin')

    def test_undated_hours_are_not_believed(self):
        note,_,_=self.read(REPORT.replace('Mañana, miércoles 25 de noviembre, ','Mañana, '))
        self.assertIsNone(note.get('scheduled_start'))

    def test_office_hours_do_not_become_water_interruption(self):
        fake=('Mañana, miércoles 25 de noviembre, desde las 00:00hs. y hasta las 18:00hs., '
              'se atiende al público en las oficinas. Se interrumpe el suministro de agua en ciertos sectores.')
        note,_,_=self.read(fake)
        self.assertIsNone(note['scheduled_start'])

    def test_electricity_only_not_water(self):
        fake=REPORT.replace('suministro de agua','suministro de electricidad')
        note,_,reason=self.read(fake)
        self.assertIsNone(note)
        self.assertEqual(reason,'no_explicit_water_impact')

    def test_start_after_end_discarded(self):
        bad=REPORT.replace('00:00hs. y hasta las 18:00hs.','19:00hs. y hasta las 18:00hs.')
        note,_,_=self.read(bad)
        self.assertIsNone(note['scheduled_start'])

    def test_25_hour_invalid(self):
        bad=REPORT.replace('00:00hs.','25:00hs.')
        note,_,_=self.read(bad)
        self.assertIsNone(note['scheduled_start'])

    def test_multiple_intervals_ambiguous(self):
        note,_,_=self.read(REPORT+' '+REPORT)
        self.assertIsNone(note['scheduled_start'])

    def test_cancelled_not_returned(self):
        note,_,reason=self.read(REPORT+' Se suspende el corte.')
        self.assertIsNone(note)
        self.assertEqual(reason,'cancelled_or_restored_announcement')

    def test_article_publication_must_agree_with_index(self):
        note,_,reason=w._scpl_article(article(pub='23-11-2026'),URL,
                                      w.checked_instant(STAMP),date(2026,11,24))
        self.assertIsNone(note)
        self.assertEqual(reason,'index_article_date_mismatch')

    def test_one_request_for_article_and_one_for_index(self):
        index=f'<a href="{URL}">{TITLE}</a><p>24-11-2026</p>'
        calls=[]
        def fetch(url):
            calls.append(url)
            if 'ver-seccion' in url:return index
            if url==URL:return article()
            raise AssertionError(url)
        result=w.collect_one('scpl_comodoro_chubut',STAMP,fetch)
        self.assertEqual(calls.count(URL),1)
        self.assertEqual(result['parser_revision'],'SCPL-DATED-SCHEDULES-v5.81')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['notices'][0]['scheduled_date'],'2026-11-25')

class HonestHealthV581(unittest.TestCase):
    def test_readable_article_index_not_called_unreadable(self):
        results={'jujuy':{'status':'unverified','notices':[],
                    'article_links_seen':10,'articles_checked':6},
                 'edos':{'status':'unverified','notices':[],
                         'article_links_seen':3,'articles_checked':3}}
        health=w.source_health_summary(results)
        self.assertEqual(set(health['readable_sources_without_accepted_bulletins']),{'jujuy','edos'})
        self.assertEqual(health['unverified_without_readable_index'],[])

    def test_page_read_flag_is_valid_index_evidence(self):
        health=w.source_health_summary({'cat':{'status':'unverified','notices':[],
                                               'page_read':True}})
        self.assertEqual(health['readable_sources_without_accepted_bulletins'],['cat'])

    def test_account_lookup_not_public_bulletin_index(self):
        health=w.source_health_summary({'aysa':{'status':'unverified','notices':[],
                    'access_mode':'account_required','coverage_kind':'address_account_lookup_only',
                    'portal_reachable':True}})
        self.assertEqual(health['account_only_sources_without_public_status'],['aysa'])
        self.assertEqual(health['readable_sources_without_accepted_bulletins'],[])
        self.assertEqual(health['unverified_without_readable_index'],[])

    def test_403_and_url_errors_still_visible_as_blocked(self):
        source={'status':'unverified','notices':[], 'index_attempts':[
            {'result':'fetch_or_parse_error','http_status':403}]}
        health=w.source_health_summary({'santa':source})
        self.assertEqual(health['all_index_requests_rejected_http_403'],['santa'])
        self.assertEqual(health['unverified_without_readable_index'],['santa'])

    def test_reproduces_real_v580_source_coverage(self):
        # Public-index reading and access-account-only are distinct categories.
        results={
            'absa':{'status':'ok','notices':[{'notification_allowed':False}]},
            'jujuy':{'status':'unverified','notices':[],'articles_checked':6,'article_links_seen':10},
            'cat':{'status':'unverified','notices':[],'page_read':True},
            'aysa':{'status':'unverified','notices':[],'access_mode':'account_required'},
            'chaco':{'status':'unverified','notices':[],'index_attempts':[{
                'result':'fetch_or_parse_error','error_type':'URLError'}]}}
        health=w.source_health_summary(results)
        self.assertEqual(health['configured_sources'],5)
        self.assertEqual(health['accepted_public_bulletins'],1)
        self.assertEqual(health['sources_with_accepted_bulletins'],['absa'])
        self.assertEqual(health['account_only_sources_without_public_status'],['aysa'])
        self.assertEqual(health['all_index_requests_failed_url_error'],['chaco'])

    def test_collect_water_does_not_enable_notifications(self):
        report=w.collect_water(STAMP,lambda _: '<html></html>')
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])
        self.assertEqual(report['source_health']['configured_sources'],30)
        self.assertTrue(all(n['notification_allowed'] is False for n in report['notices']))

if __name__=='__main__': unittest.main()

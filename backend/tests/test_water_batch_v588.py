"""v5.88 conservative recovery metadata and fail-closed report contract."""
import copy
import json
import unittest
from datetime import date
from unittest.mock import patch
import backend.water_notices as w

NOW = w.checked_instant('2026-11-28T13:23:37Z')
STAMP = '2026-11-28T13:23:37Z'
URL = ('https://aguasrionegrinas.com/general-roca-interrumpido-el-servicio-de-agua-potable-'
       'por-un-corte-de-energia-electrica-en-la-planta-stefenelli/')
HEAD = ('General Roca: interrumpido el servicio de agua potable por un corte '
        'de energia electrica en la planta Stefenelli')
CONTEXT = ('Aguas Rionegrinas informa que, debido a un corte de energia electrica '
           'realizado por EDERSA, se encuentra afectada la Planta Potabilizadora '
           'Stefenelli. Por esta situacion, se encuentra interrumpido el servicio '
           'de agua potable en la zona baja de General Roca.')
FORECAST = ('Segun informaron, el suministro electrico se restablecera a las '
            '11:30 horas y, paulatinamente, el agua potable ira normalizando '
            'su presion. Se preve que a las 15:30 horas quede normalizada '
            'la prestacion del servicio en esa zona de General Roca.')

def roca_html(published='28 noviembre, 2026', para1=CONTEXT, para2=FORECAST):
    return ('<h1>'+HEAD+'</h1><div>'+published+'</div>'
            '<p>'+para1+'</p><p>'+para2+'</p>')


def good_note(**changes):
    note=w.mk_notice('Aguas Rionegrinas','Rio Negro','General Roca',URL,
                     'water_service_bulletin','publication_only_not_live',
                     CONTEXT+' '+FORECAST,published_on='2026-11-28',
                     scheduled_start=None,scheduled_end=None)
    note.update(changes)
    return note

class V588RecoveryForecasts(unittest.TestCase):
    def helper(self, paras=None, date_value=date(2026,11,28)):
        return w._arsa_same_day_recovery_forecasts(
            paras if paras is not None else [CONTEXT,FORECAST],date_value)

    def test_recognizes_both_official_forecasts(self):
        f=self.helper()
        self.assertEqual(f['reported_electricity_recovery_forecast'],'2026-11-28T11:30-03:00')
        self.assertEqual(f['reported_pressure_normalization_estimate'],'2026-11-28T15:30-03:00')
        self.assertTrue(f['reported_forecasts_do_not_confirm_water_recovery'])

    def test_realistic_article_integration(self):
        notes,published=w._arsa_article(roca_html(),URL,NOW)
        self.assertEqual(published,date(2026,11,28))
        self.assertEqual(len(notes),1)
        self.assertEqual(notes[0]['reported_pressure_normalization_estimate'],
                         '2026-11-28T15:30-03:00')
        self.assertEqual(notes[0]['reported_electricity_recovery_forecast'],
                         '2026-11-28T11:30-03:00')

    def test_article_remains_publication_only_not_live(self):
        n=w._arsa_article(roca_html(),URL,NOW)[0][0]
        self.assertEqual(n['status'],'publication_only_not_live')
        self.assertEqual(n['kind'],'water_service_bulletin')
        self.assertFalse(n['notification_allowed'])
        self.assertIsNone(n['scheduled_end'])
        self.assertIsNone(n['scheduled_start'])

    def test_published_history_keeps_reported_date(self):
        result=self.helper(date_value=date(2026,11,28))
        self.assertIn('2026-11-28',result['reported_pressure_normalization_estimate'])

    def test_article_id_not_regenerated(self):
        n=w._arsa_article(roca_html(),URL,NOW)[0][0]
        self.assertEqual(n['id'],good_note()['id'])

    def test_forecast_only_does_not_prove_water_interruption(self):
        self.assertEqual(self.helper([FORECAST]),{})

    def test_power_cut_alone_does_not_prove_water_interruption(self):
        self.assertEqual(self.helper([CONTEXT.replace('se encuentra interrumpido el servicio de agua potable',
                                                      'no habra interrupcion del servicio de agua potable'),FORECAST]),{})

    def test_no_electric_reference(self):
        self.assertEqual(self.helper([CONTEXT.replace('corte de energia electrica','reparaciones'),FORECAST]),{})

    def test_no_power_forecast(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('se restablecera','se verificara')]),{})

    def test_no_water_forecast(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('Se preve','El personal informo')]),{})

    def test_office_schedule_not_borrowed(self):
        self.assertEqual(self.helper([CONTEXT,'El horario de atencion en la oficina es ' + FORECAST]),{})

    def test_unrelated_paragraphs_not_spliced(self):
        e='Segun informaron, el suministro electrico se restablecera a las 11:30 horas.'
        a='Se preve que a las 15:30 horas quede normalizada la prestacion del servicio.'
        self.assertEqual(self.helper([CONTEXT,e,a]),{})

    def test_impact_many_paragraphs_before_not_borrowed(self):
        self.assertEqual(self.helper([CONTEXT,'Una noticia ajena sobre inversiones generales.',FORECAST]),{})

    def test_no_yesterday_day_guess(self):
        self.assertEqual(self.helper([CONTEXT+' Ayer hubo trabajos.',FORECAST]),{})

    def test_no_tomorrow_day_guess(self):
        self.assertEqual(self.helper([CONTEXT+' Manana se retomaran tareas.',FORECAST]),{})

    def test_invalid_power_clock(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('11:30','25:30')]),{})

    def test_invalid_water_clock(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('15:30','15:60')]),{})

    def test_reversed_forecast_times_rejected(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('11:30','19:30')]),{})

    def test_twelve_hour_bound(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST.replace('11:30','02:30')]),{})

    def test_duplicated_power_forecast_rejected(self):
        p=FORECAST+' El suministro electrico se restablecera a las 12:00 horas.'
        self.assertEqual(self.helper([CONTEXT,p]),{})

    def test_duplicated_water_forecast_rejected(self):
        p=FORECAST+' Se preve que a las 16:00 horas quede normalizada la prestacion del servicio.'
        self.assertEqual(self.helper([CONTEXT,p]),{})

    def test_two_similar_paragraphs_rejected_as_ambiguous(self):
        self.assertEqual(self.helper([CONTEXT,FORECAST,CONTEXT,FORECAST]),{})

    def test_article_with_missing_date_not_promoted(self):
        self.assertEqual(w._arsa_article(roca_html(published=''),URL,NOW)[0],[])

    def test_old_article_not_promoted(self):
        self.assertEqual(w._arsa_article(roca_html(published='18 noviembre, 2026'),URL,NOW)[0],[])

    def test_power_does_not_equal_water_recovery(self):
        forecast=self.helper()
        self.assertNotEqual(forecast['reported_electricity_recovery_forecast'],
                            forecast['reported_pressure_normalization_estimate'])

class V588SafeNoticeContract(unittest.TestCase):
    def accepted(self, note=..., stamp=STAMP):
        return w._validate_water_notice(note if note is not ... else good_note(),
                                         w.checked_instant(stamp))

    def test_valid_realistic_notice_unchanged(self):
        n=good_note()
        self.assertIs(self.accepted(n)[0],n)
        self.assertIsNone(self.accepted(n)[1])

    def test_non_object_fail_closed(self):
        for item in (None,[],3,'text'):
            with self.subTest(item=item):
                self.assertEqual(self.accepted(item)[1],'not_an_object')

    def test_notification_permission_must_be_exactly_false(self):
        for flag in (True,1,0,None,'false'):
            with self.subTest(flag=flag):
                self.assertIsNone(self.accepted(good_note(notification_allowed=flag))[0])

    def test_electric_category_rejected(self):
        self.assertIsNone(self.accepted(good_note(category='electricidad'))[0])

    def test_country_confusion_rejected(self):
        self.assertIsNone(self.accepted(good_note(country='Uruguay'))[0])

    def test_unknown_status_rejected(self):
        self.assertIsNone(self.accepted(good_note(status='active_now'))[0])

    def test_unknown_kind_rejected(self):
        self.assertIsNone(self.accepted(good_note(kind='confirmed_outage'))[0])

    def test_bad_id_rejected(self):
        self.assertIsNone(self.accepted(good_note(id='agua-one'))[0])

    def test_missing_locality_rejected(self):
        self.assertIsNone(self.accepted(good_note(locality_hint=''))[0])

    def test_missing_detail_rejected(self):
        self.assertIsNone(self.accepted(good_note(zone_detail='corte'))[0])

    def test_http_source_rejected(self):
        self.assertIsNone(self.accepted(good_note(source_url='http://site.example/news'))[0])

    def test_bad_ipv6_source_rejected_without_exception(self):
        self.assertIsNone(self.accepted(good_note(source_url='https://[bad'))[0])

    def test_missing_publication_date_rejected(self):
        note=good_note();del note['published_on']
        self.assertEqual(self.accepted(note)[1],'invalid_publication_date')

    def test_future_publication_rejected(self):
        self.assertEqual(self.accepted(good_note(published_on='2026-12-01'))[1],
                         'future_publication_date')

    def test_invalid_scheduled_date_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_date='2026-11-31'))[1],
                         'invalid_event_datetime')

    def test_invalid_clock_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_start='2026-11-28T25:00-03:00'))[1],
                         'invalid_event_datetime')

    def test_time_without_timezone_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_start='2026-11-28T11:30'))[1],
                         'event_datetime_without_timezone')

    def test_end_without_start_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_end='2026-11-28T18:00-03:00'))[1],
                         'end_without_start')

    def test_inverted_start_end_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_start='2026-11-28T18:00-03:00',
                                                 scheduled_end='2026-11-28T10:00-03:00'))[1],
                         'inverted_event_interval')

    def test_event_date_conflict_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_date='2026-11-27',
                                                 scheduled_start='2026-11-28T10:00-03:00'))[1],
                         'event_day_conflicts_with_start')

    def test_far_future_schedule_rejected(self):
        self.assertEqual(self.accepted(good_note(scheduled_date='2026-12-28'))[1],
                         'event_too_far_in_future')

    def test_planned_impact_requires_date(self):
        self.assertEqual(self.accepted(good_note(status='scheduled_not_confirmed'))[1],
                         'planned_impact_without_event_date')

    def test_future_plan_retained(self):
        x=good_note(status='scheduled_not_confirmed',scheduled_date='2026-11-29')
        self.assertEqual(self.accepted(x)[0]['status'],'scheduled_not_confirmed')

    def test_past_planned_day_downgraded_without_normal_claim(self):
        x=good_note(status='scheduled_not_confirmed',scheduled_date='2026-11-27')
        got,err=self.accepted(x)
        self.assertIsNone(err)
        self.assertEqual(got['status'],'publication_only_not_live')
        self.assertTrue(got['reported_schedule_already_elapsed'])
        self.assertNotIn('normalizado',got['message'])
        self.assertEqual(x['status'],'scheduled_not_confirmed')

    def test_ended_interval_downgraded_at_same_day(self):
        x=good_note(status='scheduled_not_confirmed',scheduled_date='2026-11-28',
                    scheduled_start='2026-11-28T08:00-03:00',
                    scheduled_end='2026-11-28T09:00-03:00')
        self.assertEqual(self.accepted(x)[0]['status'],'publication_only_not_live')

    def test_pending_interval_keeps_status(self):
        x=good_note(status='scheduled_not_confirmed',scheduled_date='2026-11-28',
                    scheduled_start='2026-11-28T11:00-03:00',
                    scheduled_end='2026-11-28T18:00-03:00')
        self.assertEqual(self.accepted(x)[0]['status'],'scheduled_not_confirmed')

    def test_source_result_invalid_shape_isolated(self):
        for payload in (None,42,{'status':'ok'}, {'notices':'incorrect'}):
            with self.subTest(payload=payload):
                result=w._safe_source_result('aguas_rionegrinas_arsa',payload,STAMP)
                self.assertEqual(result['status'],'unverified')
                self.assertEqual(result['notices'],[])
                self.assertEqual(result['notices_rejected_by_contract'],1)

    def test_source_result_drop_unsafe_keep_safe(self):
        ok=good_note()
        bad=good_note(notification_allowed=True,id='agua-abcdef123456789012')
        result=w._safe_source_result('aguas_rionegrinas_arsa',
                 {'status':'ok','notices':[ok,bad],'message':'Noticias verificadas'},STAMP)
        self.assertEqual(result['notices'],[ok])
        self.assertEqual(result['notices_rejected_by_contract'],1)
        self.assertEqual(result['status'],'ok')

    def test_source_result_duplicate_notice_id_removed(self):
        n=good_note()
        r=w._safe_source_result('aguas_rionegrinas_arsa',
                 {'status':'ok','notices':[n,copy.deepcopy(n)]},STAMP)
        self.assertEqual(len(r['notices']),1)
        self.assertIn('duplicate_notice_id',r['contract_rejection_reasons'])

    def test_all_invalid_makes_source_unverified(self):
        r=w._safe_source_result('aguas_rionegrinas_arsa',
                {'status':'ok','notices':[good_note(notification_allowed=True)]},STAMP)
        self.assertEqual(r['status'],'unverified')
        self.assertEqual(r['notices'],[])

    def test_health_diagnostics_include_contract_drops(self):
        r=w._safe_source_result('aguas_rionegrinas_arsa',
                {'status':'ok','notices':[good_note(),good_note(notification_allowed=True)]},STAMP)
        health=w.source_health_summary({'arsa':r})
        self.assertEqual(health['source_notice_contract_rejections'],{'arsa':1})
        self.assertEqual(health['accepted_public_bulletins'],1)

    def test_latest_report_sample_retained(self):
        # Enough of the user's 28 Nov feed to ensure the new gate never
        # drops dated, publication-only notices or estimated timestamps.
        n=good_note(reported_pressure_normalization_estimate='2026-11-28T15:30-03:00')
        r=w._safe_source_result('aguas_rionegrinas_arsa',
                {'status':'ok','notices':[n]},STAMP)
        self.assertEqual(r['notices'],[n])
        self.assertNotIn('notices_rejected_by_contract',r)

    def test_thirty_sources_survive_single_malformed_collector(self):
        def one(key,checked_at,fetcher=None):
            if key=='agua_potable_jujuy_prensa':
                return {'status':'ok','notices':True}
            return w._result(key,checked_at)
        with patch.object(w,'collect_one',side_effect=one):
            report=w.collect_water(STAMP,fetcher=lambda _:'')
        self.assertEqual(len(report['sources']),30)
        self.assertEqual(report['notices'],[])
        self.assertEqual(report['source_health']['source_notice_contract_rejections'],
                         {'agua_potable_jujuy_prensa':1})
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])

    def test_mixed_good_bad_collector_never_enables_push(self):
        def one(key,checked_at,fetcher=None):
            r=w._result(key,checked_at)
            if key=='aguas_rionegrinas_arsa':
                r.update(status='ok',notices=[good_note(), good_note(notification_allowed=True)])
            return r
        with patch.object(w,'collect_one',side_effect=one):
            report=w.collect_water(STAMP,fetcher=lambda _:'')
        self.assertEqual(len(report['notices']),1)
        self.assertFalse(report['notices'][0]['notification_allowed'])
        self.assertFalse(report['notifications_enabled'])
        self.assertFalse(report['android_display_enabled'])

    def test_unhashable_kind_and_status_are_rejected_individually(self):
        for value in ([],{},['planned_water_service_impact']):
            with self.subTest(value=value):
                got,reason=self.accepted(good_note(kind=value))
                self.assertIsNone(got)
                self.assertEqual(reason,'unknown_water_notice_classification')
                got,reason=self.accepted(good_note(status=value))
                self.assertIsNone(got)
                self.assertEqual(reason,'unknown_water_notice_classification')

    def test_historical_scpl_interval_kept_as_publication_not_live(self):
        item=w.mk_notice('SCPL Comodoro Rivadavia','Chubut','Comodoro Rivadavia',
                         'https://scpl.coop/index.php/site/ver-nota?id=2935',
                         'planned_water_service_impact','scheduled_not_confirmed',
                         'El corte programado de agua fue anunciado para el 25 de noviembre.',
                         published_on='2026-11-24',scheduled_date='2026-11-25',
                         scheduled_start='2026-11-25T00:00:00-03:00',
                         scheduled_end='2026-11-25T18:00:00-03:00')
        accepted,reason=self.accepted(item)
        self.assertIsNone(reason)
        self.assertEqual(accepted['status'],'publication_only_not_live')
        self.assertEqual(accepted['scheduled_end'],'2026-11-25T18:00:00-03:00')
        self.assertTrue(accepted['reported_schedule_already_elapsed'])

    def test_source_with_bad_classification_keeps_its_other_notices(self):
        good=good_note()
        bad=good_note(id='agua-1234567890abcdef12',kind={})
        r=w._safe_source_result('aguas_rionegrinas_arsa',
                                {'status':'ok','notices':[good,bad]},STAMP)
        self.assertEqual(r['notices'],[good])
        self.assertEqual(r['notices_rejected_by_contract'],1)

    def test_original_30_source_ids_unchanged(self):
        self.assertEqual(len(w.SOURCES),30)
        self.assertIn('agua_potable_jujuy_prensa',w.SOURCES)
        self.assertIn('aguas_rionegrinas_arsa',w.SOURCES)

if __name__=='__main__':
    unittest.main()

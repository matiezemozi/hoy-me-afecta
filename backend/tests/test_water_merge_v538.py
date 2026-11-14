"""v5.38 tests for safe and exact merging of water and electric reports."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import verify_water_merge as validator
import build_water_feed as generator

class MergeTests(unittest.TestCase):
    def setUp(self):
        self.power = {'schema_version':1, 'generated_at':'2026-11-13T21:00:00Z',
                      'alerts':[{'id':'event-enre','category':'electricidad','users_affected':8}],
                      'sources':{'edenor':{'status':'ok'}},
                      'provincial_electricity':{'epen':{'status':'ok'}},
                      'coverage':{'water':'manual_notices_only'}}
        self.notice={'id':'agua-123','category':'agua','country':'Argentina',
                     'notification_allowed':False,'locality_hint':'El Bolson',
                     'published_on':'2026-11-13','source_url':'https://aguasrionegrinas.com/novedad/'}
        self.water = {'schema_version':1,'category':'agua','country':'Argentina',
                      'generated_at':'2026-11-14T02:49:21Z','notifications_enabled':False,
                      'android_display_enabled':False,
                      'sources':{'arsa':{'status':'ok','notifications_enabled':False,
                                         'notices':[self.notice]}},'notices':[self.notice]}
        self.merged = deepcopy(self.power)
        self.merged['water_services'] = self.water

    def check(self):
        return validator.verify(self.power,self.merged,self.water)

    def fail(self, detail):
        with self.assertRaisesRegex(validator.WaterMergeError,detail): self.check()

    def test_valid(self):
        self.assertEqual(self.check()['water_notices'],1)

    def test_bad_water_copy(self):
        self.merged['water_services']=dict(self.water,notices=[])
        self.fail('difiere')

    def test_change_enre(self):
        self.merged['alerts'][0]['users_affected']=22
        self.fail('altero')

    def test_change_coverage(self):
        self.merged['coverage']['water']='automatic'
        self.fail('altero')

    def test_change_base_timestamp(self):
        self.merged['generated_at']='2026-11-14T02:49:21Z'
        self.fail('altero')

    def test_invalid_schema(self):
        self.water['schema_version']=4
        self.fail('Esquema de agua')

    def test_water_notifications_forbidden(self):
        self.water['notifications_enabled']=True
        self.fail('desactivados')

    def test_android_display_forbidden(self):
        self.water['android_display_enabled']=True
        self.fail('desactivados')

    def test_notice_notifications_forbidden(self):
        self.notice['notification_allowed']=True
        self.fail('notificacion')

    def test_duplicate_ids(self):
        self.water['notices']=[self.notice,deepcopy(self.notice)]
        self.fail('duplicado')

    def test_missing_source_records(self):
        self.water['sources']['arsa']['notices']=[]
        self.fail('no coinciden')

    def test_insecure_article_source(self):
        self.notice['source_url']='http://nonofficial.com'
        self.fail('HTTPS')

    def test_generator_output_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            old=folder/'before.json'; base=folder/'feed.json'; water=folder/'water_feed.json'
            old.write_text(json.dumps(self.power),encoding='utf-8')
            base.write_text(json.dumps(self.power),encoding='utf-8')
            generator.main(['--out',str(water),'--merge',str(base)],collector=lambda _:self.water)
            stats=validator.verify(json.loads(old.read_text()),json.loads(base.read_text()),json.loads(water.read_text()))
            self.assertEqual(stats['water_sources'],1)

    def test_unverified_source_can_have_no_notices(self):
        self.water['sources']['arsa']['status']='unverified'
        self.water['sources']['arsa']['notices']=[]
        self.water['notices']=[]
        self.assertEqual(self.check()['water_notices'],0)

if __name__ == '__main__': unittest.main()

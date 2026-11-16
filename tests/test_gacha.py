import copy
import hashlib
import json
import struct
import random
import tempfile
import unittest
from unittest.mock import Mock,patch

from game.model import ROOT
from game.storage import Store
from game.equipment import apply_equipment,definition,validate_equipment
from game.gacha import GachaReveal


class GachaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.store.profile['gold']=10000
        self.store.save_profile()

    def test_ten_draws_cost_1500_and_retry_is_identical(self):
        result=self.store.transact('gacha',{'count':10},'ten')
        self.assertEqual((result['count'],result['cost']),(10,1500))
        self.assertEqual(self.store.profile['gold'],8500)
        self.assertEqual(len({i['id'] for i in result['items']}),10)
        order=['common','rare','unique','legendary']
        self.assertEqual(result['highest_rarity'],max((definition(i)['rarity'] for i in result['items']),key=order.index))
        self.assertEqual(self.store.transact('gacha',{'count':10},'ten'),result)
        loaded=Store(self.temp.name)
        self.assertEqual(loaded.profile['items'],self.store.profile['items'])
        self.assertEqual(loaded.transact('gacha',{'count':10},'ten'),result)
        self.assertEqual(loaded.profile['gold'],8500)

    def test_ten_draws_use_the_same_distribution_as_ten_single_draws(self):
        bulk=copy.deepcopy(self.store.profile)
        singles=copy.deepcopy(bulk)
        apply_equipment(bulk,'gacha',{'count':10},random.Random(123),'bulk')
        rng=random.Random(123)
        for i in range(10):
            apply_equipment(singles,'gacha',{},rng,str(i))
        self.assertEqual([i['definition'] for i in bulk['items']],[i['definition'] for i in singles['items']])
        self.assertEqual(bulk['gold'],singles['gold'])

    def test_invalid_counts_or_insufficient_gold_never_partially_charge(self):
        for count in (0,2,11,True,'10',None):
            profile=copy.deepcopy(self.store.profile)
            before=copy.deepcopy(profile)
            with self.assertRaises(ValueError):
                apply_equipment(profile,'gacha',{'count':count},random.Random(1),'bad')
            self.assertEqual(profile,before)
        self.store.profile['gold']=1499
        before=copy.deepcopy(self.store.profile)
        with self.assertRaises(ValueError):
            self.store.transact('gacha',{'count':10},'poor')
        self.assertEqual(self.store.profile,before)
        self.assertFalse(self.store.pending)

    def test_save_failure_reopen_keeps_all_ten_results_and_single_charge(self):
        write=self.store.write
        def fail(name,value):
            if name=='profile.json':raise OSError('disk unavailable')
            write(name,value)
        with patch.object(self.store,'write',side_effect=fail):
            with self.assertRaises(OSError):
                self.store.transact('gacha',{'count':10},'retry')
        loaded=Store(self.temp.name)
        expected=copy.deepcopy(loaded.profile)
        apply_equipment(expected,'gacha',{'count':10},random.Random(loaded.pending['seed']),'retry')
        result=loaded.transact('gacha',{'count':10},'retry')
        self.assertEqual(loaded.profile['items'],expected['items'])
        self.assertEqual(loaded.profile['gold'],8500)
        self.assertEqual(len(result['items']),10)

    def test_cleanup_failure_after_commit_does_not_pay_twice(self):
        write=self.store.write
        def fail(name,value):
            if name=='pending_transaction.json' and value=={}:raise OSError('cleanup unavailable')
            write(name,value)
        with patch.object(self.store,'write',side_effect=fail):
            with self.assertRaises(OSError):
                self.store.transact('gacha',{'count':10},'committed')
        loaded=Store(self.temp.name)
        result=loaded.transact('gacha',{'count':10},'committed')
        self.assertEqual((loaded.profile['gold'],len(loaded.profile['items'])),(8500,10))
        self.assertFalse(loaded.pending)
        self.assertEqual(result,loaded.profile['transactions']['committed']['result'])

    def test_new_only_on_first_definition_and_confirmation_is_persistent(self):
        rng=Mock()
        rng.choices.return_value=['common']
        rng.choice.return_value='bell'
        profile=copy.deepcopy(self.store.profile)
        result=apply_equipment(profile,'gacha',{'count':10},rng,'common')
        self.assertEqual([i['is_new'] for i in result['items']],[True]+[False]*9)
        self.assertEqual(result['highest_rarity'],'common')
        self.store.profile=profile
        self.store.save_profile()
        key=profile['items'][0]['id']
        self.store.transact('mark_seen',{'item_id':key},'seen')
        self.assertFalse(Store(self.temp.name).profile['items'][0]['is_new'])
        self.assertTrue(result['items'][0]['is_new'])
        for i in list(self.store.profile['items']):
            self.store.transact('sell',{'item_id':i['id']},'sell-'+i['id'])
        later=apply_equipment(self.store.profile,'gacha',{},rng,'again')
        self.assertFalse(later['items'][0]['is_new'])

    def test_old_sold_equipment_history_is_not_new_again(self):
        rng=Mock()
        rng.choices.return_value=['common']
        rng.choice.return_value='bell'
        profile=copy.deepcopy(self.store.profile)
        profile['transactions']['legacy']={'operation':'gacha','result':{'message':'Common 방울 획득!'}}
        result=apply_equipment(profile,'gacha',{},rng,'later')
        self.assertFalse(result['items'][0]['is_new'])
        validate_equipment(profile)

    def test_new_state_save_validation(self):
        for history in (True,['unknown'],['bell_common','bell_common']):
            profile=copy.deepcopy(self.store.profile)
            profile['discovered_equipment']=history
            with self.assertRaises(ValueError):validate_equipment(profile)

    def test_reveal_is_one_finite_animation_for_the_highest_rarity(self):
        rng=Mock()
        rng.choices.side_effect=[[r] for r in ['common','rare','unique','common','legendary']*2]
        rng.choice.return_value='bell'
        result=apply_equipment(copy.deepcopy(self.store.profile),'gacha',{'count':10},rng,'ranks')
        reveal=GachaReveal(result)
        self.assertEqual(reveal.result['highest_rarity'],'legendary')
        self.assertFalse(reveal.ready)
        reveal.update(.9)
        self.assertFalse(reveal.ready)
        reveal.update(.2)
        self.assertTrue(reveal.ready)
        reveal.update(100)
        self.assertEqual(reveal.clock,reveal.DURATION)

    def test_opening_sheets_are_non_looping_and_match_png_files(self):
        root=ROOT/'output/nyangi_art_v6'
        manifest=json.loads((root/'assets_manifest.json').read_text())
        self.assertEqual(len(manifest['entries']),5)
        for spec in manifest['entries']:
            data=(root/'png'/spec['file']).read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',data[16:24]),(spec['width'],spec['height']))
            self.assertEqual(hashlib.sha256(data).hexdigest(),spec['sha256'])
            self.assertFalse(spec['loop'])
            if '/shop/' in spec['file']:
                self.assertEqual((spec['frames'],spec['fps'],spec['pivot']),(6,8,[96,176]))
        self.assertEqual({e.get('light') for e in manifest['entries'] if '/shop/' in e['file']},
                         {'white','green','purple','gold'})

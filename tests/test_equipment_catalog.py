import copy
import hashlib
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import Mock

from game.model import ROOT
from game.storage import Store
from game.equipment import RULES,DEFINITIONS,apply_equipment,definition,stat_value,validate_equipment,bonuses
from game.visuals import EQUIPMENT_ART


class EquipmentCatalogTests(unittest.TestCase):
    def test_exactly_20_types_and_80_definitions_with_bounded_growth(self):
        self.assertEqual(len(RULES['types']),20)
        self.assertEqual(len(DEFINITIONS),80)
        self.assertEqual(set(EQUIPMENT_ART.icons),set(RULES['types']))
        self.assertEqual(set(EQUIPMENT_ART.effects),set(RULES['rarities']))
        ranks=list(RULES['rarities'])
        for key,spec in RULES['types'].items():
            self.assertIn(spec['stat'],RULES['caps'])
            self.assertGreater(spec['base'],0)
            for lower,upper in zip(ranks,ranks[1:]):
                a=dict(definition=key+'_'+lower,enhancement=10,stacks=10)
                b=dict(definition=key+'_'+upper,enhancement=6,stacks=0)
                self.assertLessEqual(stat_value(a),stat_value(b))
        for key,value in {'bell':.08,'boots':.04,'ribbon':.02}.items():
            self.assertEqual(RULES['types'][key]['base'],value)

    def test_all_80_can_be_drawn_and_keep_existing_rarity_weights(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            profile=Store(folder).profile
            profile['gold']=100000
            rng=Mock()
            rng.choice.side_effect=list(RULES['types'])*4
            for rarity in RULES['rarities']:
                rng.choices.return_value=[rarity]
                for _ in RULES['types']:
                    apply_equipment(profile,'gacha',{},rng,str(len(profile['items'])))
            self.assertEqual({i['definition'] for i in profile['items']},set(DEFINITIONS))
            self.assertTrue(all(i['is_new'] for i in profile['items']))
            self.assertEqual(profile['gold'],88000)
            rng.choices.assert_called_with(list(RULES['rarities']),weights=[70,23,6,1])
            rng.choice.assert_called_with(list(RULES['types']))
            profile['unlocked_slots']=3
            profile['equipment_slots']=[i['id'] for i in profile['items'][-3:]]
            validate_equipment(profile)
            self.assertTrue(all(value<=RULES['caps'][key] for key,value in bonuses(profile).items()))

    def test_equipment_art_draws_correct_effect_before_its_shared_icon(self):
        art=Mock()
        item={'definition':'ninja_scroll_unique'}
        EQUIPMENT_ART.draw(art,item,200,300,.25,size=32)
        self.assertEqual([call.args[0] for call in art.sprite.call_args_list],
                         ['sprites/equipment_fx/unique.png','sprites/equipment/ninja_scroll.png'])
        self.assertEqual(art.sprite.call_args_list[0].args,( 'sprites/equipment_fx/unique.png',200,300,.25))
        self.assertEqual(art.sprite.call_args_list[0].kwargs,{'scale':.5})

    def test_20_icon_files_and_4_looping_effects_match_manifest(self):
        root=ROOT/'output/nyangi_art_v7'
        manifest=json.loads((root/'assets_manifest.json').read_text())
        entries=manifest['entries']
        self.assertEqual(len(entries),24)
        icons=[e for e in entries if '/equipment/' in e['file']]
        effects=[e for e in entries if '/equipment_fx/' in e['file']]
        self.assertEqual({e['type'] for e in icons},set(RULES['types']))
        self.assertEqual({e['rarity'] for e in effects},set(RULES['rarities']))
        for spec in entries:
            data=(root/'png'/spec['file']).read_bytes()
            self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',data[16:24]),(spec['width'],spec['height']))
            self.assertEqual(hashlib.sha256(data).hexdigest(),spec['sha256'])
        for spec in effects:
            self.assertTrue(spec['loop'])
            self.assertEqual((spec['frames'],spec['fps'],spec['pivot']),(6,8,[48,48]))
        self.assertEqual(len({e['sha256'] for e in icons}),20)

    def test_pre_expansion_pending_draw_uses_its_original_three_types(self):
        self.check_pending(None,['bell','boots','ribbon'])

    def test_pending_draw_keeps_its_explicit_type_pool(self):
        self.check_pending(['magic_book','moon_badge'],['magic_book','moon_badge'])

    def check_pending(self,saved_pool,expected_pool):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            store=Store(folder)
            store.profile['gold']=10000
            store.save_profile()
            seed=421
            fingerprint=hashlib.sha256(json.dumps(store.profile,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            journal=dict(id='old-request',operation='gacha',args={'count':10},seed=seed,base=fingerprint)
            if saved_pool is not None:journal['equipment_types']=saved_pool
            store.write('pending_transaction.json',journal)
            expected=copy.deepcopy(store.profile)
            apply_equipment(expected,'gacha',{'count':10},random.Random(seed),'old-request',gacha_pool=expected_pool)
            loaded=Store(folder)
            result=loaded.transact('gacha',{'count':10},'old-request')
            self.assertEqual(loaded.profile['items'],expected['items'])
            self.assertEqual(loaded.profile['gold'],8500)
            self.assertEqual(loaded.transact('gacha',{'count':10},'old-request'),result)
            self.assertTrue({definition(i)['type'] for i in loaded.profile['items']}<=set(expected_pool))

    def test_old_equipped_items_and_progress_load_unchanged(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            store=Store(folder)
            store.profile['items']=[dict(id=kind,definition=kind+'_rare',enhancement=3,stacks=4,locked=True)
                                    for kind in ('bell','boots','ribbon')]
            store.profile['unlocked_slots']=3
            store.profile['equipment_slots']=['bell','boots','ribbon']
            store.save_profile()
            loaded=Store(folder)
            self.assertEqual(loaded.profile['items'],store.profile['items'])
            self.assertEqual(loaded.profile['equipment_slots'],['bell','boots','ribbon'])

    def test_invalid_frozen_type_pool_does_not_change_profile(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            profile=Store(folder).profile
            profile['gold']=10000
            before=copy.deepcopy(profile)
            for pool in ([],['unknown'],['bell','bell'],'bell'):
                with self.assertRaises(ValueError):
                    apply_equipment(profile,'gacha',{},random.Random(1),'bad',gacha_pool=pool)
                self.assertEqual(profile,before)

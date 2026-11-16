import copy
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock, patch
from game.model import ROOT, World, Enemy, Projectile
from game.storage import Store
from game.equipment import RULES, apply_equipment, bonuses, stat_value, enhancement_offer, validate_equipment


def item(key,definition='bell_common',enhancement=0,stacks=0,locked=False):
    return dict(id=key,definition=definition,enhancement=enhancement,stacks=stacks,locked=locked)


class EquipmentTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.store.profile['gold']=100000
        self.store.save_profile()

    def test_gacha_costs_150_and_duplicate_request_returns_same_item(self):
        result=self.store.transact('gacha',{},'gacha-one')
        self.assertEqual(self.store.profile['gold'],99850)
        self.assertEqual(self.store.transact('gacha',{},'gacha-one'),result)
        self.assertEqual(len(self.store.profile['items']),1)
        self.assertEqual(Store(self.temp.name).profile['items'],self.store.profile['items'])

    def test_gacha_probabilities_do_not_change_with_inventory_or_max_stacks(self):
        a=copy.deepcopy(self.store.profile);b=copy.deepcopy(a)
        b['items']=[item('max','bell_legendary',10,10)]
        for seed in range(100):
            x=copy.deepcopy(a);y=copy.deepcopy(b)
            apply_equipment(x,'gacha',{},random.Random(seed),'draw')
            apply_equipment(y,'gacha',{},random.Random(seed),'draw')
            self.assertEqual(x['items'][-1]['definition'],y['items'][-1]['definition'])

    def test_random_result_survives_failed_save_and_process_reopen(self):
        write=self.store.write
        def fail(name,value):
            if name=='profile.json':raise OSError('disk full')
            write(name,value)
        with patch.object(self.store,'write',side_effect=fail):
            with self.assertRaises(OSError):self.store.transact('gacha',{},'draw-failed')
        loaded=Store(self.temp.name)
        seed=loaded.pending['seed']
        expected=copy.deepcopy(loaded.profile)
        apply_equipment(expected,'gacha',{},random.Random(seed),'draw-failed')
        loaded.transact('gacha',{},'draw-failed')
        self.assertEqual(loaded.profile['items'],expected['items'])
        self.assertEqual(loaded.profile['gold'],99850)

    def test_enhancement_failure_keeps_level_but_costs_gold_and_success_increases_once(self):
        profile=copy.deepcopy(self.store.profile)
        profile['items']=[item('x','bell_legendary',9)]
        cost,chance=enhancement_offer(profile['items'][0])
        before=profile['gold']
        failed=apply_equipment(profile,'enhance',{'item_id':'x'},Mock(random=lambda:1.),'failure')
        self.assertFalse(failed['success'])
        self.assertEqual(profile['items'][0]['enhancement'],9)
        self.assertEqual(profile['gold'],before-cost)
        apply_equipment(profile,'enhance',{'item_id':'x'},Mock(random=lambda:0.),'success')
        self.assertEqual(profile['items'][0]['enhancement'],10)
        with self.assertRaises(ValueError):apply_equipment(profile,'enhance',{'item_id':'x'},random.Random(),'over')

    def test_rarity_cost_chance_return_and_tier_balance(self):
        for kind in RULES['types']:
            entries=[item('x',kind+'_'+rarity) for rarity in RULES['rarities']]
            self.assertEqual(len(set(enhancement_offer(e) for e in entries)),4)
            for lower,upper in zip(entries,entries[1:]):
                lower.update(enhancement=10,stacks=10)
                upper.update(enhancement=6)
                self.assertLessEqual(stat_value(lower),stat_value(upper))
        for step in range(9):
            cost,chance=enhancement_offer(item('x',enhancement=step))
            next_cost,next_chance=enhancement_offer(item('x',enhancement=step+1))
            self.assertGreater(next_cost,cost)
            self.assertLess(next_chance,chance)

    def test_stack_preserves_target_growth_consumes_plain_material_only(self):
        self.store.profile['items']=[item('target',enhancement=7),item('material')]
        self.store.transact('stack',{'item_id':'target','material_id':'material'},'stack')
        self.assertEqual(len(self.store.profile['items']),1)
        self.assertEqual((self.store.profile['items'][0]['enhancement'],self.store.profile['items'][0]['stacks']),(7,1))
        self.store.transact('stack',{'item_id':'target','material_id':'material'},'stack')
        self.assertEqual(self.store.profile['items'][0]['stacks'],1)

    def test_stack_rejects_locked_equipped_grown_different_or_self_material(self):
        for bad in (item('m',locked=True),item('m',enhancement=1),item('m',stacks=1),item('m','boots_common')):
            self.store.profile['items']=[item('target'),bad]
            before=copy.deepcopy(self.store.profile)
            with self.assertRaises(ValueError):self.store.transact('stack',{'item_id':'target','material_id':'m'})
            self.assertEqual(before,self.store.profile)
        self.store.profile['items']=[item('target'),item('m')]
        self.store.profile['equipment_slots'][0]='m'
        with self.assertRaises(ValueError):self.store.transact('stack',{'item_id':'target','material_id':'m'})
        with self.assertRaises(ValueError):self.store.transact('stack',{'item_id':'target','material_id':'target'})

    def test_slot_unlock_and_shared_equipment_reject_duplicate_equipping(self):
        self.store.profile['items']=[item('x')]
        with self.assertRaises(ValueError):self.store.transact('unlock_slot',{'slot':2})
        self.store.transact('unlock_slot',{'slot':1},'slot-2')
        self.store.transact('unlock_slot',{'slot':2},'slot-3')
        self.assertEqual(self.store.profile['gold'],99250)
        self.store.transact('equip',{'slot':0,'item_id':'x'},'equip-1')
        self.store.transact('equip',{'slot':2,'item_id':'x'},'equip-2')
        self.assertEqual(self.store.profile['equipment_slots'],[None,None,'x'])
        self.assertAlmostEqual(bonuses(self.store.profile)['damage'],.08)
        self.store.transact('buy_character',{'character_id':'black'},'shared-black')
        self.store.select_character('black')
        self.assertEqual(self.store.profile['equipment_slots'],[None,None,'x'])
        self.assertAlmostEqual(bonuses(self.store.profile)['damage'],.08)

    def test_sell_fixed_rarity_price_and_protects_locked_or_equipped(self):
        self.store.profile['items']=[item('common'),item('legendary','bell_legendary',10,10)]
        before=self.store.profile['gold']
        self.store.transact('sell',{'item_id':'common'},'sale-1')
        self.store.transact('sell',{'item_id':'legendary'},'sale-2')
        self.assertEqual(self.store.profile['gold'],before+45+75)
        for locked,equipped in ((True,False),(False,True)):
            self.store.profile['items']=[item('protected',locked=locked)]
            self.store.profile['equipment_slots'][0]='protected' if equipped else None
            with self.assertRaises(ValueError):self.store.transact('sell',{'item_id':'protected'})

    def test_equipment_caps_snapshot_and_real_projectile_damage(self):
        world=World(bonuses={'damage':99,'move_speed':99,'dash_reduction':99})
        self.assertEqual(world.bonuses,RULES['caps'])
        self.assertAlmostEqual(world.dash_cooldown,.875)
        w=World(bonuses={'damage':.2})
        w.next_spawn_at=float('inf');w.update_enemy=lambda e,dt:None
        enemy=Enemy(580,w.cat.y+26,species='squirrel')
        w.enemies=[enemy];w.aim=(enemy.x,enemy.y)
        w.shoot();w.update(.2)
        self.assertAlmostEqual(enemy.hp,1.3)

    def test_invalid_inventory_is_rejected_before_save(self):
        self.store.profile['items']=[item('duplicate'),item('duplicate')]
        with self.assertRaises(ValueError):self.store.save_profile()
        self.store.profile['items']=[item('a')]
        self.store.profile['equipment_slots'][2]='a'
        with self.assertRaises(ValueError):self.store.save_profile()

    def test_fractional_damage_does_not_leave_an_invisible_hp_residue(self):
        enemy=Enemy(100,100,species='bee')
        for _ in range(9):self.assertFalse(enemy.damage(.1))
        self.assertTrue(enemy.damage(.1))
        self.assertEqual(enemy.hp,0)
        self.assertFalse(enemy.damage(.1))

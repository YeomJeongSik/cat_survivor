import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from game.model import ROOT, World, Enemy
from game.storage import Store


class ProgressionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.store.profile['gold']=2000
        self.store.save_profile()

    def test_character_purchase_owns_without_equipping_and_deduplicates(self):
        result=self.store.transact('buy_character',{'character_id':'black'},'buy-1')
        self.assertIn('black',self.store.profile['characters'])
        self.assertEqual(self.store.profile['selected_character_id'],'nabi')
        self.assertEqual(self.store.profile['gold'],1500)
        self.assertEqual(self.store.transact('buy_character',{'character_id':'black'},'buy-1'),result)
        with self.assertRaises(ValueError):self.store.transact('buy_character',{'character_id':'black'},'buy-2')
        self.store.select_character('black')
        self.assertEqual(Store(self.temp.name).profile['selected_character_id'],'black')

    def test_purchase_failure_journal_survives_reopen_and_retries_once(self):
        before=copy.deepcopy(self.store.profile)
        write=self.store.write
        def fail_profile(name,value):
            if name=='profile.json':raise OSError('disk full')
            write(name,value)
        with patch.object(self.store,'write',side_effect=fail_profile):
            with self.assertRaises(OSError):self.store.transact('buy_character',{'character_id':'black'},'retry-1')
        self.assertEqual(self.store.profile,before)
        loaded=Store(self.temp.name)
        self.assertEqual(loaded.pending['id'],'retry-1')
        with self.assertRaises(ValueError):loaded.select_character('nabi')
        loaded.transact('buy_character',{'character_id':'black'},'retry-1')
        self.assertEqual(loaded.profile['gold'],1500)
        self.assertFalse(loaded.pending)

    def test_melee_has_own_range_damage_and_does_not_create_projectiles(self):
        world=World(character_id='black')
        world.aim=(960,world.cat.y+26)
        world.enemies=[Enemy(world.cat.x+60,world.cat.y+26,species='squirrel'),
                       Enemy(world.cat.x-60,world.cat.y+26,species='bee'),
                       Enemy(world.cat.x+180,world.cat.y+26,species='bee')]
        world.shoot()
        self.assertEqual(world.enemies[0].hp,.5)
        self.assertEqual(world.enemies[1].hp,1)
        self.assertEqual(world.enemies[2].hp,1)
        self.assertFalse(world.projectiles)
        self.assertEqual(world.cat.ammo,4)
        world.shoot()
        self.assertEqual(world.enemies[0].hp,.5)

    def test_melee_special_spends_one_charge_hits_each_enemy_once_and_respects_burrow(self):
        world=World(character_id='black')
        world.cat.pierce_charges=1
        world.aim=(960,world.cat.y+26)
        world.enemies=[Enemy(world.cat.x+50,world.cat.y+26,species='squirrel'),
                       Enemy(world.cat.x+50,world.cat.y+26,species='snake')]
        world.shoot(True)
        self.assertFalse(world.enemies[0].alive)
        self.assertEqual(world.enemies[1].hp,2)
        self.assertEqual(world.cat.pierce_charges,0)
        reward=world.run_exp
        world.shoot(True)
        self.assertEqual(world.run_exp,reward)

    def test_achievements_use_settled_kills_and_claim_once(self):
        from test_rewards import dead_world
        world=dead_world()
        world.run_kills['bee']=3
        self.store.settle(world)
        self.store.settle(world)
        self.assertEqual(self.store.profile['stats']['kills'],3)
        before=self.store.profile['gold']
        args={'achievement_id':'first_hunt','character_id':'nabi'}
        self.store.transact('claim_achievement',args,'claim-1')
        self.store.transact('claim_achievement',args,'claim-1')
        self.assertEqual(self.store.profile['gold'],before+30)
        with self.assertRaises(ValueError):self.store.transact('claim_achievement',args,'claim-2')
        with self.assertRaises(ValueError):self.store.transact('claim_achievement',{'achievement_id':'hunter','character_id':'nabi'},'claim-3')

    def test_max_level_achievement_converts_exp_separately_from_results(self):
        self.store.profile['stats']['best_time']=180
        self.store.profile['characters']['nabi'].update(level=50,exp=0,skill_points=50)
        before=self.store.profile['gold']
        result=self.store.transact('claim_achievement',{'achievement_id':'survivor','character_id':'nabi'},'achievement-max')
        self.assertEqual((result['exp'],result['gold']),(0,75))
        self.assertEqual(self.store.profile['gold'],before+75)
        self.assertFalse(self.store.profile['settled_runs'])

    def test_abandoned_run_does_not_advance_achievements(self):
        world=World();world.run_kills['bee']=5;world.time=500
        world.finish_run()
        self.assertEqual(sum(world.run_kills.values()),0)
        with self.assertRaises(ValueError):self.store.settle(world)
        self.assertEqual(self.store.profile['stats']['kills'],0)

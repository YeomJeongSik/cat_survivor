import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from game.model import ROOT, World, DEATH_SECONDS, Enemy, Projectile
from game.rewards import RULES, level_cost, settle_run, bonus_percent
from game.storage import Store
from game.app import App, RESULT_SECONDS
from game.framework import scene_machine
from game.lobby import Lobby


def dead_world(exp=12, gold=8, seconds=60):
    world=World()
    world.time=seconds
    world.run_exp,world.run_gold=exp,gold
    world.cat.hp=0
    world.begin_death()
    world.update(DEATH_SECONDS+.01)
    return world


def headless_app(store, world):
    app=App.__new__(App)
    scene_machine(app)
    app.show_play()
    app.store,app.world=store,world
    app.lobby=Lobby()
    app.dragging=None
    app.audio=Mock()
    app.ui_clock=app.result_clock=0.
    app.saved_result=False
    app.settlement=None
    app.keys=set()
    app.mouse=(0,0)
    app.error=''
    app.last_countdown=None
    app.controls_popup=app.exit_confirm=False
    app.buttons=[]
    return app


class RewardTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.folder.cleanup)
        self.store=Store(self.folder.name)

    def test_rewards_accumulate_once_per_kill_even_with_piercing_overlap(self):
        w=World();w.next_spawn_at=float('inf')
        w.update_enemy=lambda enemy,dt:None
        e=Enemy(200,200,species='bee',exp_reward=3,gold_reward=2)
        w.enemies=[e];w.projectiles=[Projectile(200,200,dx=0,dy=0,piercing=True)]
        for _ in range(10):w.tick(.01,set())
        self.assertEqual((w.run_exp,w.run_gold),(3,2))

    def test_bonus_boundaries_are_time_only_and_gold_starts_later(self):
        for kind in ('exp','gold'):
            for step in RULES[kind+'_bonuses']:
                self.assertLess(bonus_percent(step['seconds']-.01,kind),step['percent'])
                self.assertEqual(bonus_percent(step['seconds'],kind),step['percent'])
            self.assertEqual(bonus_percent(10**9,kind),150)
        self.assertEqual(bonus_percent(599.99,'exp'),100)
        self.assertEqual(bonus_percent(899.99,'gold'),100)
        w=dead_world(seconds=900)
        first=settle_run(self.store.profile,w)
        self.store.profile['characters']['nabi'].update(level=50,exp=0,skill_points=50)
        second=settle_run(self.store.profile,w)
        self.assertEqual((first['exp_percent'],first['gold_percent']),(second['exp_percent'],second['gold_percent']))

    def test_every_level_and_final_extra_point_are_awarded(self):
        w=dead_world(exp=sum(level_cost(level) for level in range(1,50)),gold=0)
        r=self.store.settle(w)
        self.assertEqual(r['character_after'],dict(level=50,exp=0,skill_points=50))
        self.assertEqual((r['applied_exp'],r['converted_gold']),(w.run_exp,0))

    def test_fractional_bonus_exp_is_kept_and_gold_is_floored(self):
        r=self.store.settle(dead_world(exp=1,gold=1,seconds=3600))
        self.assertEqual((r['character_after']['exp'],r['combat_gold']),(1.5,1))
        self.assertEqual(Store(self.folder.name).profile['characters']['nabi']['exp'],1.5)

    def test_overflow_is_combined_then_half_up_once_without_gold_bonus(self):
        self.store.profile['characters']['nabi'].update(level=50,exp=0,skill_points=50)
        r=self.store.settle(dead_world(exp=2,gold=0))
        self.assertEqual((r['applied_exp'],r['overflow_exp'],r['converted_gold']),(0,2,1))
        # One aggregate conversion: two 0.5-GOLD amounts must not become 2 GOLD.
        r=self.store.settle(dead_world(exp=1,gold=1,seconds=5400))
        self.assertEqual((r['overflow_exp'],r['converted_gold'],r['combat_gold'],r['gold_gained']),(1.5,1,1,2))

    def test_reaching_cap_uses_only_needed_exp_and_gives_two_points(self):
        self.store.profile['characters']['nabi'].update(level=49,exp=level_cost(49)-1,skill_points=48)
        r=self.store.settle(dead_world(exp=3,gold=0))
        self.assertEqual((r['applied_exp'],r['overflow_exp'],r['converted_gold']),(1,2,1))
        self.assertEqual(r['character_after'],dict(level=50,exp=0,skill_points=50))

    def test_duplicate_run_replays_same_receipt_after_reopen(self):
        w=dead_world(exp=250,gold=20)
        original=self.store.settle(w)
        before=copy.deepcopy(self.store.profile)
        self.assertEqual(self.store.settle(w),original)
        self.assertEqual(self.store.profile,before)
        reopened=Store(self.folder.name)
        self.assertEqual(reopened.settle(w),original)
        self.assertEqual(reopened.profile,before)
        w.run_gold+=1
        with self.assertRaises(ValueError):reopened.settle(w)
        self.assertEqual(reopened.profile,before)

    def test_failed_replace_keeps_disk_and_memory_then_retry_pays_once(self):
        self.store.save_profile()
        path=Path(self.folder.name)/'profile.json'
        before_disk=path.read_bytes()
        before_memory=copy.deepcopy(self.store.profile)
        w=dead_world()
        with patch('game.storage.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.store.settle(w)
        self.assertEqual(self.store.profile,before_memory)
        self.assertEqual(path.read_bytes(),before_disk)
        result=self.store.settle(w)
        self.store.settle(w)
        self.assertEqual(self.store.profile['gold'],result['gold_gained'])

    def test_uncertain_write_outcome_does_not_double_pay_on_retry_or_reopen(self):
        w=dead_world()
        write=self.store.write
        def wrote_then_failed(name,value):
            write(name,value)
            raise OSError('lost acknowledgement')
        with patch.object(self.store,'write',side_effect=wrote_then_failed):
            with self.assertRaises(OSError):self.store.settle(w)
        self.assertEqual(self.store.profile['gold'],0)
        reopened=Store(self.folder.name)
        receipt=reopened.settle(w)
        self.assertEqual(reopened.profile['gold'],receipt['gold_gained'])
        self.store.settle(w)
        self.assertEqual(self.store.profile['gold'],receipt['gold_gained'])

    def test_abandon_and_unfinished_runs_cannot_pay(self):
        w=World();w.run_exp=100;w.run_gold=100
        with self.assertRaises(ValueError):self.store.settle(w)
        w.finish_run()
        self.assertEqual((w.run_exp,w.run_gold,w.end_reason),(0,0,'abandoned'))
        with self.assertRaises(ValueError):self.store.settle(w)
        self.assertEqual(self.store.profile['gold'],0)

    def test_v1_migration_preserves_original_and_ignores_old_ranking(self):
        folder=Path(self.folder.name)
        original=b'{"version":1,"equipped_skin_id":"bee_golden","bgm_volume":30}'
        (folder/'profile.json').write_bytes(original)
        (folder/'leaderboard.json').write_bytes(b'original historical ranking')
        s=Store(folder)
        self.assertEqual(s.profile['gold'],0)
        s.settle(dead_world())
        self.assertEqual((folder/'profile.v1-backup.json').read_bytes(),original)
        self.assertEqual((folder/'leaderboard.json').read_bytes(),b'original historical ranking')
        self.assertEqual(Store(folder).profile['version'],2)

    def test_future_and_invalid_financial_profile_are_not_overwritten(self):
        path=Path(self.folder.name)/'profile.json'
        for data in ({'version':99},{**self.store.profile,'gold':-1}):
            path.write_text(json.dumps(data),encoding='utf-8')
            before=path.read_bytes()
            with self.assertRaises(ValueError):Store(self.folder.name)
            self.assertEqual(path.read_bytes(),before)

    def test_ui_blocks_leaving_and_restart_until_save_then_skip_is_separate(self):
        app=headless_app(self.store,dead_world())
        original_id=app.world.run_id
        with patch.object(self.store,'write',side_effect=OSError('disk failure')):
            app.update(0)
        self.assertEqual(app.scene,'RESULT')
        self.assertFalse(app.saved_result)
        app.start();app.action('title',0)
        self.assertEqual((app.scene,app.world.run_id),('RESULT',original_id))
        app.action('retry_save',0)
        self.assertTrue(app.saved_result)
        app.start()
        self.assertEqual((app.scene,app.world.run_id,app.result_clock),('RESULT',original_id,RESULT_SECONDS))
        before=copy.deepcopy(self.store.profile)
        app.update(10)
        self.assertEqual(self.store.profile,before)
        app.start()
        self.assertEqual(app.scene,'PLAY')
        self.assertNotEqual(app.world.run_id,original_id)

    def test_confirm_exit_cancels_or_discards_without_touching_profile(self):
        w=World();w.run_exp=100;w.run_gold=30;w.pause()
        app=headless_app(self.store,w)
        before=copy.deepcopy(self.store.profile)
        app.action('exit_run',0)
        self.assertTrue(app.exit_confirm)
        app.action('resume',0)
        self.assertEqual(w.mode,'PAUSED')
        app.action('cancel_exit',0)
        self.assertEqual((app.scene,w.mode),('PLAY','PAUSED'))
        app.action('exit_run',0)
        app.action('confirm_exit',0)
        self.assertEqual((app.scene,w.end_reason,w.run_exp,w.run_gold),('LOBBY','abandoned',0,0))
        self.assertEqual(self.store.profile,before)


if __name__=='__main__':
    unittest.main()

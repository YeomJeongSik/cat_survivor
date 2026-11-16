import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game.characters import CHARACTERS
from game.model import ROOT, World
from game.rewards import initial_character
from game.storage import Store
from game.lobby import MENU, SLOTS, PANEL
from test_rewards import headless_app, dead_world


class LobbyTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT/'tests')
        self.addCleanup(self.folder.cleanup)
        self.store=Store(self.folder.name)

    def test_title_opens_lobby_without_starting_world_then_launch_is_explicit(self):
        app=headless_app(self.store,None)
        app.show_title()
        app.action('start',0)
        self.assertEqual(app.scene,'LOBBY')
        self.assertIsNone(app.world)
        app.action('start',0)
        self.assertEqual(app.scene,'PLAY')
        self.assertEqual(app.world.character_id,self.store.profile['selected_character_id'])

    def test_lobby_freezes_world_and_open_panels_block_start(self):
        world=World()
        app=headless_app(self.store,world)
        app.enter_lobby()
        app.update(20)
        self.assertEqual(world.time,0)
        for name in (*MENU,'settings','controls'):
            app.action(('lobby','open',name),0)
            self.assertEqual(app.lobby.panel,name)
            app.action('start',0)
            self.assertEqual(app.scene,'LOBBY')
            app.click(50,50)
            self.assertIsNone(app.lobby.panel)
            self.assertEqual(app.scene,'LOBBY')

    def test_return_requires_save_success_and_skips_animation_separately(self):
        world=dead_world(exp=240,gold=80)
        app=headless_app(self.store,world)
        with patch.object(self.store,'write',side_effect=OSError('disk failure')):
            app.update(0)
        app.enter_lobby()
        self.assertEqual(app.scene,'RESULT')
        app.action('retry_save',0)
        app.enter_lobby()
        self.assertEqual(app.scene,'RESULT')
        app.enter_lobby()
        self.assertEqual(app.scene,'LOBBY')
        self.assertEqual(self.store.profile['gold'],80)
        self.assertEqual(self.store.profile['characters']['nabi']['level'],3)

    def test_character_selection_is_owned_only_atomic_and_idempotent(self):
        for key in ('black_cat','missing',None,[]):
            with self.assertRaises(ValueError):self.store.select_character(key)
        with patch.dict(CHARACTERS,{'fixture':dict(CHARACTERS['nabi'])}):
            with self.assertRaises(ValueError):self.store.select_character('fixture')
            self.store.profile['characters']['fixture']=initial_character()
            before=copy.deepcopy(self.store.profile)
            with patch.object(self.store,'write',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):self.store.select_character('fixture')
            self.assertEqual(self.store.profile,before)
            self.store.select_character('fixture')
            self.assertEqual(Store(self.folder.name).profile['selected_character_id'],'fixture')
            with patch.object(self.store,'write',side_effect=AssertionError('redundant write')):
                self.store.select_character('fixture')

    def test_browse_does_not_equip_and_failed_selection_keeps_panel(self):
        app=headless_app(self.store,World())
        app.enter_lobby()
        app.lobby.open(app,'character')
        with patch.object(self.store,'select_character',side_effect=OSError('disk failure')):
            app.action(('lobby','select'),0)
        self.assertEqual(app.lobby.panel,'character')
        self.assertIn('disk failure',app.lobby.error)
        app.action(('lobby','select'),0)
        self.assertIsNone(app.lobby.panel)
        self.assertEqual(self.store.profile['selected_character_id'],'nabi')

    def test_closing_settings_finishes_drag_saves_and_clears_inputs(self):
        app=headless_app(self.store,World())
        app.enter_lobby()
        app.lobby.open(app,'settings')
        app.dragging=('bgm_volume',352)
        app.keys.add('shoot')
        app.store.profile['bgm_volume']=30
        app.lobby.close(app)
        self.assertIsNone(app.dragging)
        self.assertFalse(app.keys)
        self.assertEqual(Store(self.folder.name).profile['bgm_volume'],30)

    def test_old_v2_profile_gets_default_selection_without_touching_finances(self):
        self.store.save_profile()
        import json
        path=Path(self.folder.name)/'profile.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        data.pop('selected_character_id')
        data['gold']=321
        path.write_text(json.dumps(data),encoding='utf-8')
        loaded=Store(self.folder.name)
        self.assertEqual((loaded.profile['selected_character_id'],loaded.profile['gold']),('nabi',321))
        self.assertNotIn('selected_character_id',json.loads(path.read_text(encoding='utf-8')))
        loaded.save_profile()
        self.assertEqual(Store(self.folder.name).profile['gold'],321)

    def test_declared_rectangles_are_in_canvas_and_menu_buttons_do_not_overlap(self):
        rectangles=[rect for _,rect in MENU.values()]+SLOTS+[PANEL]
        for left,bottom,right,top in rectangles:
            self.assertTrue(0<=left<right<=960 and 0<=bottom<top<=640)
        menu=[rect for _,rect in MENU.values()]
        for first,second in zip(menu,menu[1:]):
            self.assertLessEqual(second[3],first[1])


if __name__=='__main__':
    unittest.main()

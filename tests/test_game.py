import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from transitions import Machine, MachineError
from game.model import ROOT, Cat, World, Enemy, Projectile, Item, WAVES, BALANCE, DEATH_SECONDS, wave_quota, segment_hit
from game.storage import Store
from game.app import fit_size, tile_segments, enemy_frame_state, KEY_BINDINGS, p


class RulesTest(unittest.TestCase):
    def test_images_keep_aspect_and_terrain_is_cropped_not_squashed(self):
        for source,box in (((192,224),(64,64)),((192,64),(290,48)),((768,512),(420,280))):
            width,height=fit_size(*source,*box)
            self.assertAlmostEqual(width/height,source[0]/source[1])
            self.assertLessEqual(width,box[0])
            self.assertLessEqual(height,box[1])
        for left,right,_ in BALANCE['surfaces']:
            segments=list(tile_segments(left,right))
            self.assertEqual(sum(width for _,width,_ in segments),right-left)
            self.assertEqual(segments[0],(left,32,'left'))
            self.assertEqual(segments[-1],(right-32,32,'right'))
            for (x,width,_),(next_x,_,_) in zip(segments,segments[1:]):
                self.assertEqual(x+width,next_x)
            self.assertTrue(all(0<width<=32 for _,width,_ in segments))

    def test_transitions_owns_entity_states(self):
        for actor in (Cat(0,80),Enemy(100,100),Projectile(0,100),Item(50,98)):
            self.assertIsInstance(actor.machine,Machine)
            self.assertFalse(actor.machine.auto_transitions)
        with self.assertRaises(ValueError):
            Enemy(100,100,species='bee',state='BURROW_MOVE')

    def test_illegal_transitions_do_not_change_state_or_clock(self):
        snake=Enemy(100,100,species='snake',clock=2)
        with self.assertRaises(MachineError):
            snake.enter('POP_UP')
        self.assertEqual((snake.state,snake.clock),('IDLE',2))
        snake.enter('CHARGE')
        self.assertEqual(snake.clock,0)
        snake.enter('POP_UP')
        snake.enter('HIT')
        snake.enter('DEAD')
        with self.assertRaises(MachineError):
            snake.enter('IDLE')
        cat=Cat(100,80)
        cat.enter('DEAD')
        with self.assertRaises(MachineError):
            cat.enter('MOVE')
        bandage=Item(100,98,kind='bandage')
        with self.assertRaises(AttributeError):
            bandage.enter('DESPAWN')

    def test_motion_transition_preserves_attack_timer(self):
        e=Enemy(100,400,clock=1.7,origin_y=400)
        e.enter('FLY',reset_clock=False)
        self.assertEqual(e.clock,1.7)
        e.enter('FLY',reset_clock=False)
        self.assertEqual(e.clock,1.7)
        e.enter('WARNING')
        self.assertEqual(e.clock,0)

    def test_world_transitions_are_terminal_and_countdown_is_required(self):
        w=World()
        self.assertIsInstance(w.machine,Machine)
        with self.assertRaises(MachineError):
            w.finish_resume()
        w.pause()
        w.pause()
        self.assertEqual((w.mode,w.countdown),('COUNTDOWN',3))
        w.update(3)
        self.assertEqual(w.mode,'PLAYING')
        w.finish_run()
        with self.assertRaises(MachineError):
            w.pause_play()

    def test_wave_table(self):
        self.assertEqual([w['index'] for w in WAVES],list(range(1,201)))
        self.assertEqual(sum(w['quota'] for w in WAVES),953)
        self.assertAlmostEqual(sum(w['duration'] for w in WAVES),1116.7)
        self.assertEqual([WAVES[i-1]['stage'] for i in (35,36,78,79,134,135,200)],[1,2,2,3,3,4,4])

    def test_left_ctrl_replaces_manual_aim_and_z(self):
        self.assertEqual(KEY_BINDINGS[p.SDLK_LCTRL],'shoot')
        self.assertEqual(KEY_BINDINGS[p.SDLK_DOWN],'down')
        for key in (p.SDLK_z,p.SDLK_RCTRL,p.SDLK_UP):
            self.assertNotIn(key,KEY_BINDINGS)

    def test_homing_selects_nearest_visible_damageable_enemy(self):
        w=World()
        underground=Enemy(w.cat.x+10,105,species='snake')
        dead=Enemy(w.cat.x+5,105,species='bee',state='DEAD')
        near=Enemy(w.cat.x-70,160,species='bee',state='TARGET_LOCK')
        far=Enemy(w.cat.x+180,180,species='bee')
        w.enemies=[underground,dead,far,near]
        w.cat.facing=1
        w.shoot()
        self.assertEqual(len(w.projectiles),1)
        bullet=w.projectiles[0]
        self.assertIs(bullet.target,near)
        self.assertLess(bullet.dx,0)
        self.assertEqual(w.cat.ammo,3)
        self.assertAlmostEqual(math.hypot(bullet.dx,bullet.dy),1)

    def test_homing_tracks_motion_and_retargets_dead_or_hidden_enemy(self):
        w=World()
        w.spawn_queue=[]
        w.cat.invincible=999
        target=Enemy(600,200,species='bee',state='TARGET_LOCK')
        other=Enemy(700,300,species='bee',state='TARGET_LOCK')
        w.enemies=[target,other]
        w.shoot()
        bullet=w.projectiles[0]
        self.assertIs(bullet.target,target)
        target.x=400
        w.tick(.01,set())
        self.assertLess(bullet.dx,0)
        target.enter('HIT')
        w.tick(.01,set())
        self.assertIs(bullet.target,other)
        snake=Enemy(600,200,species='snake',state='POP_UP')
        w.enemies=[snake,other]
        bullet.target=snake
        snake.enter('RETURN_UNDERGROUND')
        snake.enter('IDLE')
        w.tick(.01,set())
        self.assertIs(bullet.target,other)

    def test_no_target_keeps_ammo_and_no_target_in_flight_is_safe(self):
        w=World()
        w.spawn_queue=[]
        w.shoot()
        self.assertEqual((w.cat.ammo,len(w.projectiles)),(4,0))
        w.projectiles=[Projectile(100,300)]
        w.tick(.01,set())
        self.assertEqual(len(w.projectiles),1)
        self.assertIsNone(w.projectiles[0].target)

    def test_ammo_cap_is_four_including_pickups(self):
        w=World()
        self.assertEqual(w.cat.ammo,4)
        w.items=[Item(w.cat.x,w.cat.y+18)]
        w.tick(.01,set())
        self.assertEqual(w.cat.ammo,4)

    def test_enemy_species_hp_and_nonlethal_hits_preserve_ai(self):
        for species,required in (('magpie',3),('squirrel',2),('bee',1),('snake',2)):
            for grade in range(3):
                e=Enemy(200,200,species=species,grade=grade,state='POP_UP' if species=='snake' else 'IDLE',clock=.1)
                self.assertEqual((e.hp,e.max_hp),(required,required))
                state=e.state
                for hit in range(1,required+1):
                    killed=e.damage()
                    self.assertEqual(e.hp,required-hit)
                    self.assertEqual(killed,hit==required)
                    if hit<required:
                        self.assertTrue(e.alive)
                        self.assertEqual((e.state,e.clock),(state,.1))
                self.assertFalse(e.alive)
                self.assertEqual(e.state,'HIT')

    def test_projectile_consumed_on_nonlethal_hit_and_score_on_kill_only(self):
        w=World()
        w.spawn_queue=[]
        e=Enemy(200,180,species='squirrel',state='CROUCH_CHARGE')
        w.enemies=[e]
        for expected_hp in (1,0):
            w.events.clear()
            w.projectiles=[Projectile(170,180,target=e)]
            w.tick(.04,set())
            self.assertEqual(e.hp,expected_hp)
            self.assertFalse(w.projectiles)
            self.assertEqual(w.kill_score,10 if expected_hp==0 else 0)
            self.assertEqual(w.events.count('enemy_hit'),1)
            self.assertEqual(w.events.count('enemy_death'),int(expected_hp==0))

    def test_down_space_drops_through_only_the_current_platform(self):
        w=World()
        w.spawn_queue=[]
        c=w.cat
        c.x,c.y=400,300
        w.events.clear()
        w.jump({'down'})
        self.assertEqual((c.state,c.grounded,c.jumps_used),('FALL',False,1))
        self.assertNotIn('jump',w.events)
        w.update(.08,{'left'})
        self.assertLess(c.y,300)
        w.update(.45,{'left'})
        self.assertEqual(c.y,195)  # Catch the lower platform after moving over it.
        self.assertTrue(c.grounded)
        self.assertEqual(c.jumps_used,0)
        w.jump({'down'})
        w.update(.5)
        self.assertEqual(c.y,BALANCE['ground'])
        self.assertTrue(c.grounded)
        w.jump({'down'})
        self.assertEqual(c.state,'JUMP')
        self.assertGreater(c.vy,0)

    def test_drop_keeps_one_air_jump_and_is_blocked_while_paused(self):
        w=World()
        w.cat.x=200
        w.cat.y=195
        w.pause()
        w.jump({'down'})
        self.assertEqual((w.cat.y,w.cat.grounded),(195,True))
        w.pause()
        w.update(3)
        w.jump({'down'})
        w.jump()
        self.assertEqual((w.cat.state,w.cat.jumps_used),('JUMP',2))
        velocity=w.cat.vy
        w.jump()
        self.assertEqual(w.cat.vy,velocity)

    def test_each_enemy_attack_emits_one_species_sound_at_attack_start(self):
        for species,state in (('magpie','WARNING'),('squirrel','CROUCH_CHARGE'),
                              ('bee','TARGET_LOCK'),('snake','CHARGE')):
            w=World()
            w.events.clear()
            enemy=Enemy(250,200,species=species,state=state,clock=.79)
            w.update_enemy(enemy,.02)
            self.assertEqual(w.events,[species+'_attack'])
            w.update_enemy(enemy,.01)
            self.assertEqual(w.events,[species+'_attack'])

    def test_cat_jump_shot_and_hurt_sounds_follow_actual_actions(self):
        w=World()
        w.spawn_queue=[]
        w.events.clear()
        w.jump()
        w.jump()
        w.jump()
        self.assertEqual(w.events.count('jump'),2)
        w.enemies=[Enemy(600,200,species='bee',state='TARGET_LOCK')]
        w.shoot()
        w.shoot()
        self.assertEqual(w.events.count('shot'),1)
        w.cat.y=BALANCE['ground']
        w.cat.vy=0
        w.projectiles=[]
        w.enemies=[Enemy(w.cat.x,w.cat.y+24,species='bee',state='TARGET_LOCK',spawn_grace=0)]
        w.tick(.001,set())
        w.tick(.001,set())
        self.assertEqual(w.events.count('hurt'),1)

    def test_faster_original_spawn_schedule(self):
        self.assertEqual([wave_quota(WAVES[i-1]) for i in (1,36,79,135)],[3,4,5,6])
        self.assertEqual(sum(wave_quota(spec) for spec in WAVES),953)
        w=World()
        for number in (1,36,79,135):
            w.wave=number
            w.start_wave()
            times=[t for t,_ in w.spawn_queue]
            self.assertEqual(len(times),wave_quota(w.spec))
            self.assertAlmostEqual(times[0],.12)
            self.assertAlmostEqual(times[1]-times[0],.2)
            self.assertLess(times[-1],w.spec['duration'])

    def test_pause_and_countdown_freeze_everything(self):
        w=World(42)
        w.update(1)
        w.pause()
        before=copy.deepcopy((w.time,w.cat,w.enemies,w.items,w.wave_time,w.food_time,w.spawn_queue))
        w.update(20,{'right','shoot'})
        self.assertEqual(before,(w.time,w.cat,w.enemies,w.items,w.wave_time,w.food_time,w.spawn_queue))
        w.pause()
        w.update(2.9,{'right','shoot'})
        self.assertEqual(before,(w.time,w.cat,w.enemies,w.items,w.wave_time,w.food_time,w.spawn_queue))
        w.update(.2)
        self.assertEqual(w.mode,'PLAYING')
        self.assertEqual(w.time,before[0])

    def test_double_jump_dash_and_boundaries(self):
        w=World()
        w.jump()
        w.update(.1)
        velocity=w.cat.vy
        w.jump()
        self.assertGreater(w.cat.vy,velocity)
        self.assertEqual(w.cat.jumps_used,2)
        w.update(.02)
        velocity=w.cat.vy
        w.jump()
        self.assertEqual(w.cat.vy,velocity)
        w.dash({'right'})
        w.update(.1,{'right'})
        self.assertTrue(w.trails)
        w.cat.invincible=9999
        w.update(6,{'right'})
        self.assertLessEqual(w.cat.x,934)
        self.assertGreaterEqual(w.cat.y,BALANCE['ground'])
        self.assertEqual(w.cat.jumps_used,0)
        w.jump()
        self.assertEqual(w.cat.jumps_used,1)

    def test_magpie_wait_height_and_gradual_return(self):
        w=World()
        w.spawn_enemy('magpie')
        self.assertTrue(w.enemies)
        self.assertEqual(w.enemies[0].y,BALANCE['magpie_y'])
        for state in ('IDLE','FLY','WARNING'):
            e=Enemy(200,123,species='magpie',state=state,attack_dx=1,attack_dy=-1)
            w.update_enemy(e,.1)
            self.assertEqual(e.y,BALANCE['magpie_y'])
        self.assertLess(BALANCE['magpie_y']+32,541-16)
        e=Enemy(200,480,species='magpie',state='RUSH',attack_dy=-1,attack_length=260)
        for _ in range(8):
            w.update_enemy(e,.1)
        self.assertEqual(e.state,'RECOVER')
        low=e.y
        w.update_enemy(e,.1)
        self.assertAlmostEqual(e.y-low,BALANCE['magpie_return_speed']*.1)
        self.assertLess(e.y,BALANCE['magpie_y'])
        for _ in range(50):
            w.update_enemy(e,.1)
            if e.state=='IDLE':
                break
        self.assertEqual(e.y,BALANCE['magpie_y'])
        self.assertEqual(e.state,'IDLE')

    def test_magpie_parabola_returns_to_wait_height(self):
        w=World()
        e=Enemy(200,480,species='magpie',state='DIVE',arc_start_x=200,arc_end_x=700,arc_depth=300)
        w.update_enemy(e,BALANCE['magpie_arc_seconds']/2)
        self.assertAlmostEqual(e.y,180)
        self.assertAlmostEqual(e.x,450)
        w.update_enemy(e,BALANCE['magpie_arc_seconds']/2)
        self.assertEqual((e.state,e.y),('IDLE',480))

    def test_death_animation_finishes_before_game_over(self):
        w=World()
        w.spawn_queue=[]
        w.cat.hp=1
        w.enemies=[Enemy(w.cat.x,w.cat.y+24,species='bee',state='TARGET_LOCK',spawn_grace=0)]
        w.update(.01)
        self.assertEqual((w.mode,w.cat.state),('DYING','DEAD'))
        frozen=(w.time,w.wave_time,w.enemies[0].x,w.food_time)
        w.update(DEATH_SECONDS-.01,{'right','shoot'})
        self.assertEqual(w.mode,'DYING')
        self.assertEqual(frozen,(w.time,w.wave_time,w.enemies[0].x,w.food_time))
        w.update(.02)
        self.assertEqual(w.mode,'GAME_OVER')

    def test_dash_prevents_contact_damage_only_during_dash(self):
        w=World()
        w.spawn_queue=[]
        e=Enemy(w.cat.x,w.cat.y+24,species='bee',state='TARGET_LOCK',spawn_grace=0)
        w.enemies=[e]
        w.dash({'right'})
        for _ in range(17):
            e.x=w.cat.x+BALANCE['dash_speed']*.01
            w.tick(.01,set())
        self.assertEqual(w.cat.hp,3)
        self.assertGreater(w.cat.dash_left,0)
        e.x=w.cat.x+BALANCE['dash_speed']*.03
        w.tick(.03,set())
        self.assertEqual(w.cat.hp,2)

    def test_wave_clears_early_only_after_all_scheduled_spawns(self):
        w=World()
        w.enemies=[]
        w.update(.1)
        self.assertEqual(w.wave,1)
        w.spawn_queue=[]
        w.enemies=[Enemy(100,300,species='bee',state='TARGET_LOCK')]
        w.update(.01)
        self.assertEqual(w.wave,1)
        w.enemies[0].enter('HIT')
        w.update(.01)
        self.assertEqual((w.wave,w.completed),(2,1))
        self.assertLess(w.time,1)
        w.wave=200
        w.completed=199
        w.start_wave()
        w.spawn_queue=[]
        w.enemies=[Enemy(100,300,species='bee',state='HIT')]
        w.update(.01)
        self.assertEqual(w.mode,'CLEAR')
        self.assertIn('rainbow_clear',w.unlocked)

    def test_footstep_cadence_stops_while_paused(self):
        w=World()
        w.update(.5,{'right'})
        self.assertEqual(w.events.count('footstep'),2)
        w.pause()
        w.update(2,{'right'})
        self.assertEqual(w.events.count('footstep'),2)

    def test_siren_exactly_three_game_time_pulses(self):
        w=World()
        w.events.clear()
        w.update(.9)
        self.assertEqual(w.events.count('siren'),3)
        w.update(.4)
        self.assertEqual(w.events.count('siren'),3)
        w.pause()
        w.update(5)
        self.assertEqual(w.events.count('siren'),3)

    def test_swept_hit_only_nearest_enemy(self):
        w=World()
        w.spawn_queue=[]
        w.enemies=[Enemy(200,180,state='TARGET_LOCK',species='bee'),Enemy(200,180,state='TARGET_LOCK',species='bee')]
        w.projectiles=[Projectile(170,180,dx=1,dy=0)]
        w.tick(.1,set())
        self.assertEqual(sum(e.alive for e in w.enemies),1)
        self.assertEqual(len(w.projectiles),0)
        self.assertIsNotNone(segment_hit(0,0,1000,0,(400,-1,410,1)))
        self.assertIsNone(segment_hit(0,0,1000,0,(400,2,410,4)))

    def test_snake_underground_cannot_hit_or_be_hit(self):
        w=World()
        w.spawn_queue=[]
        w.enemies=[Enemy(w.cat.x,w.cat.y+24,species='snake')]
        w.projectiles=[Projectile(w.cat.x-40,w.cat.y+24)]
        w.tick(.05,set())
        self.assertEqual(w.cat.hp,3)
        self.assertTrue(w.enemies[0].alive)
        w.projectiles=[]
        w.enemies[0].enter('CHARGE')
        w.enemies[0].enter('POP_UP')
        w.enemies[0].spawn_grace=0
        w.enemies[0].x=w.cat.x
        w.tick(.001,set())
        self.assertEqual(w.cat.hp,2)

    def test_snake_charge_keeps_tail_only_until_attack(self):
        w=World()
        e=Enemy(w.cat.x,200,species='snake',state='CHARGE')
        w.update_enemy(e,.1)
        self.assertEqual((e.state,e.y),('CHARGE',BALANCE['ground']+22))
        self.assertEqual(enemy_frame_state(e),'idle')
        self.assertFalse(e.exposed)
        self.assertFalse(e.damage())
        self.assertEqual(e.hp,2)
        w.update_enemy(e,.51)
        self.assertEqual(e.state,'POP_UP')
        self.assertEqual(enemy_frame_state(e),'pop_up')
        w.update_enemy(e,.1)
        self.assertGreater(e.y,BALANCE['ground']+22)

    def test_caps_food_and_bandage(self):
        w=World()
        for _ in range(15):
            w.spawn_enemy('bee')
            w.spawn_food(4)
        self.assertLessEqual(sum(e.species=='bee' for e in w.enemies),3)
        self.assertLessEqual(sum(i.kind=='churu' for i in w.items),6)
        w.items=[Item(100,98,kind='bandage')]
        w.spawn_queue=[]
        w.cat.invincible=9999
        w.update(25)
        self.assertTrue(any(i.kind=='bandage' for i in w.items))
        w.cat.x=100
        w.update(.01)
        self.assertFalse(any(i.kind=='bandage' for i in w.items))
        self.assertEqual(w.cat.hp,3)

    def test_evolution_policy_stays_with_spawn(self):
        w=World()
        e=Enemy(200,400,evolution=11.99,max_grade=1)
        w.update_enemy(e,.02)
        self.assertEqual(e.grade,1)
        w.update_enemy(e,13)
        self.assertEqual(e.grade,1)

    def test_last_wave_waits_for_timer(self):
        w=World()
        w.wave=200
        w.completed=199
        w.start_wave()
        w.cat.invincible=9999
        w.update(4)
        self.assertNotIn('rainbow_clear',w.unlocked)
        w.update(.2)
        self.assertEqual(w.mode,'CLEAR')
        self.assertEqual(w.completed,200)
        self.assertIn('rainbow_clear',w.unlocked)

    def test_seed_reproducibility(self):
        a,b=World(17),World(17)
        a.update(3)
        b.update(3)
        self.assertEqual(a.enemies,b.enemies)
        self.assertEqual(a.items,b.items)

    def test_full_timeline_and_caps(self):
        w=World(17)
        w.cat.invincible=99999
        while w.mode=='PLAYING':
            w.update(.25)
            self.assertLessEqual(sum(e.alive for e in w.enemies),w.spec['cap'])
            self.assertLessEqual(sum(e.alive and e.species=='bee' for e in w.enemies),3)
        self.assertEqual(w.mode,'CLEAR')
        self.assertEqual(w.completed,200)
        self.assertAlmostEqual(w.time,1116.7,places=5)


class StorageTest(unittest.TestCase):
    def test_corrupt_save_preserved_and_volume_sanitized(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            path=Path(folder)/'profile.json'
            path.write_text('{broken',encoding='utf-8')
            s=Store(folder)
            s.save_profile()
            self.assertEqual(len(list(Path(folder).glob('profile.json.damaged-*'))),1)
            self.assertEqual(json.loads(path.read_text())['version'],1)
            s.profile['bgm_volume']=float('nan')
            path.write_text(json.dumps(s.profile),encoding='utf-8')
            self.assertEqual(Store(folder).profile['bgm_volume'],70)

    def test_clear_ranks_before_higher_uncleared_score(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            s=Store(folder)
            a=World(); a.kill_score=999999
            s.record(a)
            b=World(); b.clear_run()
            s.record(b)
            self.assertTrue(s.records[0]['cleared'])
            s.unlock({'bee_golden'})
            self.assertIn('bee_golden',Store(folder).profile['unlocked_skin_ids'])


if __name__=='__main__':
    unittest.main()

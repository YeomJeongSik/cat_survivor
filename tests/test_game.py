import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from transitions import Machine, MachineError
from game.model import ROOT, Cat, World, Enemy, Projectile, Item, BALANCE, DEATH_SECONDS, WORLD_WIDTH, segment_hit
from game.difficulty import SETTINGS, difficulty_at, monster_stats, validate_settings
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

    def test_difficulty_boundaries_and_initial_species_hp_order(self):
        validate_settings(SETTINGS)
        self.assertEqual(difficulty_at(29.99)['start'],0)
        self.assertEqual(difficulty_at(30)['start'],30)
        self.assertNotIn('bee',difficulty_at(0)['weights'])
        self.assertIn('bee',difficulty_at(30)['weights'])
        self.assertNotIn('snake',difficulty_at(59.99)['weights'])
        self.assertIn('snake',difficulty_at(60)['weights'])
        values=[monster_stats(k,difficulty_at(0))['max_hp'] for k in ('bee','magpie','snake','squirrel')]
        self.assertEqual(values,sorted(set(values)))
        self.assertTrue(all(isinstance(Enemy(0,100,species=k).hp,float) for k in SETTINGS['monsters']))
        for invalid in (-1,math.nan,math.inf):
            with self.assertRaises(ValueError):difficulty_at(invalid)

    def test_wasd_mapping_replaces_arrows_and_keyboard_fire(self):
        self.assertEqual(KEY_BINDINGS,{p.SDLK_a:'left',p.SDLK_d:'right',p.SDLK_w:'up',p.SDLK_s:'down'})
        for key in (p.SDLK_LEFT,p.SDLK_RIGHT,p.SDLK_DOWN,p.SDLK_UP,p.SDLK_z,p.SDLK_LCTRL):
            self.assertNotIn(key,KEY_BINDINGS)

    def test_mouse_vector_is_normalized_and_fixed_after_firing(self):
        w=World()
        w.next_spawn_at=math.inf
        w.aim=(w.cat.x+300,w.cat.y+26+400)
        w.shoot()
        bullet=w.projectiles[0]
        self.assertAlmostEqual(bullet.dx,.6)
        self.assertAlmostEqual(bullet.dy,.8)
        self.assertEqual(w.cat.ammo,3)
        start=(bullet.x,bullet.y)
        w.aim=(0,0)
        w.tick(.05,set())
        self.assertAlmostEqual(bullet.x-start[0],BALANCE['projectile_speed']*.05*.6)
        self.assertAlmostEqual(bullet.y-start[1],BALANCE['projectile_speed']*.05*.8)
        self.assertAlmostEqual(math.hypot(bullet.dx,bullet.dy),1)

    def test_mouse_on_player_has_safe_facing_fallback(self):
        w=World()
        w.aim=(w.cat.x,w.cat.y+26)
        w.cat.facing=-1
        w.shoot()
        self.assertEqual((w.projectiles[0].dx,w.projectiles[0].dy),(-1.,0.))

    def test_no_enemy_still_fires_and_projectiles_expire_at_map_edges(self):
        w=World()
        w.next_spawn_at=math.inf
        w.shoot()
        self.assertEqual((w.cat.ammo,len(w.projectiles)),(3,1))
        for x,y,dx,dy in ((WORLD_WIDTH-1,300,1,0),(1,300,-1,0),(400,559,0,1),(400,81,0,-1)):
            for piercing in (False,True):
                w.projectiles=[Projectile(x,y,dx=dx,dy=dy,piercing=piercing)]
                w.tick(.01,set())
                self.assertFalse(w.projectiles)

    def test_piercing_hits_all_crossed_enemies_once_and_is_125_percent(self):
        w=World()
        w.next_spawn_at=math.inf
        w.enemies=[Enemy(180,180,species='squirrel',max_hp=2.,state='CROUCH_CHARGE'),
                   Enemy(240,180,species='squirrel',max_hp=2.,state='CROUCH_CHARGE')]
        bullet=Projectile(100,180,piercing=True)
        self.assertEqual(bullet.scale,1.25)
        w.projectiles=[bullet]
        w.tick(.25,set())
        self.assertEqual([e.hp for e in w.enemies],[1,1])
        self.assertEqual(len(bullet.hit_enemies),2)
        self.assertIn(bullet,w.projectiles)

    def test_piercing_overlap_and_reentry_cannot_repeat_damage(self):
        w=World()
        w.next_spawn_at=math.inf
        w.update_enemy=lambda enemy,dt:None
        enemy=Enemy(200,180,species='squirrel',max_hp=2.,state='CROUCH_CHARGE')
        w.enemies=[enemy]
        bullet=Projectile(200,180,dx=0,dy=0,piercing=True)
        w.projectiles=[bullet]
        for _ in range(9):
            w.tick(.25,set())
        self.assertEqual(enemy.hp,1)
        self.assertIn(bullet,w.projectiles)  # No time-to-live while inside the map.
        bullet.x=500
        w.tick(.01,set())
        bullet.x=200
        w.tick(.01,set())
        self.assertEqual(enemy.hp,1)
        replacement=Enemy(200,180,species='squirrel',max_hp=2.,state='CROUCH_CHARGE')
        w.enemies=[replacement]
        w.tick(.01,set())
        self.assertEqual(replacement.hp,1)

    def test_pickup_ten_counter_and_three_special_charges_are_independent(self):
        w=World()
        w.next_spawn_at=math.inf
        for count in range(1,41):
            w.items=[Item(w.cat.x,w.cat.y+18)]
            w.tick(.001,set())
            self.assertEqual(w.cat.churu_collected,count%10)
            self.assertEqual(w.cat.pierce_charges,min(3,count//10))
        self.assertEqual(w.cat.ammo,4)
        w.shoot()
        self.assertEqual((w.cat.ammo,w.cat.pierce_charges,w.cat.churu_collected),(3,3,0))
        w.cat.ammo=0
        for _ in range(3):
            w.shoot(piercing=True)
        self.assertEqual((w.cat.ammo,w.cat.pierce_charges),(0,0))
        count=len(w.projectiles)
        w.shoot(piercing=True)
        self.assertEqual(len(w.projectiles),count)

    def test_dash_two_charges_share_sequential_nonresetting_recharge(self):
        w=World()
        w.next_spawn_at=math.inf
        self.assertEqual(w.cat.dash_charges,2)
        w.dash({'right'})
        self.assertEqual(w.cat.dash_charges,1)
        w.update(.2)
        remaining=w.cat.dash_cd
        w.dash({'left'})
        self.assertEqual(w.cat.dash_charges,0)
        self.assertAlmostEqual(w.cat.dash_cd,remaining)
        w.dash({'right'})
        self.assertEqual(w.cat.dash_charges,0)
        w.update(remaining-.01)
        self.assertEqual(w.cat.dash_charges,0)
        w.update(.02)
        self.assertEqual(w.cat.dash_charges,1)
        w.update(BALANCE['dash_cooldown'])
        self.assertEqual((w.cat.dash_charges,w.cat.dash_cd),(2,0.))

    def test_pause_freezes_charge_recovery_and_blocks_both_fire_modes(self):
        w=World()
        w.cat.pierce_charges=1
        w.dash({'right'})
        w.pause()
        snapshot=(w.cat.dash_charges,w.cat.dash_cd,w.cat.ammo,w.cat.pierce_charges)
        w.update(5)
        w.shoot()
        w.shoot(piercing=True)
        self.assertEqual(snapshot,(w.cat.dash_charges,w.cat.dash_cd,w.cat.ammo,w.cat.pierce_charges))
        self.assertFalse(w.projectiles)

    def test_ammo_cap_is_four_including_pickups(self):
        w=World()
        self.assertEqual(w.cat.ammo,4)
        w.items=[Item(w.cat.x,w.cat.y+18)]
        w.tick(.01,set())
        self.assertEqual(w.cat.ammo,4)

    def test_enemy_species_hp_and_nonlethal_hits_preserve_ai(self):
        for species,spec in SETTINGS['monsters'].items():
            e=Enemy(200,200,species=species,state='POP_UP' if species=='snake' else 'IDLE',clock=.1)
            required=spec['hp']
            state=e.state
            for hit in range(1,math.ceil(required)+1):
                killed=e.damage()
                self.assertEqual(e.hp,max(0.,required-hit))
                self.assertEqual(killed,hit==math.ceil(required))
                if not killed:self.assertEqual((e.state,e.clock),(state,.1))
            self.assertEqual(e.state,'HIT')
            self.assertFalse(e.damage())
        e=Enemy(200,200)
        e.damage(.25)
        self.assertEqual(e.hp,1.25)
        for invalid in (0,-1,math.nan,math.inf):
            with self.assertRaises(ValueError):e.damage(invalid)

    def test_projectile_consumed_on_nonlethal_hit_and_rewards_on_kill_only(self):
        w=World()
        w.next_spawn_at=math.inf
        e=Enemy(200,180,species='squirrel',max_hp=2.,state='CROUCH_CHARGE')
        w.enemies=[e]
        for expected_hp in (1,0):
            w.events.clear()
            w.projectiles=[Projectile(170,180)]
            w.tick(.04,set())
            self.assertEqual(e.hp,expected_hp)
            self.assertFalse(w.projectiles)
            self.assertEqual((w.run_exp,w.run_gold),(e.exp_reward,e.gold_reward) if expected_hp==0 else (0,0))
            self.assertEqual(w.events.count('enemy_hit'),1)
            self.assertEqual(w.events.count('enemy_death'),int(expected_hp==0))

    def test_down_space_drops_through_only_the_current_platform(self):
        w=World()
        w.next_spawn_at=math.inf
        c=w.cat
        c.x,c.y=488,300
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
        w.cat.x=288
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
        w.next_spawn_at=math.inf
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

    def test_continuous_spawns_skip_caps_without_accumulating_backlog(self):
        w=World()
        w.update(.24)
        self.assertFalse(w.enemies)
        w.update(.02)
        self.assertEqual(w.spawn_stats['attempted'],1)
        w.cat.invincible=9999
        w.update(16)
        self.assertLessEqual(sum(e.alive for e in w.enemies),w.rules['cap'])
        attempts=w.spawn_stats['attempted']
        w.enemies=[]
        remaining=w.next_spawn_at-w.time
        w.update(max(0,remaining-.01))
        self.assertEqual(w.spawn_stats['attempted'],attempts)
        w.update(.02)
        self.assertEqual(w.spawn_stats['attempted'],attempts+1)
        self.assertEqual(sum(e.alive for e in w.enemies),1)

    def test_pause_and_countdown_freeze_everything(self):
        w=World(42)
        w.update(1)
        w.pause()
        before=copy.deepcopy((w.time,w.cat,w.enemies,w.items,w.next_spawn_at,w.food_time,w.last_warning_boundary))
        w.update(20,{'right','shoot'})
        self.assertEqual(before,(w.time,w.cat,w.enemies,w.items,w.next_spawn_at,w.food_time,w.last_warning_boundary))
        w.pause()
        w.update(2.9,{'right','shoot'})
        self.assertEqual(before,(w.time,w.cat,w.enemies,w.items,w.next_spawn_at,w.food_time,w.last_warning_boundary))
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
        self.assertEqual(w.cat.x,WORLD_WIDTH-26)
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
        w.next_spawn_at=math.inf
        w.cat.hp=1
        w.enemies=[Enemy(w.cat.x,w.cat.y+24,species='bee',state='TARGET_LOCK',spawn_grace=0)]
        w.update(.01)
        self.assertEqual((w.mode,w.cat.state),('DYING','DEAD'))
        frozen=(w.time,w.next_spawn_at,w.enemies[0].x,w.food_time)
        w.update(DEATH_SECONDS-.01,{'right','shoot'})
        self.assertEqual(w.mode,'DYING')
        self.assertEqual(frozen,(w.time,w.next_spawn_at,w.enemies[0].x,w.food_time))
        w.update(.02)
        self.assertEqual(w.mode,'GAME_OVER')

    def test_player_contact_padding_is_reduced_to_seventy_percent(self):
        for gap, hp in ((34,3),(30,2)):
            w=World()
            w.next_spawn_at=math.inf
            w.enemies=[Enemy(w.cat.x+gap,w.cat.y+24,species='squirrel',
                             state='CROUCH_CHARGE',spawn_grace=0)]
            w.tick(.001,set())
            self.assertEqual(w.cat.hp,hp)

    def test_dash_prevents_contact_damage_only_during_dash(self):
        w=World()
        w.next_spawn_at=math.inf
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

    def test_killing_every_enemy_does_not_change_difficulty_or_end_run(self):
        w=World()
        w.next_spawn_at=math.inf
        w.enemies=[Enemy(100,300,species='bee',state='HIT')]
        w.update(.5)
        self.assertEqual((w.mode,w.rules['start']),('PLAYING',0))
        self.assertFalse(hasattr(w,'wave'))
        self.assertFalse(hasattr(w,'clear_run'))
        self.assertFalse(hasattr(w,'score'))

    def test_footstep_cadence_stops_while_paused(self):
        w=World()
        w.update(.5,{'right'})
        self.assertEqual(w.events.count('footstep'),2)
        w.pause()
        w.update(2,{'right'})
        self.assertEqual(w.events.count('footstep'),2)

    def test_warning_precedes_boundary_once_and_freezes_during_pause(self):
        w=World()
        w.next_spawn_at=math.inf
        w.time=26.98
        w.update(.01)
        self.assertFalse(w.warning_message)
        w.update(.02)
        self.assertTrue(w.warning_message)
        self.assertEqual(w.events.count('siren'),1)
        w.pause()
        before=(w.time,w.warning_message)
        w.update(10)
        self.assertEqual((w.time,w.warning_message),before)
        w.pause();w.update(3)
        w.update(2.98)
        self.assertTrue(w.warning_message)
        w.update(.02)
        self.assertEqual(w.rules['start'],30)
        self.assertFalse(w.warning_message)
        self.assertEqual(w.events.count('siren'),1)
        w.time=57
        w.update(.01)
        self.assertEqual(w.events.count('siren'),2)
        w.time=537
        w.update(.01)
        self.assertTrue(w.warning_message)
        self.assertEqual(w.events.count('siren'),3)

    def test_swept_hit_only_nearest_enemy(self):
        w=World()
        w.next_spawn_at=math.inf
        w.enemies=[Enemy(200,180,state='TARGET_LOCK',species='bee'),Enemy(200,180,state='TARGET_LOCK',species='bee')]
        w.projectiles=[Projectile(170,180,dx=1,dy=0)]
        w.tick(.1,set())
        self.assertEqual(sum(e.alive for e in w.enemies),1)
        self.assertEqual(len(w.projectiles),0)
        self.assertIsNotNone(segment_hit(0,0,1000,0,(400,-1,410,1)))
        self.assertIsNone(segment_hit(0,0,1000,0,(400,2,410,4)))

    def test_snake_underground_cannot_hit_or_be_hit(self):
        w=World()
        w.next_spawn_at=math.inf
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
        w.next_spawn_at=math.inf
        w.cat.invincible=9999
        w.update(25)
        self.assertTrue(any(i.kind=='bandage' for i in w.items))
        w.cat.x=100
        w.update(.01)
        self.assertFalse(any(i.kind=='bandage' for i in w.items))
        self.assertEqual(w.cat.hp,3)

    def test_stats_are_fixed_at_spawn_across_difficulty_boundary(self):
        w=World()
        w.time=89.9
        w.spawn_enemy('magpie')
        old=w.enemies[0]
        snapshot=(old.hp,old.max_hp,old.attack_interval,old.grade,old.exp_reward,old.gold_reward)
        w.time=120
        w.spawn_enemy('magpie')
        new=w.enemies[-1]
        self.assertGreater(new.max_hp,old.max_hp)
        self.assertLess(new.attack_interval,old.attack_interval)
        for _ in range(200):w.update_enemy(old,.1)
        self.assertEqual(snapshot,(old.hp,old.max_hp,old.attack_interval,old.grade,old.exp_reward,old.gold_reward))

    def test_runtime_stat_caps_hold_for_arbitrarily_late_spawns(self):
        for seconds in (480,540,3600,10**9):
            rules=difficulty_at(seconds)
            self.assertGreaterEqual(rules['spawn_interval'],.65)
            self.assertLessEqual(rules['cap'],24)
            for kind,spec in SETTINGS['monsters'].items():
                stats=monster_stats(kind,rules)
                self.assertLessEqual(stats['max_hp'],spec['max_hp'])
                self.assertGreaterEqual(stats['attack_interval'],spec['min_attack_interval'])
                self.assertGreaterEqual(stats['warning_seconds'],.4)
                self.assertLessEqual(stats['exp_reward'],spec['max_exp'])
                self.assertLessEqual(stats['gold_reward'],spec['max_gold'])
            self.assertEqual(rules['hp_multiplier'],4)
        self.assertNotEqual(difficulty_at(480)['weights'],difficulty_at(540)['weights'])
        self.assertEqual(difficulty_at(480)['weights'],difficulty_at(600)['weights'])

    def test_seed_reproducibility(self):
        a,b=World(17),World(17)
        a.update(3)
        b.update(3)
        self.assertEqual(a.enemies,b.enemies)
        self.assertEqual(a.items,b.items)

    def test_excessive_config_is_clamped_and_unchanged_mix_has_no_warning(self):
        excessive=dict(spawn_interval=.001,cap=999,hp_multiplier=999,attack_rate=999,reward_multiplier=999)
        with patch.dict(SETTINGS['phases'][-1],excessive):
            rules=difficulty_at(600)
            self.assertEqual((rules['spawn_interval'],rules['cap']),(.65,24))
            self.assertEqual((rules['hp_multiplier'],rules['attack_rate'],rules['reward_multiplier']),(4,1.5,3))
        mix=SETTINGS['combinations'][0]
        with patch.dict(SETTINGS,{'combinations':[mix,mix]}):
            w=World()
            w.next_spawn_at=math.inf
            w.time=537
            w.tick(.01,set())
            self.assertFalse(w.warning_message)
            self.assertNotIn('siren',w.events)

    def test_full_timeline_and_caps(self):
        w=World(17)
        w.cat.invincible=99999
        for _ in range(2500):
            w.update(.5)
            self.assertLessEqual(sum(e.alive for e in w.enemies),w.rules['cap'])
            for kind,spec in SETTINGS['monsters'].items():
                self.assertLessEqual(sum(e.alive and e.species==kind for e in w.enemies),spec['cap'])
        self.assertEqual(w.mode,'PLAYING')
        self.assertAlmostEqual(w.time,1250,places=5)
        self.assertFalse(hasattr(w,'score'))

    def test_bandage_warns_before_time_spawn_and_cannot_collect_early(self):
        w=World()
        w.next_spawn_at=math.inf
        w.time=27.99
        w.cat.hp=2
        w.update(.02)
        item=next(i for i in w.items if i.kind=='bandage')
        self.assertEqual(item.state,'PRE_SPAWN_WARNING')
        self.assertEqual(w.cat.hp,2)
        w.update(2)
        self.assertEqual(w.cat.hp,3)
        self.assertFalse(any(i.kind=='bandage' for i in w.items))
        self.assertEqual(w.next_bandage_at,60)


class StorageTest(unittest.TestCase):
    def test_corrupt_save_preserved_and_volume_sanitized(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            path=Path(folder)/'profile.json'
            path.write_text('{broken',encoding='utf-8')
            s=Store(folder)
            s.save_profile()
            self.assertEqual(len(list(Path(folder).glob('profile.json.damaged-*'))),1)
            self.assertEqual(json.loads(path.read_text())['version'],2)
            s.profile['bgm_volume']=float('nan')
            path.write_text(json.dumps(s.profile),encoding='utf-8')
            self.assertEqual(Store(folder).profile['bgm_volume'],70)



if __name__=='__main__':
    unittest.main()

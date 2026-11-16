"""Deterministic gameplay rules, independent of the graphics/audio device."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
import random
from uuid import uuid4
from .difficulty import SETTINGS, difficulty_at, monster_stats
from .states import CAT_ACTIVE, ENEMY_GRAPHS, Machine, actor_machine

ROOT = Path(__file__).resolve().parents[1]
BALANCE = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
_ART = json.loads((ROOT/'output/nyangi_art_v1/assets_manifest.json').read_text(encoding='utf-8-sig'))
_DEATH = next(e for e in _ART['entries'] if e['file']=='sprites/cat/tobi_default/dead.png')
DEATH_SECONDS = _DEATH['frames']/_DEATH['fps']
SPECIES = ('magpie', 'squirrel', 'bee', 'snake')
SKINS = ('tobi_default', 'magpie_tuxedo', 'squirrel_brown', 'bee_golden', 'snake_silver', 'rainbow_clear')


def segment_hit(ax, ay, bx, by, box):
    """Return earliest segment/AABB hit, including a stationary segment."""
    low, high = 0., 1.
    for start, delta, minimum, maximum in ((ax, bx-ax, box[0], box[2]), (ay, by-ay, box[1], box[3])):
        if abs(delta) < 1e-9:
            if not minimum <= start <= maximum:
                return None
        else:
            u, v = sorted(((minimum-start)/delta, (maximum-start)/delta))
            low, high = max(low, u), min(high, v)
            if low > high:
                return None
    return low


@dataclass
class Actor:
    x: float
    y: float
    state: str = 'IDLE'
    clock: float = 0.
    machine: Machine = field(init=False,repr=False,compare=False)

    def __post_init__(self):
        self.machine = actor_machine(self,self.state_graph())

    def state_graph(self):
        return {'IDLE':()}

    def _state_entered(self, event):
        if event.kwargs.get('reset_clock',True):
            self.clock = 0.

    def enter(self, state, *, reset_clock=True):
        if state == self.state and not reset_clock:
            return
        return self.trigger('enter_'+state,reset_clock=reset_clock)


@dataclass
class Cat(Actor):
    vx: float = 0.
    vy: float = 0.
    facing: int = 1
    grounded: bool = True
    jumps_used: int = 0
    hp: int = 3
    ammo: int = BALANCE['ammo_max']
    dash_left: float = 0.
    dash_cd: float = 0.
    dash_charges: int = BALANCE['dash_max_charges']
    churu_collected: int = 0
    pierce_charges: int = 0
    shot_cd: float = 0.
    invincible: float = 0.
    attack_left: float = 0.
    heal_left: float = 0.
    idle_time: float = 0.
    step_clock: float = 0.

    def state_graph(self):
        return {**{state:tuple(s for s in (*CAT_ACTIVE,'DEAD') if s != state) for state in CAT_ACTIVE},'DEAD':()}


@dataclass
class Enemy(Actor):
    species: str = 'magpie'
    hp: float | None = None
    max_hp: float | None = None
    attack_interval: float | None = None
    warning_seconds: float = .6
    exp_reward: int | None = None
    gold_reward: int | None = None
    hit_flash: float = 0.
    grade: int = 0
    vx: float = 0.
    vy: float = 0.
    origin_y: float = 0.
    attack_dx: float = 0.
    attack_dy: float = 0.
    behavior: int = 0
    distance: float = 0.
    attack_length: float = 260.
    arc_start_x: float = 0.
    arc_end_x: float = 0.
    arc_depth: float = 0.
    spawn_grace: float = .8
    speed_scale: float = 1.

    def __post_init__(self):
        spec = SETTINGS['monsters'][self.species]
        self.max_hp = float(spec['hp'] if self.max_hp is None else min(spec['max_hp'],self.max_hp))
        if not math.isfinite(self.max_hp) or self.max_hp<=0:
            raise ValueError('Enemy HP must be finite and positive')
        self.attack_interval = max(spec['min_attack_interval'],spec['attack_interval'] if self.attack_interval is None else self.attack_interval)
        self.warning_seconds = max(SETTINGS['limits']['min_warning_seconds'],self.warning_seconds)
        self.exp_reward = spec['exp'] if self.exp_reward is None else min(spec['max_exp'],self.exp_reward)
        self.gold_reward = spec['gold'] if self.gold_reward is None else min(spec['max_gold'],self.gold_reward)
        if self.hp is None:
            self.hp = 0 if self.state in ('HIT','DEAD') else self.max_hp
        super().__post_init__()

    def damage(self, amount=1.):
        if not math.isfinite(amount) or amount<=0:
            raise ValueError('Damage must be finite and positive')
        if not self.exposed:
            return False
        self.hp = max(0.,self.hp-amount)
        self.hit_flash = .15
        if self.hp == 0:
            self.enter('HIT')
            return True
        return False

    def state_graph(self):
        graph = ENEMY_GRAPHS[self.species]
        return {**{state:(*targets,'HIT') for state,targets in graph.items()},'HIT':('DEAD',),'DEAD':()}

    @property
    def alive(self):
        return self.hp>0 and self.state not in ('HIT', 'DEAD')

    @property
    def exposed(self):
        return self.alive and (self.species != 'snake' or self.state in ('POP_UP', 'RETURN_UNDERGROUND'))

    @property
    def targetable(self):
        return self.exposed and 0 <= self.x <= 960 and BALANCE['ground'] <= self.y <= 560

    def box(self, padding=0):
        rx, ry = (13, 11) if self.species == 'bee' else (22, 23)
        if self.species == 'snake':
            ry = 30
        return self.x-rx-padding, self.y-ry-padding, self.x+rx+padding, self.y+ry+padding


@dataclass
class Projectile(Actor):
    dx: float = 1.
    dy: float = 0.
    piercing: bool = False
    hit_enemies: list = field(default_factory=list,repr=False,compare=False)

    @property
    def scale(self):
        return BALANCE['pierce_scale'] if self.piercing else 1.

    def state_graph(self):
        return {'IDLE':('FLY',),'FLY':('HIT','DESPAWN'),'HIT':(),'DESPAWN':()}


@dataclass
class Item(Actor):
    kind: str = 'churu'

    def state_graph(self):
        graph = {'IDLE':('COLLECTED',),'SPAWN':('IDLE','COLLECTED'),'COLLECTED':()}
        if self.kind == 'churu':
            graph['IDLE'] += ('DESPAWN',)
            graph['SPAWN'] += ('DESPAWN',)
            graph['DESPAWN'] = ()
        elif self.kind == 'bandage':
            graph['PRE_SPAWN_WARNING'] = ('SPAWN',)
        else:
            raise ValueError(f'Unknown item kind: {self.kind}')
        return graph


class World:
    def __init__(self, seed=1, character_id="nabi"):
        self.run_id = str(uuid4())
        self.character_id = character_id
        self.run_exp = self.run_gold = 0
        self.run_kills = dict.fromkeys(SPECIES,0)
        self.end_reason = None
        self.seed = seed
        self.rng = random.Random(seed)
        self.cat = Cat(480, BALANCE['ground'])
        self.aim = (960.,BALANCE['ground']+26.)
        self.enemies, self.projectiles, self.items, self.trails = [], [], [], []
        self.time, self.food_time = 0., 0.
        self.spawn_rng = random.Random(seed ^ 2654435761)
        self.next_spawn_at = SETTINGS['initial_spawn_delay']
        self.next_bandage_at = SETTINGS['bandage_interval']
        self.last_warning_boundary = None
        self.countdown = 0.
        self.machine = Machine(model=self,model_attribute='mode',initial='PLAYING',
                               states=['PLAYING','PAUSED','COUNTDOWN','DYING','GAME_OVER'],
                               auto_transitions=False,transitions=[
                                   ['pause_play','PLAYING','PAUSED'],
                                   dict(trigger='resume_play',source='PAUSED',dest='COUNTDOWN',before='_prepare_countdown'),
                                   ['finish_resume','COUNTDOWN','PLAYING'],
                                   dict(trigger='begin_death',source='PLAYING',dest='DYING',before='_start_death'),
                                   ['finish_death','DYING','GAME_OVER'],
                                   dict(trigger='finish_run',source=['PLAYING','PAUSED','COUNTDOWN'],dest='GAME_OVER',before='_abandon')])
        self.events = []
        self.swings = []
        self.spawn_stats = dict(attempted=0, success=0, skipped=0)
        self.bandage_due = None
        self.spawn_food(4)

    @property
    def rules(self):
        return difficulty_at(self.time)

    @property
    def warning_message(self):
        rules = self.rules
        boundary = rules['next_change']
        if not 1e-8 < boundary-self.time <= SETTINGS['warning_seconds']+1e-8:
            return ''
        following = difficulty_at(boundary)
        keys = ('spawn_interval','cap','weights','hp_multiplier','attack_rate','reward_multiplier','grade')
        return following['warning'] if any(rules[k]!=following[k] for k in keys) else ''

    def pause(self):
        if self.mode == 'PLAYING':
            self.pause_play()
        elif self.mode == 'PAUSED':
            self.resume_play()

    def _prepare_countdown(self):
        self.countdown = 3.

    def _abandon(self):
        self.end_reason = "abandoned"
        self.run_exp = self.run_gold = 0
        self.run_kills = dict.fromkeys(SPECIES,0)

    def _start_death(self):
        self.end_reason = "death"
        self.cat.enter('DEAD')
        self.cat.vx = self.cat.vy = 0.
        self.cat.attack_left = 0.
        self.events.append('cat_death')

    def jump(self,keys=frozenset()):
        if self.mode != 'PLAYING':
            return
        c = self.cat
        if 'down' in keys and c.grounded and c.y > BALANCE['ground']:
            # Start below the one-way surface so lower platforms still catch the fall.
            c.y -= 2
            c.vy,c.grounded,c.jumps_used = -80.,False,1
            c.enter('FALL')
            return
        if self.cat.jumps_used < BALANCE['max_jumps']:
            self.cat.vy, self.cat.grounded = BALANCE['jump_speed'], False
            self.cat.jumps_used += 1
            self.cat.enter('JUMP')
            self.events.append('jump')

    def dash(self, keys):
        c = self.cat
        if self.mode != 'PLAYING' or c.dash_charges == 0 or c.dash_left > 0:
            return
        move = int('right' in keys) - int('left' in keys)
        c.facing = move or c.facing
        c.dash_left = BALANCE['dash_duration']
        if c.dash_charges == BALANCE['dash_max_charges']:
            c.dash_cd = BALANCE['dash_cooldown']
        c.dash_charges -= 1
        c.enter('DASH')
        self.events.append('dash')

    def aim_direction(self):
        c = self.cat
        dx,dy = self.aim[0]-c.x,self.aim[1]-c.y-26
        length = math.hypot(dx,dy)
        return (dx/length,dy/length) if length > 1e-9 else (float(c.facing),0.)

    def shoot(self,piercing=False):
        c = self.cat
        if self.mode != 'PLAYING' or (not piercing and c.shot_cd > 0):
            return
        if self.character_id=='black':
            return self.melee(piercing)
        if not (c.pierce_charges if piercing else c.ammo):
            self.events.append('empty')
            return
        dx,dy = self.aim_direction()
        self.projectiles.append(Projectile(c.x,c.y+26,dx=dx,dy=dy,piercing=piercing))
        if piercing:
            c.pierce_charges -= 1
        else:
            c.ammo -= 1
            c.shot_cd = BALANCE['shot_cooldown']
        c.attack_left = .2
        self.events.append('shot')

    def hit_enemy(self, enemy, damage):
        killed=enemy.damage(damage)
        self.events.append('enemy_hit')
        if killed:
            self.run_kills[enemy.species]+=1
            self.run_exp+=enemy.exp_reward
            self.run_gold+=enemy.gold_reward
            self.events.append('enemy_death')

    def melee(self, special=False):
        c=self.cat
        if special and not c.pierce_charges:
            self.events.append('empty')
            return
        if special:
            c.pierce_charges-=1
        else:
            c.shot_cd=.4
        dx,dy=self.aim_direction()
        radius=112.5 if special else 90.
        damage=3. if special else 2.
        c.facing=1 if dx>=0 else -1
        c.attack_left=.22
        self.swings.append((c.x,c.y+26,math.atan2(dy,dx),radius,self.time,special))
        for enemy in self.enemies:
            ex,ey=enemy.x-c.x,enemy.y-c.y-26
            length=math.hypot(ex,ey)
            if enemy.exposed and length<=radius+15 and (length<1e-9 or (ex*dx+ey*dy)/length>=math.cos(math.radians(80 if special else 55))):
                self.hit_enemy(enemy,damage)
        self.events.append('shot')

    def spawn_food(self, count):
        count = min(count, BALANCE['food_cap'] - sum(i.kind == 'churu' for i in self.items))
        for _ in range(count):
            for _ in range(24):
                if self.rng.random() < .35:
                    x = self.cat.x + self.rng.choice((-1, 1))*self.rng.uniform(80, 260)
                    y = BALANCE['ground']+18
                else:
                    left, right, floor = self.rng.choice(BALANCE['surfaces'])
                    x, y = self.rng.uniform(left+22, right-22), floor+18
                if not 35 < x < 925 or abs(x-self.cat.x) < 35:
                    continue
                if any(math.hypot(x-i.x, y-i.y) < 55 for i in self.items):
                    continue
                if any(e.exposed and math.hypot(x-e.x, y-e.y) < 75 for e in self.enemies):
                    continue
                self.items.append(Item(x, y, state='SPAWN'))
                break

    def spawn_enemy(self, kind):
        self.spawn_stats['attempted'] += 1
        living = [e for e in self.enemies if e.alive]
        rules = self.rules
        if len(living) >= rules['cap'] or sum(e.species == kind for e in living) >= SETTINGS['monsters'][kind]['cap']:
            self.spawn_stats['skipped'] += 1
            return
        for _ in range(24):
            x = self.spawn_rng.uniform(45, 915)
            y = self.spawn_rng.uniform(310, 480) if kind in ('magpie', 'bee') else BALANCE['ground']+22
            if kind == 'magpie':
                y = BALANCE['magpie_y']
            if kind == 'squirrel':
                left, right, floor = self.spawn_rng.choice(BALANCE['surfaces'])
                x, y = self.spawn_rng.uniform(left+25, right-25), floor+22
            if math.hypot(x-self.cat.x, y-self.cat.y-22) < 145:
                continue
            if any(math.hypot(x-e.x, y-e.y) < 65 for e in living):
                continue
            self.enemies.append(Enemy(x, y, species=kind, **monster_stats(kind,rules),
                                      vx=self.spawn_rng.choice((-1, 1))*70, origin_y=y,
                                      behavior=self.spawn_rng.randrange(3), speed_scale=1.1 if rules['grade']==2 else 1.))
            self.spawn_stats['success'] += 1
            return
        self.spawn_stats['skipped'] += 1

    def update_cat(self, dt, keys):
        c = self.cat
        was_grounded = c.grounded
        for name in ('shot_cd', 'invincible', 'attack_left', 'heal_left'):
            setattr(c, name, max(0., getattr(c, name)-dt))
        if c.dash_charges < BALANCE['dash_max_charges']:
            c.dash_cd -= dt
            while c.dash_cd <= 1e-9 and c.dash_charges < BALANCE['dash_max_charges']:
                c.dash_charges += 1
                c.dash_cd += BALANCE['dash_cooldown']
            if c.dash_charges == BALANCE['dash_max_charges']:
                c.dash_cd = 0.
        move = int('right' in keys)-int('left' in keys)
        if move and c.dash_left <= 0:
            c.facing = move
        c.vx = move * BALANCE['move_speed']
        if c.dash_left > 0:
            c.vx = c.facing * BALANCE['dash_speed']
            c.dash_left = max(0., c.dash_left-dt)
            if not self.trails or self.time-self.trails[-1][3] > .025:
                self.trails.append((c.x, c.y, c.facing, self.time))
        previous = c.y
        c.x = max(26, min(934, c.x+c.vx*dt))
        c.vy -= BALANCE['gravity'] * dt
        c.y += c.vy * dt
        c.grounded = False
        for left, right, floor in sorted(BALANCE['surfaces'], key=lambda v: -v[2]):
            if left-15 <= c.x <= right+15 and c.vy <= 0 and previous >= floor-.01 and c.y <= floor:
                c.y, c.vy, c.grounded = floor, 0., True
                c.jumps_used = 0
                if not was_grounded:
                    self.events.append('land')
                break
        c.idle_time = c.idle_time+dt if c.grounded and not move else 0.
        c.step_clock = c.step_clock+dt if c.grounded and move and c.dash_left<=0 else 0.
        if c.step_clock >= .22:
            c.step_clock -= .22
            self.events.append('footstep')
        state = ('DASH' if c.dash_left > 0 else 'JUMP' if c.vy > 0 else 'FALL' if not c.grounded
                 else 'MOVE' if move else 'GROOM' if c.idle_time > 4 else 'IDLE')
        if state != c.state:
            c.enter(state)
        c.clock += dt

    def update_enemy(self, e, dt):
        e.clock += dt
        e.hit_flash = max(0.,e.hit_flash-dt)
        if not e.alive:
            if e.state == 'HIT' and e.clock > .1:
                e.enter('DEAD')
            return
        e.spawn_grace = max(0., e.spawn_grace-dt)
        g, c = e.grade, self.cat
        warning = e.warning_seconds
        if e.species == 'snake':
            if e.state in ('IDLE', 'BURROW_MOVE'):
                e.y = BALANCE['ground']+22
                dx = c.x-e.x
                e.x += max(-1, min(1, dx))*(55, 62, 70)[g]*dt
                if abs(dx) < 42 and e.clock > e.attack_interval:
                    e.enter('CHARGE')
                elif abs(dx) >= 42:
                    e.enter('BURROW_MOVE',reset_clock=False)
            elif e.state == 'CHARGE':
                e.y = BALANCE['ground']+22
                if e.clock >= warning:
                    e.enter('POP_UP')
                    self.events.append('snake_attack')
            elif e.state == 'POP_UP':
                e.y = BALANCE['ground']+22+45*min(1, e.clock/.18)
                if e.clock >= .3:
                    e.enter('RETURN_UNDERGROUND')
            elif e.state == 'RETURN_UNDERGROUND':
                e.y = BALANCE['ground']+22+45*max(0, 1-e.clock/.24)
                if e.clock >= .24:
                    e.enter('IDLE')
        elif e.species == 'squirrel':
            if e.state in ('IDLE', 'PATROL', 'LAND'):
                e.x += e.vx*dt*e.speed_scale
                surface = next((s for s in BALANCE['surfaces'][1:] if abs(e.y-s[2]-22) < 2 and s[0]-2 <= e.x <= s[1]+2), BALANCE['surfaces'][0])
                if e.x < surface[0]+25 or e.x > surface[1]-25:
                    e.vx *= -1
                    e.x = max(surface[0]+25,min(surface[1]-25,e.x))
                e.enter('PATROL',reset_clock=False)
                if e.clock > e.attack_interval:
                    e.enter('CROUCH_CHARGE')
            elif e.state == 'CROUCH_CHARGE' and e.clock > warning+.2:
                e.vy = (520, 600, 660)[g]
                e.vx = (1 if c.x > e.x else -1)*150
                e.enter('JUMP')
                self.events.append('squirrel_attack')
            elif e.state == 'JUMP':
                old_y = e.y
                e.vy -= BALANCE['gravity']*dt
                e.x += e.vx*dt
                e.y += e.vy*dt
                if e.x < 25 or e.x > 935:
                    e.x = max(25, min(935, e.x))
                    e.vx *= -1
                for left, right, floor in sorted(BALANCE['surfaces'], key=lambda s: -s[2]):
                    if left <= e.x <= right and e.vy <= 0 and old_y-22 >= floor and e.y-22 <= floor:
                        e.y, e.vy = floor+22, 0
                        e.enter('LAND')
                        break
        elif e.species == 'magpie':
            self.update_magpie(e,dt,warning)
        else:
            if e.state in ('IDLE', 'WAIT'):
                if e.clock > e.attack_interval:
                    dx,dy = c.x-e.x,c.y+24-e.y
                    length = max(1,math.hypot(dx,dy))
                    e.attack_dx, e.attack_dy = dx/length, dy/length
                    e.enter('TARGET_LOCK')
            elif e.state == 'TARGET_LOCK' and e.clock >= warning:
                e.distance = 0.
                e.enter('DASH')
                self.events.append('bee_attack')
            elif e.state == 'DASH':
                speed = 250
                e.x += e.attack_dx*speed*dt
                e.y += e.attack_dy*speed*dt
                e.distance += speed*dt
                e.x, e.y = max(25,min(935,e.x)), max(BALANCE['ground']+20,min(510,e.y))
                if e.distance >= 140:
                    e.enter('WAIT')

    def update_magpie(self,e,dt,warning):
        home = BALANCE['magpie_y']
        if e.state in ('IDLE','FLY','WARNING'):
            e.y = home
        if e.state in ('IDLE','FLY'):
            if e.behavior == 2:
                speed = (150,175,190)[e.grade]
                e.vx = max(-speed,min(speed,(self.cat.x-e.x)*1.5))
            elif e.behavior == 0 and self.rng.random() < dt*.6:
                e.vx *= -1
            e.x += e.vx*dt*e.speed_scale
            if e.x < 30 or e.x > 930:
                e.x = max(30,min(930,e.x))
                e.vx *= -1
            e.enter('FLY',reset_clock=False)
            if e.clock > e.attack_interval:
                dx,dy = self.cat.x-e.x,self.cat.y+24-e.y
                length = max(1.,math.hypot(dx,dy))
                e.attack_dx,e.attack_dy = dx/length,dy/length
                e.attack_length = min(700.,max(260.,length+40))
                e.arc_start_x = e.x
                e.arc_end_x = max(30,min(930,2*self.cat.x-e.x))
                e.arc_depth = max(60,min(home-BALANCE['ground']-22,home-self.cat.y-24))
                e.enter('WARNING')
        elif e.state == 'WARNING' and e.clock >= warning:
            e.distance = 0.
            e.enter('DIVE' if e.behavior == 0 else 'RUSH')
            self.events.append('magpie_attack')
        elif e.state == 'DIVE':
            t = min(1.,e.clock/BALANCE['magpie_arc_seconds'])
            e.x = e.arc_start_x+(e.arc_end_x-e.arc_start_x)*t
            e.y = home-4*e.arc_depth*t*(1-t)
            if t >= 1:
                e.enter('IDLE')
        elif e.state == 'RUSH':
            speed = (360,400,450)[e.grade]
            e.x = max(25,min(935,e.x+e.attack_dx*speed*dt))
            e.y = max(BALANCE['ground']+22,min(520,e.y+e.attack_dy*speed*dt))
            e.distance += speed*dt
            if e.distance >= e.attack_length:
                e.enter('RECOVER')
        elif e.state == 'RECOVER':
            delta = home-e.y
            step = BALANCE['magpie_return_speed']*dt
            e.y += max(-step,min(step,delta))
            if abs(e.y-home) < .001:
                e.enter('IDLE')

    def update(self, dt, keys=frozenset()):
        if dt < 0 or not math.isfinite(dt):
            raise ValueError('dt must be finite and nonnegative')
        if self.mode == 'DYING':
            self.cat.clock += dt
            if self.cat.clock >= DEATH_SECONDS:
                self.finish_death()
            return
        if self.mode == 'COUNTDOWN':
            self.countdown -= dt
            if self.countdown <= 0:
                self.finish_resume()
            return
        if self.mode != 'PLAYING':
            return
        # Fixed substeps preserve collision and due events after a slow frame.
        while dt > 1e-9 and self.mode == 'PLAYING':
            step = min(dt, 1/120)
            self.tick(step, keys)
            dt -= step

    def tick(self, dt, keys):
        self.time += dt
        rules = self.rules
        boundary = rules['next_change']
        if self.warning_message and self.last_warning_boundary != boundary:
            self.last_warning_boundary = boundary
            self.events.append('siren')
        self.food_time += dt
        self.update_cat(dt,keys)
        if 'shoot' in keys:
            self.shoot()
        if self.time+1e-8 >= self.next_spawn_at:
            weights = rules['weights']
            self.spawn_enemy(self.spawn_rng.choices(list(weights),weights=list(weights.values()))[0])
            self.next_spawn_at = self.time+rules['spawn_interval']
        if self.food_time >= SETTINGS['food_interval']:
            self.food_time -= SETTINGS['food_interval']
            self.spawn_food(4)
        if self.time >= self.next_bandage_at-SETTINGS['bandage_warning_seconds'] and self.bandage_due is None:
            if not any(i.kind=='bandage' for i in self.items):
                self.items.append(Item(480,BALANCE['ground']+18,kind='bandage',state='PRE_SPAWN_WARNING'))
                self.bandage_due = self.next_bandage_at
        if self.time+1e-8 >= self.next_bandage_at:
            for item in self.items:
                if item.kind=='bandage' and item.state=='PRE_SPAWN_WARNING':
                    item.enter('SPAWN')
            self.bandage_due = None
            self.next_bandage_at += SETTINGS['bandage_interval']
        for e in self.enemies:
            self.update_enemy(e,dt)
        for p in self.projectiles:
            p.clock += dt
            old_x,old_y = p.x,p.y
            p.x += p.dx*BALANCE['projectile_speed']*dt
            p.y += p.dy*BALANCE['projectile_speed']*dt
            p.enter('FLY',reset_clock=False)
            hits = sorted(((t,e) for e in self.enemies if e.exposed and not any(e is hit for hit in p.hit_enemies)
                           and (t:=segment_hit(old_x,old_y,p.x,p.y,e.box(5*p.scale))) is not None),key=lambda pair:pair[0])
            for _,e in hits if p.piercing else hits[:1]:
                p.hit_enemies.append(e)
                self.hit_enemy(e,1.)
                if not p.piercing:
                    p.enter('HIT')
            if p.state != 'HIT' and (not 0 <= p.x <= 960 or not BALANCE['ground'] <= p.y <= 560):
                p.enter('DESPAWN')
        self.projectiles = [p for p in self.projectiles if p.state not in ('HIT','DESPAWN')]
        self.enemies = [e for e in self.enemies if not(e.state == 'DEAD' and e.clock > .45)]
        c = self.cat
        for i in self.items:
            i.clock += dt
            if i.state == 'SPAWN' and i.clock > .15:
                i.enter('IDLE')
            if i.state != 'PRE_SPAWN_WARNING' and math.hypot(i.x-c.x,i.y-c.y-18) < 35:
                if i.kind == 'churu':
                    c.ammo = min(BALANCE['ammo_max'],c.ammo+1)
                    c.churu_collected += 1
                    if c.churu_collected >= BALANCE['pierce_pickups']:
                        c.churu_collected = 0
                        c.pierce_charges = min(BALANCE['pierce_max_charges'],c.pierce_charges+1)
                    self.events.append('pickup')
                else:
                    c.hp = min(3,c.hp+1)
                    c.heal_left = .6
                    self.events.append('heal')
                i.enter('COLLECTED')
            elif i.kind == 'churu' and i.clock > BALANCE['food_lifetime']:
                i.enter('DESPAWN')
        self.items = [i for i in self.items if i.state not in ('COLLECTED','DESPAWN')]
        if not c.invincible and c.dash_left <= 0:
            for e in self.enemies:
                if e.exposed and not e.spawn_grace and segment_hit(c.x,c.y+24,c.x,c.y+24,e.box(13*BALANCE['player_hitbox_scale'])) is not None:
                    c.hp -= 1
                    c.invincible = BALANCE['invincible_seconds']
                    self.events.append('hurt')
                    if c.hp <= 0:
                        self.begin_death()
                    break
        self.trails = [t for t in self.trails if self.time-t[3] < .23]
        self.swings = [s for s in self.swings if self.time-s[4]<.22]

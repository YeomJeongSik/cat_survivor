"""Deterministic gameplay rules, independent of the graphics/audio device."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
import random
from .states import CAT_ACTIVE, ENEMY_GRAPHS, Machine, actor_machine

ROOT = Path(__file__).resolve().parents[1]
BALANCE = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
WAVES = json.loads((ROOT / 'config/wave_data.json').read_text(encoding='utf-8'))
ACHIEVEMENTS = json.loads((ROOT/'config/achievements.json').read_text(encoding='utf-8'))
_ART = json.loads((ROOT/'output/nyangi_art_v1/assets_manifest.json').read_text(encoding='utf-8-sig'))
_DEATH = next(e for e in _ART['entries'] if e['file']=='sprites/cat/tobi_default/dead.png')
DEATH_SECONDS = _DEATH['frames']/_DEATH['fps']
SPECIES = ('magpie', 'squirrel', 'bee', 'snake')
SKINS = ('tobi_default', 'magpie_tuxedo', 'squirrel_brown', 'bee_golden', 'snake_silver', 'rainbow_clear')


def direction_to(x, y, target):
    dx,dy = target.x-x,target.y-y
    length = math.hypot(dx,dy)
    return (dx/length,dy/length) if length else (1.,0.)


def wave_quota(spec):
    return math.ceil(spec['quota']*BALANCE['spawn_multiplier'])


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
    hp: int | None = None
    max_hp: int = field(init=False)
    hit_flash: float = 0.
    grade: int = 0
    max_grade: int = 1
    evolution: float = 0.
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
        self.max_hp = BALANCE['enemy_hp'][self.species]
        if self.hp is None:
            self.hp = 0 if self.state in ('HIT','DEAD') else self.max_hp
        super().__post_init__()

    def damage(self):
        if not self.exposed:
            return False
        self.hp = max(0,self.hp-1)
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
    target: Enemy | None = field(default=None,repr=False,compare=False)

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
    def __init__(self, seed=1):
        self.seed = seed
        self.rng = random.Random(seed)
        self.cat = Cat(480, BALANCE['ground'])
        self.enemies, self.projectiles, self.items, self.trails = [], [], [], []
        self.time, self.wave_time, self.food_time = 0., 0., 0.
        self.wave, self.completed, self.kill_score = 1, 0, 0
        self.countdown = 0.
        self.machine = Machine(model=self,model_attribute='mode',initial='PLAYING',
                               states=['PLAYING','PAUSED','COUNTDOWN','DYING','GAME_OVER','CLEAR'],
                               auto_transitions=False,transitions=[
                                   ['pause_play','PLAYING','PAUSED'],
                                   dict(trigger='resume_play',source='PAUSED',dest='COUNTDOWN',before='_prepare_countdown'),
                                   ['finish_resume','COUNTDOWN','PLAYING'],
                                   dict(trigger='begin_death',source='PLAYING',dest='DYING',before='_start_death'),
                                   ['finish_death','DYING','GAME_OVER'],
                                   ['finish_run',['PLAYING','PAUSED','COUNTDOWN'],'GAME_OVER'],
                                   ['clear_run','PLAYING','CLEAR']])
        self.unlocked = {'tobi_default'}
        self.notices, self.events = [], []
        self.spawn_stats = dict(attempted=0, success=0, skipped=0)
        self.bandage_due = None
        self.start_wave()
        self.spawn_food(4)

    @property
    def spec(self):
        return WAVES[self.wave-1]

    @property
    def score(self):
        return self.completed * 100 + int(self.time * 2) + self.kill_score + (50000 if self.mode == 'CLEAR' else 0)

    def start_wave(self):
        self.wave_time = 0.
        self.wave_rng = random.Random(self.seed ^ (self.wave * 2654435761))
        kinds = list(self.spec['species'])
        offset = self.wave % len(kinds)
        kinds = kinds[offset:] + kinds[:offset]
        self.spawn_queue = []
        due = BALANCE['spawn_first_delay']
        for i in range(wave_quota(self.spec)):
            self.spawn_queue.append((due,kinds[i%len(kinds)]))
            due += BALANCE['spawn_fast_gap'] if i<2 else BALANCE['spawn_slow_gap']
        if self.wave % BALANCE['heal_wave_interval'] == 0:
            self.bandage_due = self.time + .4
        self.events.append('wave')
        self.siren_due = [0.,.32,.64]

    def pause(self):
        if self.mode == 'PLAYING':
            self.pause_play()
        elif self.mode == 'PAUSED':
            self.resume_play()

    def _prepare_countdown(self):
        self.countdown = 3.

    def _start_death(self):
        self.cat.enter('DEAD')
        self.cat.vx = self.cat.vy = 0.
        self.cat.attack_left = 0.
        self.events.append('cat_death')

    def jump(self,keys=frozenset()):
        if self.mode != 'PLAYING':
            return
        c = self.cat
        if self.cat.jumps_used < BALANCE['max_jumps']:
            self.cat.vy, self.cat.grounded = BALANCE['jump_speed'], False
            self.cat.jumps_used += 1
            self.cat.enter('JUMP')
            self.events.append('jump')

    def dash(self, keys):
        c = self.cat
        if self.mode != 'PLAYING' or c.dash_cd > 0:
            return
        move = int('right' in keys) - int('left' in keys)
        c.facing = move or c.facing
        c.dash_left, c.dash_cd = BALANCE['dash_duration'], BALANCE['dash_cooldown']
        c.enter('DASH')
        self.events.append('dash')

    def nearest_enemy(self, x, y):
        return min((e for e in self.enemies if e.targetable),
                   key=lambda e:(e.x-x)**2+(e.y-y)**2,default=None)

    def shoot(self):
        c = self.cat
        if self.mode != 'PLAYING' or c.shot_cd > 0:
            return
        c.shot_cd = BALANCE['shot_cooldown']
        if not c.ammo:
            self.events.append('empty')
            return
        target = self.nearest_enemy(c.x,c.y+26)
        if target is None:
            self.events.append('no_target')
            return
        dx,dy = direction_to(c.x,c.y+26,target)
        self.projectiles.append(Projectile(c.x+dx*25,c.y+26+dy*18,dx=dx,dy=dy,target=target))
        c.ammo -= 1
        c.attack_left = .2
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
        if len(living) >= self.spec['cap'] or (kind == 'bee' and sum(e.species == 'bee' for e in living) >= 3):
            self.spawn_stats['skipped'] += 1
            return
        for _ in range(24):
            x = self.wave_rng.uniform(45, 915)
            y = self.wave_rng.uniform(310, 480) if kind in ('magpie', 'bee') else BALANCE['ground']+22
            if kind == 'magpie':
                y = BALANCE['magpie_y']
            if kind == 'squirrel':
                left, right, floor = self.wave_rng.choice(BALANCE['surfaces'])
                x, y = self.wave_rng.uniform(left+25, right-25), floor+22
            if math.hypot(x-self.cat.x, y-self.cat.y-22) < 145:
                continue
            if any(math.hypot(x-e.x, y-e.y) < 65 for e in living):
                continue
            grade = self.spec['grade']
            self.enemies.append(Enemy(x, y, species=kind, grade=grade, max_grade=1 if grade == 0 else 2,
                                      vx=self.wave_rng.choice((-1, 1))*70, origin_y=y,
                                      behavior=self.wave_rng.randrange(3), speed_scale=1.1 if self.spec['stage'] >= 3 else 1.))
            self.spawn_stats['success'] += 1
            return
        self.spawn_stats['skipped'] += 1

    def update_cat(self, dt, keys):
        c = self.cat
        was_grounded = c.grounded
        for name in ('dash_cd', 'shot_cd', 'invincible', 'attack_left', 'heal_left'):
            setattr(c, name, max(0., getattr(c, name)-dt))
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
        e.evolution += dt
        if e.grade < e.max_grade and e.evolution >= BALANCE['evolution_seconds']:
            e.grade += 1
            e.evolution = 0.
        g, c = e.grade, self.cat
        warning = (.6, .45, .34)[g]
        if e.species == 'snake':
            if e.state in ('IDLE', 'BURROW_MOVE'):
                e.y = BALANCE['ground']+22
                dx = c.x-e.x
                e.x += max(-1, min(1, dx))*(55, 62, 70)[g]*dt
                if abs(dx) < 42 and e.clock > .8:
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
                if e.clock > 1.7:
                    e.enter('CROUCH_CHARGE')
            elif e.state == 'CROUCH_CHARGE' and e.clock > (.8, .6, .48)[g]:
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
                wait = (1.9, 1.45, 1.05)[g]
                if e.clock > wait:
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
            if e.clock > 1.8:
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
        self.wave_time += dt
        while self.siren_due and self.siren_due[0] <= self.wave_time:
            self.siren_due.pop(0)
            self.events.append('siren')
        self.food_time += dt
        self.update_cat(dt,keys)
        if 'shoot' in keys:
            self.shoot()
        while self.spawn_queue and self.spawn_queue[0][0] <= self.wave_time:
            _, kind = self.spawn_queue.pop(0)
            self.spawn_enemy(kind)
        if self.food_time >= self.spec['duration']/2:
            self.food_time -= self.spec['duration']/2
            self.spawn_food(4)
        if self.bandage_due is not None and self.time >= self.bandage_due:
            self.items.append(Item(480,BALANCE['ground']+18,kind='bandage',state='SPAWN'))
            self.bandage_due = None
        for e in self.enemies:
            self.update_enemy(e,dt)
        for p in self.projectiles:
            p.clock += dt
            old_x,old_y = p.x,p.y
            if p.target is None or not p.target.targetable or not any(e is p.target for e in self.enemies):
                p.target = self.nearest_enemy(p.x,p.y)
            if p.target is not None:
                p.dx,p.dy = direction_to(p.x,p.y,p.target)
            p.x += p.dx*BALANCE['projectile_speed']*dt
            p.y += p.dy*BALANCE['projectile_speed']*dt
            p.enter('FLY',reset_clock=False)
            hits = [(t,e) for e in self.enemies if e.exposed and (t:=segment_hit(old_x,old_y,p.x,p.y,e.box(5))) is not None]
            if hits:
                _, e = min(hits,key=lambda pair:pair[0])
                killed = e.damage()
                p.enter('HIT')
                self.events.append('enemy_hit')
                if killed:
                    self.kill_score += (10,15,25)[e.grade]
                    self.events.append('enemy_death')
            elif not 0 <= p.x <= 960 or not BALANCE['ground'] <= p.y <= 560 or p.clock > 2:
                p.enter('DESPAWN')
        self.projectiles = [p for p in self.projectiles if p.state not in ('HIT','DESPAWN')]
        self.enemies = [e for e in self.enemies if not(e.state == 'DEAD' and e.clock > .45)]
        c = self.cat
        for i in self.items:
            i.clock += dt
            if i.state == 'SPAWN' and i.clock > .15:
                i.enter('IDLE')
            if math.hypot(i.x-c.x,i.y-c.y-18) < 35:
                if i.kind == 'churu':
                    c.ammo = min(BALANCE['ammo_max'],c.ammo+1)
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
                if e.exposed and not e.spawn_grace and segment_hit(c.x,c.y+24,c.x,c.y+24,e.box(13)) is not None:
                    c.hp -= 1
                    c.invincible = BALANCE['invincible_seconds']
                    self.events.append('hurt')
                    if c.hp <= 0:
                        self.begin_death()
                    break
        self.trails = [t for t in self.trails if self.time-t[3] < .23]
        for achievement in ACHIEVEMENTS:
            if 'species' not in achievement:
                continue
            species,needed,skin = achievement['species'],achievement['count'],achievement['skin_id']
            if skin not in self.unlocked and sum(e.species == species and e.alive and 0 <= e.x <= 960 and 0 <= e.y <= 560 for e in self.enemies) >= needed:
                self.unlocked.add(skin)
                self.notices.append((skin,self.time))
                self.events.append('unlock')
        cleared_early = not self.spawn_queue and not any(e.alive for e in self.enemies)
        if self.mode == 'PLAYING' and (cleared_early or self.wave_time+1e-8 >= self.spec['duration']):
            self.completed += 1
            if self.wave == len(WAVES):
                self.clear_run()
                self.unlocked.add('rainbow_clear')
                self.events.append('clear')
            else:
                self.wave += 1
                self.start_wave()

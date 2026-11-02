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
        self.spawn_queue,self.siren_due = [],[]


    @property
    def spec(self):
        return WAVES[self.wave-1]


    @property
    def score(self):
        return self.completed * 100 + int(self.time * 2) + self.kill_score + (50000 if self.mode == 'CLEAR' else 0)


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


    def tick(self,dt,keys):
        self.time += dt
        self.wave_time += dt
        self.update_cat(dt,keys)



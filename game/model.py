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



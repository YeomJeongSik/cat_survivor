"""Time-based endless spawn rules and bounded, immutable-at-spawn enemy stats."""
from bisect import bisect_right
import json
import math
from pathlib import Path

SETTINGS = json.loads((Path(__file__).resolve().parents[1]/'config/endless.json').read_text(encoding='utf-8'))


def validate_settings(data):
    phases,limits,monsters=data['phases'],data['limits'],data['monsters']
    starts=[phase['start'] for phase in phases]
    if not starts or starts[0]!=0 or any(not math.isfinite(t) or t<0 for t in starts) or any(a>=b for a,b in zip(starts,starts[1:])):
        raise ValueError('Difficulty times must start at zero and increase')
    for key in ('warning_seconds','initial_spawn_delay','food_interval','bandage_interval','bandage_warning_seconds','cycle_seconds'):
        if not math.isfinite(data[key]) or data[key]<=0:
            raise ValueError('Timing must be finite and positive')
    if any(not math.isfinite(value) or value<=0 for value in limits.values()):
        raise ValueError('Limits must be finite and positive')
    for spec in monsters.values():
        if any(not math.isfinite(v) or v<=0 for v in spec.values()) or spec['hp']>spec['max_hp'] or spec['min_attack_interval']>spec['attack_interval']:
            raise ValueError('Invalid monster bounds')
    for phase in phases:
        if any(not math.isfinite(phase[k]) or phase[k]<=0 for k in ('spawn_interval','cap','hp_multiplier','attack_rate','reward_multiplier')):
            raise ValueError('Invalid difficulty value')
        if phase['grade'] not in (0,1,2):
            raise ValueError('Unknown visual grade')
    for weights in [p['weights'] for p in phases]+data['combinations']:
        if not weights or any(k not in monsters or not math.isfinite(v) or v<=0 for k,v in weights.items()):
            raise ValueError('Invalid monster combination')
    if not data['combinations'] or data['warning_seconds']>=min([b-a for a,b in zip(starts,starts[1:])]+[data['cycle_seconds']]):
        raise ValueError('Warning must fit before the next change')


validate_settings(SETTINGS)
STARTS = tuple(p['start'] for p in SETTINGS['phases'])


def difficulty_at(seconds):
    if not math.isfinite(seconds) or seconds<0:
        raise ValueError('Survival time must be finite and nonnegative')
    index=bisect_right(STARTS,seconds+1e-9)-1
    phase=SETTINGS['phases'][index]
    limits=SETTINGS['limits']
    rules={**phase,
           'spawn_interval':max(limits['min_spawn_interval'],phase['spawn_interval']),
           'cap':min(limits['max_alive'],phase['cap']),
           'hp_multiplier':min(limits['hp_multiplier'],phase['hp_multiplier']),
           'attack_rate':min(limits['attack_rate'],phase['attack_rate']),
           'reward_multiplier':min(limits['reward_multiplier'],phase['reward_multiplier'])}
    if index+1<len(STARTS):
        rules['next_change']=STARTS[index+1]
    else:
        cycle=math.floor((seconds-phase['start']+1e-9)/SETTINGS['cycle_seconds'])
        combinations=SETTINGS['combinations']
        rules['weights']=combinations[cycle%len(combinations)]
        rules['next_change']=phase['start']+(cycle+1)*SETTINGS['cycle_seconds'] if len(combinations)>1 else math.inf
        if cycle:
            rules['warning']='새 적 조합'
    return rules


def monster_stats(species,rules):
    spec=SETTINGS['monsters'][species]
    return {
        'max_hp':min(spec['max_hp'],spec['hp']*rules['hp_multiplier']),
        'attack_interval':max(spec['min_attack_interval'],spec['attack_interval']/rules['attack_rate']),
        'warning_seconds':max(SETTINGS['limits']['min_warning_seconds'],.6/rules['attack_rate']),
        'exp_reward':min(spec['max_exp'],math.floor(spec['exp']*rules['reward_multiplier'])),
        'gold_reward':min(spec['max_gold'],math.floor(spec['gold']*rules['reward_multiplier'])),
        'grade':rules['grade'],
    }

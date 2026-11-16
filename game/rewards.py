"""Run settlement math, independent of rendering and disk writes."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
import json
import math
from pathlib import Path

RULES=json.loads((Path(__file__).resolve().parents[1]/'config/rewards.json').read_text(encoding='utf-8'))


def level_cost(level):
    return RULES['level_exp_base']+(level-1)*RULES['level_exp_growth']


def bonus_percent(seconds, kind):
    return next((step['percent'] for step in reversed(RULES[kind+'_bonuses']) if seconds>=step['seconds']),100)


def initial_character():
    return dict(level=1,exp=0,skill_points=0)


def validate_progress(profile):
    if type(profile['gold']) is not int or profile['gold']<0:
        raise ValueError('Invalid saved GOLD')
    if not isinstance(profile['characters'],dict) or 'nabi' not in profile['characters']:
        raise ValueError('Invalid saved characters')
    for character in profile['characters'].values():
        level,exp,points=character['level'],character['exp'],character['skill_points']
        if type(level) is not int or not 1<=level<=RULES['max_level']:
            raise ValueError('Invalid saved level')
        if type(exp) not in (int,float) or not math.isfinite(exp) or exp<0 or exp>=(level_cost(level) if level<50 else 1):
            raise ValueError('Invalid saved EXP')
        if level==50 and exp!=0:
            raise ValueError('Maximum-level EXP must be zero')
        if type(points) is not int or not 0<=points<=level-1+(level==50):
            raise ValueError('Invalid saved skill points')
    if not isinstance(profile['settled_runs'],dict):
        raise ValueError('Invalid settlement receipts')
    for run_id,receipt in profile['settled_runs'].items():
        if not isinstance(run_id,str) or not isinstance(receipt,dict) or receipt.get('run_id')!=run_id:
            raise ValueError('Invalid settlement receipt')


def settle_run(profile,world):
    if world.mode!='GAME_OVER' or world.end_reason!='death':
        raise ValueError('Only a completed death can settle rewards')
    if not world.run_id or world.character_id not in profile['characters']:
        raise ValueError('Unknown run or character')
    if type(world.run_exp) is not int or type(world.run_gold) is not int or min(world.run_exp,world.run_gold)<0:
        raise ValueError('Run rewards must be nonnegative integers')
    if not math.isfinite(world.time) or world.time<0:
        raise ValueError('Invalid survival time')
    character=profile['characters'][world.character_id]
    level=before_level=character['level']
    exp=Decimal(str(character['exp']))
    exp_percent=bonus_percent(world.time,'exp')
    gold_percent=bonus_percent(world.time,'gold')
    boosted=Decimal(world.run_exp)*exp_percent/100
    remaining=boosted
    points=0
    while level<RULES['max_level']:
        used=min(remaining,Decimal(level_cost(level))-exp)
        exp+=used
        remaining-=used
        if exp<level_cost(level):
            break
        level+=1
        exp=Decimal(0)
        points+=1+(level==RULES['max_level'])
    converted=int((remaining*Decimal(RULES['exp_to_gold'])).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    combat_gold=int((Decimal(world.run_gold)*gold_percent/100).to_integral_value(rounding=ROUND_FLOOR))
    result=dict(run_id=world.run_id,character_id=world.character_id,survival_time=world.time,
                raw_exp=world.run_exp,raw_gold=world.run_gold,exp_percent=exp_percent,gold_percent=gold_percent,
                applied_exp=float(boosted-remaining),overflow_exp=float(remaining),converted_gold=converted,
                combat_gold=combat_gold,gold_gained=combat_gold+converted,level_before=before_level,
                level_after=level,exp_after=float(exp),skill_points_gained=points)
    result['character_after']=dict(level=level,exp=float(exp),skill_points=character['skill_points']+points)
    return result


assert RULES['max_level']==50 and RULES['level_exp_base']>0 and RULES['level_exp_growth']>=0
assert Decimal(RULES['exp_to_gold']).is_finite() and Decimal(RULES['exp_to_gold'])>=0
for kind in ('exp','gold'):
    steps=RULES[kind+'_bonuses']
    assert steps and all(math.isfinite(s['seconds']) and s['seconds']>=0 and 101<=s['percent']<=150 for s in steps)
    assert all(a['seconds']<b['seconds'] and a['percent']<=b['percent'] for a,b in zip(steps,steps[1:]))
assert RULES['gold_bonuses'][0]['seconds']>RULES['exp_bonuses'][0]['seconds']

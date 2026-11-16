"""Deterministic profile operations; one journaled request commits atomically."""
from .rewards import initial_character, grow_character
from .achievements import ACHIEVEMENTS, progress
from .equipment import apply_equipment


def apply_operation(profile,operation,args,rng,request_id,gacha_pool=None):
    if operation=='buy_character':
        if args.get('character_id')!='black':
            raise ValueError('Unknown character')
        if 'black' in profile['characters']:
            raise ValueError('Already owned')
        if profile['gold']<500:
            raise ValueError('GOLD가 부족합니다.')
        profile['gold']-=500
        profile['characters']['black']=initial_character()
        return {'message':'흑냥이를 구매했습니다.'}
    if operation=='claim_achievement':
        achievement=next((a for a in ACHIEVEMENTS if a['id']==args.get('achievement_id')),None)
        key=args.get('character_id')
        if achievement is None or key not in profile['characters']:
            raise ValueError('Unknown achievement or character')
        if achievement['id'] in profile['claimed_achievements']:
            raise ValueError('이미 수령한 업적입니다.')
        if progress(profile,achievement)<achievement['target']:
            raise ValueError('업적 조건을 아직 달성하지 못했습니다.')
        growth=grow_character(profile['characters'][key],achievement['exp'])
        profile['characters'][key]=growth['character']
        gold=achievement['gold']+growth['converted_gold']
        profile['gold']+=gold
        profile['claimed_achievements'][achievement['id']]=dict(character_id=key,exp=growth['applied_exp'],gold=gold)
        return dict(message='업적 보상을 수령했습니다.',exp=growth['applied_exp'],gold=gold)
    return apply_equipment(profile,operation,args,rng,request_id,gacha_pool=gacha_pool)

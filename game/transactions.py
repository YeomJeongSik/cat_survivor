"""Deterministic profile operations; one journaled request commits atomically."""
from .rewards import initial_character


def apply_operation(profile,operation,args,rng,request_id):
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
    raise ValueError('Unknown operation')

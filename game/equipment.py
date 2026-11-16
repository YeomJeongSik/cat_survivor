"""Shared equipment definitions, bounded stat calculations and save validation."""
import json
import math
from pathlib import Path

RULES=json.loads((Path(__file__).resolve().parents[1]/'config/equipment.json').read_text(encoding='utf-8'))
DEFINITIONS={f'{kind}_{rarity}':dict(type=kind,rarity=rarity) for kind in RULES['types'] for rarity in RULES['rarities']}


def definition(item):
    return DEFINITIONS[item['definition']]


def item_name(item):
    spec=definition(item)
    return RULES['rarities'][spec['rarity']]['name']+' '+RULES['types'][spec['type']]['name']


def stat_value(item):
    spec=definition(item)
    rarity=RULES['rarities'][spec['rarity']]
    return round(RULES['types'][spec['type']]['base']*rarity['multiplier']*
                 (1+item['enhancement']*rarity['enhance_step']+item['stacks']*RULES['stack_step']),6)


def enhancement_offer(item):
    rarity=RULES['rarities'][definition(item)['rarity']]
    step=item['enhancement']
    return math.ceil(rarity['cost']*(step+1)**1.25),max(5,rarity['chance']-4*step)


def material_allowed(profile,target,material):
    return (material['id']!=target['id'] and material['definition']==target['definition'] and
            not material['locked'] and material['id'] not in profile['equipment_slots'] and
            material['enhancement']==0 and material['stacks']==0)


def bonuses(profile):
    result=dict.fromkeys(RULES['caps'],0.)
    inventory={i['id']:i for i in profile.get('items',[])}
    for key in profile.get('equipment_slots',[])[:profile.get('unlocked_slots',1)]:
        if key in inventory:
            item=inventory[key]
            stat=RULES['types'][definition(item)['type']]['stat']
            result[stat]+=stat_value(item)
    return {key:min(value,RULES['caps'][key]) for key,value in result.items()}


def validate_equipment(profile):
    if not isinstance(profile['items'],list) or type(profile['unlocked_slots']) is not int or not 1<=profile['unlocked_slots']<=3:
        raise ValueError('Invalid equipment save')
    ids=[]
    for item in profile['items']:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not isinstance(item.get('definition'),str) or item['definition'] not in DEFINITIONS:
            raise ValueError('Unknown equipment')
        for field in ('enhancement','stacks'):
            if type(item.get(field)) is not int or not 0<=item[field]<=10:
                raise ValueError('Invalid equipment growth')
        if type(item.get('locked')) is not bool:
            raise ValueError('Invalid equipment lock')
        ids.append(item['id'])
    slots=profile['equipment_slots']
    if len(ids)!=len(set(ids)) or not isinstance(slots,list) or len(slots)!=3 or any(key is not None and not isinstance(key,str) for key in slots):
        raise ValueError('Duplicate equipment or invalid slots')
    equipped=[key for key in slots if key is not None]
    if len(equipped)!=len(set(equipped)) or any(key not in ids for key in equipped) or any(key is not None for key in slots[profile['unlocked_slots']:]):
        raise ValueError('Invalid equipped item')


def apply_equipment(profile,operation,args,rng,request_id):
    if operation=='gacha':
        if profile['gold']<RULES['gacha_price']:
            raise ValueError('GOLD가 부족합니다.')
        rarities=list(RULES['rarities'])
        rarity=rng.choices(rarities,weights=[RULES['rarities'][key]['weight'] for key in rarities])[0]
        kind=rng.choice(list(RULES['types']))
        item=dict(id=request_id+':item',definition=kind+'_'+rarity,enhancement=0,stacks=0,locked=False)
        profile['gold']-=RULES['gacha_price']
        profile['items'].append(item)
        return dict(message=item_name(item)+' 획득!',item_id=item['id'])
    if operation=='unlock_slot':
        slot=args.get('slot')
        if type(slot) is not int or slot!=profile['unlocked_slots'] or slot>=3:
            raise ValueError('순서대로 다음 슬롯만 해금할 수 있습니다.')
        cost=RULES['slot_costs'][slot]
        if profile['gold']<cost:raise ValueError('GOLD가 부족합니다.')
        profile['gold']-=cost
        profile['unlocked_slots']+=1
        return dict(message='장비 슬롯을 해금했습니다.')
    if operation=='unequip':
        slot=args.get('slot')
        if type(slot) is not int or not 0<=slot<profile['unlocked_slots']:
            raise ValueError('잠긴 슬롯입니다.')
        if profile['equipment_slots'][slot] is None:raise ValueError('빈 슬롯입니다.')
        profile['equipment_slots'][slot]=None
        return dict(message='장비를 해제했습니다.')
    item=next((item for item in profile['items'] if item['id']==args.get('item_id')),None)
    if item is None:raise ValueError('장비를 찾을 수 없습니다.')
    if operation=='equip':
        slot=args.get('slot')
        if type(slot) is not int or not 0<=slot<profile['unlocked_slots']:raise ValueError('잠긴 슬롯입니다.')
        profile['equipment_slots']=[None if key==item['id'] else key for key in profile['equipment_slots']]
        profile['equipment_slots'][slot]=item['id']
        return dict(message='장비를 장착했습니다.')
    if operation=='lock':
        item['locked']=not item['locked']
        return dict(message='장비를 잠갔습니다.' if item['locked'] else '잠금을 해제했습니다.')
    if operation=='enhance':
        if item['enhancement']>=10:raise ValueError('최대 강화입니다.')
        cost,chance=enhancement_offer(item)
        if profile['gold']<cost:raise ValueError('GOLD가 부족합니다.')
        profile['gold']-=cost
        success=rng.random()*100<chance
        if success:item['enhancement']+=1
        return dict(message='강화 성공!' if success else '강화 실패 · 단계 유지',success=success,cost=cost)
    if operation=='stack':
        material=next((i for i in profile['items'] if i['id']==args.get('material_id')),None)
        if item['stacks']>=10:raise ValueError('최대 중첩입니다.')
        if material is None or not material_allowed(profile,item,material):raise ValueError('사용할 수 없는 중첩 재료입니다.')
        item['stacks']+=1
        profile['items'].remove(material)
        return dict(message='중첩이 1 증가했습니다.')
    if operation=='sell':
        if item['locked'] or item['id'] in profile['equipment_slots']:raise ValueError('장착·잠금 장비는 판매할 수 없습니다.')
        gold=RULES['rarities'][definition(item)['rarity']]['sale']
        profile['items'].remove(item)
        profile['gold']+=gold
        return dict(message=f'{gold} GOLD에 판매했습니다.',gold=gold)
    raise ValueError('Unknown equipment operation')


assert sum(r['weight'] for r in RULES['rarities'].values())==100
for lower,upper in zip(list(RULES['rarities'].values()),list(RULES['rarities'].values())[1:]):
    assert lower['multiplier']*(1+10*lower['enhance_step']+10*RULES['stack_step'])<=upper['multiplier']*(1+6*upper['enhance_step'])

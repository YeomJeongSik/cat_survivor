"""Lobby layout and panel state; economic actions belong to later features."""
from uuid import uuid4
import pico2d as p
from .characters import CHARACTERS
from .visuals import REWARD_ART, NEW_BADGE
from .gacha import GachaReveal
from .achievements import ACHIEVEMENTS, progress
from .equipment import RULES as GEAR, item_name, definition, stat_value, enhancement_offer, material_allowed, bonuses
from .rewards import level_cost

INK=(48,45,52)
PANEL=(100,100,860,552)
CLOSE=(696,492,836,526)
CONTROLS=(275,190,685,490)
MENU={
    'character':('캐릭터 선택',(630,480,920,526)),
    'skills':('스킬 트리',(630,418,920,464)),
    'equipment':('장비',(630,356,920,402)),
    'shop':('상점',(630,294,920,340)),
    'achievements':('업적',(630,232,920,278)),
}
SLOTS=[(52+101*i,264,132+101*i,310) for i in range(3)]


def contains(rect,x,y):
    return rect[0]<=x<=rect[2] and rect[1]<=y<=rect[3]


def rounded_box(rect,color,radius=8):
    left,bottom,right,top=rect
    p.draw_rectangle(left+radius,bottom,right-radius,top,*color,filled=True)
    p.draw_rectangle(left,bottom+radius,right,top-radius,*color,filled=True)
    for x in (left+radius,right-radius):
        for y in (bottom+radius,top-radius):
            p.draw_circle(x,y,radius,*color,filled=True)


class Lobby:
    def __init__(self):
        self.panel=None
        self.preview='nabi'
        self.error=''
        self.message=''
        self.confirm=None
        self.request_id=None
        self.page=0
        self.item_id=None
        self.material_target=None
        self.slot=0
        self.reveal=None

    @property
    def bounds(self):
        if self.reveal:
            return self.reveal.BOUNDS
        return (210,170,750,470) if self.confirm else CONTROLS if self.panel=='controls' else (40,70,920,552) if self.panel=='equipment' else PANEL

    def open(self,app,name):
        if app.store.pending:
            return
        if name not in (*MENU,'settings','controls'):
            return
        self.close(app)
        self.panel=name
        self.message=''
        self.page=0
        self.material_target=None
        app.buttons=[]
        self.preview=app.store.profile['selected_character_id']

    def close(self,app):
        if self.reveal:
            if self.reveal.ready:
                self.reveal=None
                app.buttons=[]
            return
        if app.store.pending:
            return
        if self.confirm:
            self.confirm=None
            app.buttons=[]
            return
        if app.dragging:
            app.dragging=None
            app.save()
        self.panel=None
        self.error=''
        app.buttons=[]
        app.keys.clear()

    def update(self,dt):
        if self.reveal:
            self.reveal.update(dt)

    def ask(self,app,operation,args,lines):
        self.confirm=dict(operation=operation,args=args,lines=lines)
        self.request_id=None
        app.buttons=[]

    def operate(self,app):
        pending=app.store.pending
        command=pending or self.confirm
        if not command:
            return
        self.request_id=pending.get('id') if pending else self.request_id or str(uuid4())
        try:
            result=app.store.transact(command['operation'],command['args'],self.request_id)
        except (OSError,ValueError) as exc:
            self.error=str(exc)
        else:
            self.message=result['message']
            if command['operation']=='gacha' and result.get('items'):
                self.reveal=GachaReveal(result)
                self.message=''
            app.error=''
            self.error=''
            self.confirm=None
            self.request_id=None
        app.buttons=[]

    def action(self,app,args):
        if self.reveal:
            if args[0]=='reveal_close':
                self.close(app)
            return
        if args[0]=='page':
            self.page=max(0,self.page+args[1])
            app.buttons=[]
        elif args[0]=='claim':
            achievement=next(a for a in ACHIEVEMENTS if a['id']==args[1])
            self.ask(app,'claim_achievement',{'achievement_id':args[1],'character_id':app.store.profile['selected_character_id']},
                     [achievement['name'],f'EXP +{achievement["exp"]} / GOLD +{achievement["gold"]}','EXP는 현재 선택한 캐릭터에게 지급됩니다.'])
        elif args[0]=='gacha':
            count=args[1] if len(args)>1 else 1
            self.ask(app,'gacha',{'count':count},[f'장비를 {count}회 뽑을까요?',f'비용: {GEAR["gacha_price"]*count:,} GOLD','중복 장비도 나옵니다.'])
        elif args[0]=='slot':
            slot=args[1]
            if slot>=app.store.profile['unlocked_slots']:
                self.ask(app,'unlock_slot',{'slot':slot},[f'슬롯 {slot+1}을 해금할까요?',f'비용: {GEAR["slot_costs"][slot]} GOLD'])
            else:
                self.slot=slot
        elif args[0]=='item':
            target=next((i for i in app.store.profile['items'] if i['id']==self.material_target),None)
            material=next(i for i in app.store.profile['items'] if i['id']==args[1])
            if target:
                grown={**target,'stacks':target['stacks']+1}
                self.ask(app,'stack',{'item_id':target['id'],'material_id':material['id']},
                         ['왼쪽 장비 유지 / 오른쪽 재료 소모',
                          f'유지: {item_name(target)} +{target["enhancement"]} / 중첩 {target["stacks"]}',
                          f'소모: {item_name(material)} +0 / 중첩 0',
                          f'중첩 {target["stacks"]} → {grown["stacks"]} · 효과 {stat_value(target)*100:.2f}% → {stat_value(grown)*100:.2f}%'])
                self.material_target=None
            else:
                self.item_id=args[1]
                if material.get('is_new',False):
                    try:
                        app.store.transact('mark_seen',{'item_id':material['id']})
                    except (OSError,ValueError) as exc:
                        self.error=str(exc)
        elif args[0]=='gear':
            self.gear_action(app,args[1])
        elif args[0]=='cancel_material':
            self.material_target=None
        elif args[0]=='confirm':
            self.operate(app)
        elif args[0]=='cancel':
            if not app.store.pending:
                self.confirm=None
                app.buttons=[]
        elif args[0]=='buy_black':
            self.ask(app,'buy_character',{'character_id':'black'},['흑냥이를 구매할까요?','비용: 500 GOLD','구매 후 캐릭터 창에서 선택할 수 있습니다.'])
        elif args[0]=='open':
            self.open(app,args[1])
        elif args[0]=='close':
            self.close(app)
        elif args[0]=='preview' and self.panel=='character':
            if args[1] in app.store.profile['characters'] and args[1] in CHARACTERS:
                self.preview=args[1]
        elif args[0]=='select' and self.panel=='character':
            try:
                app.store.select_character(self.preview)
            except (OSError,ValueError) as exc:
                self.error=f'선택 저장 실패: {exc}'
            else:
                self.close(app)

    def draw(self,app):
        art=app.art
        profile=app.store.profile
        selected=profile['selected_character_id']
        info=CHARACTERS[selected]
        character=profile['characters'][selected]
        app.background(True)
        app.panel(28,566,932,616)
        art.text('산책 준비',48,592,24,INK)
        REWARD_ART['gold'].draw(art,694,592,app.ui_clock,scale=1.4)
        art.text(f'GOLD   {profile["gold"]:,}',720,592,20,INK)
        app.panel(28,238,358,536)
        app.cat(110,440,'idle',app.ui_clock,skin=info['skin'],scale=2.)
        art.text(info['name'],196,493,24,INK)
        art.text(f'Lv. {character["level"]}',196,460,21,INK)
        maximum=character['level']==50
        exp=character['exp']
        label='EXP  MAX' if maximum else f'EXP  {exp:g} / {level_cost(character["level"])}'
        REWARD_ART['exp'].draw(art,64,404,app.ui_clock,scale=1.3)
        art.text(label,88,404,16,INK)
        p.draw_rectangle(52,367,334,381,*INK,filled=True)
        p.draw_rectangle(54,369,332,379,208,197,163,filled=True)
        ratio=1. if maximum else exp/level_cost(character['level'])
        if ratio:
            p.draw_rectangle(54,369,54+278*ratio,379,84,141,104,filled=True)
        art.text(f'미사용 스킬 포인트  {character["skill_points"]}',52,333,16,INK)
        app.buttons.append(((46,317,340,351),('lobby','open','skills'),True))
        inventory={item['id']:item for item in profile['items']}
        for i,rect in enumerate(SLOTS):
            rounded_box(rect,(240,207,139) if contains(rect,*app.mouse) else (231,221,192))
            x=(rect[0]+rect[2])/2
            equipped=inventory.get(profile['equipment_slots'][i])
            label=GEAR['types'][definition(equipped)['type']]['name'] if equipped else '빈 슬롯' if i<profile['unlocked_slots'] else '잠금'
            art.text(label,x,287,13,INK,True)
            app.buttons.append((rect,('lobby','open','equipment'),True))
        app.cat(480,225,'groom' if app.ui_clock%8>4 else 'idle',app.ui_clock,skin=info['skin'],scale=3.)
        art.outlined_text(info['name'],480,193,24)
        art.outlined_text(info['features'],480,159,15)
        for name,(label,rect) in MENU.items():
            app.button(label,rect,('lobby','open',name))
        app.button('출전하기',(630,80,920,128),'start')
        app.button('설정',(30,84,165,126),('lobby','open','settings'))
        app.button('키 설명',(185,84,320,126),('lobby','open','controls'))
        app.button('타이틀',(30,28,165,70),'title')
        art.outlined_text('Enter  출전하기',775,51,14)
        if app.store.pending:
            self.panel=self.panel or 'shop'
            self.confirm=dict(operation=app.store.pending['operation'],args=app.store.pending['args'],lines=['저장이 끝나지 않은 거래가 있습니다.','같은 결과로 저장을 재시도합니다.'])
        if self.panel:
            app.buttons=[]
            if self.reveal:
                self.reveal.draw(app)
                return
            if self.panel=='controls':
                app.controls_panel()
                return
            self.draw_panel(app)
            if self.message or self.error:
                art.text(('저장 실패 · 확인 버튼으로 재시도' if app.store.pending else (self.error or self.message))[:38],480,150 if self.panel=='equipment' else 115,14,INK,True)
            if self.confirm:
                app.panel(210,170,750,470)
                app.buttons=[]
                art.text('거래 확인',480,430,24,INK,True)
                for i,line in enumerate(self.confirm['lines']):
                    art.text(line,480,382-i*32,17,INK,True)
                app.button('취소',(290,205,425,247),('lobby','cancel'),not bool(app.store.pending))
                app.button('저장 재시도' if app.store.pending else '확인',(535,205,670,247),('lobby','confirm'))

    def draw_panel(self,app):
        art=app.art
        profile=app.store.profile
        selected=profile['selected_character_id']
        info=CHARACTERS[selected]
        character=profile['characters'][selected]
        title=MENU[self.panel][0] if self.panel in MENU else '설정'
        app.panel(*( (40,70,920,552) if self.panel=='equipment' else PANEL))
        art.text(title,124,520,24,INK)
        app.button('닫기',CLOSE,('lobby','close'))
        if self.panel=='character':
            p.draw_line(480,195,480,482,188,171,133)
            for index,key in enumerate(k for k in profile['characters'] if k in CHARACTERS):
                rect=(132,378-index*110,456,474-index*110)
                color=(240,207,139) if key==self.preview else (231,221,192)
                if contains(rect,*app.mouse):
                    color=(247,219,157)
                rounded_box(rect,color)
                y=(rect[1]+rect[3])/2
                app.cat(180,y-18,'idle',app.ui_clock,skin=CHARACTERS[key]['skin'])
                art.text(CHARACTERS[key]['name'],240,y+14,19,INK)
                art.text('출전 중' if key==selected else '미리보기',240,y-15,14,INK)
                app.buttons.append((rect,('lobby','preview',key),True))
            preview=CHARACTERS[self.preview]
            growth=profile['characters'][self.preview]
            art.text(preview['name'],510,472,23,INK)
            for i,line in enumerate(preview['story']):
                art.text(line,510,420-i*27,16,INK)
            art.text(preview['features'],510,348,16,INK)
            art.text(f'Lv. {growth["level"]}   스킬 포인트 {growth["skill_points"]}',510,305,16,INK)
            app.button('선택하기',(525,130,815,178),('lobby','select'))
            if self.error:
                art.text('선택 저장 실패 · 선택하기로 재시도',480,195,16,(151,44,44),True)
        elif self.panel=='skills':
            art.text(f'{info["name"]}   Lv. {character["level"]}',132,451,22,INK)
            art.text(f'미사용 스킬 포인트  {character["skill_points"]}',132,409,18,INK)
            art.text('스킬 디자인 준비 중',480,300,24,INK,True)
            art.text('스킬 구성이 정해지면 이곳에서 포인트를 사용할 수 있습니다.',480,255,17,INK,True)
        elif self.panel=='equipment':
            self.draw_equipment(app)
        elif self.panel=='shop':
            REWARD_ART['gold'].draw(art,113,454,app.ui_clock,scale=1.1)
            art.text(f'보유 GOLD   {profile["gold"]:,}',132,454,18,INK)
            if 'black' not in profile['characters']:
                art.text('흑냥이',310,423,24,INK,True)
                art.text('근접 캐릭터',310,397,17,INK,True)
                app.cat(310,284,'idle',app.ui_clock,skin=CHARACTERS['black']['skin'],scale=3.)
                art.text('500 GOLD',310,257,21,INK,True)
                app.button('구매하기',(168,193,453,235),('lobby','buy_black'),profile['gold']>=500)
            else:
                art.text('모든 캐릭터 보유',310,355,21,INK,True)
            art.text('장비 뽑기',650,423,24,INK,True)
            art.draw('ui/equipment_chest.png',650,340,160,144)
            art.text('150 GOLD',650,257,21,INK,True)
            app.button('1회 뽑기',(508,193,793,235),('lobby','gacha'),profile['gold']>=150)
            app.button('10연뽑 · 1,500 G',(508,139,793,181),('lobby','gacha',10),profile['gold']>=GEAR['gacha_price']*10)
            art.text('Common 70% · Rare 23% · Unique 6% · Legendary 1%',480,480,14,INK,True)
        elif self.panel=='achievements':
            self.page=min(self.page,(len(ACHIEVEMENTS)-1)//5)
            for i,achievement in enumerate(ACHIEVEMENTS[self.page*5:self.page*5+5]):
                y=442-i*55
                claimed=achievement['id'] in profile['claimed_achievements']
                current=progress(profile,achievement)
                art.text(achievement['name'],132,y,18,INK)
                art.text(f'{achievement["description"]}  {current:g}/{achievement["target"]}',132,y-23,14,INK)
                reward=f'EXP +{achievement["exp"]}' if achievement['exp'] else f'GOLD +{achievement["gold"]}'
                art.text(reward,540,y-8,15,INK)
                app.button('수령 완료' if claimed else '수령',(690,y-25,825,y+17),('lobby','claim',achievement['id']),not claimed and current>=achievement['target'])
            app.button('이전',(170,140,305,182),('lobby','page',-1),self.page>0)
            app.button('다음',(655,140,790,182),('lobby','page',1),(self.page+1)*5<len(ACHIEVEMENTS))
        elif self.panel=='settings':
            app.volume('bgm_volume',352,365)
            app.volume('sfx_volume',352,260)


    def gear_action(self,app,operation):
        profile=app.store.profile
        item=next((i for i in profile['items'] if i['id']==self.item_id),None)
        if operation=='unequip':
            self.ask(app,'unequip',{'slot':self.slot},[f'슬롯 {self.slot+1}의 장비를 해제할까요?'])
            return
        if not item:return
        if operation=='stack_pick':
            self.material_target=item['id']
            self.page=0
            app.buttons=[]
            return
        args={'item_id':item['id']}
        if operation=='equip':
            args['slot']=self.slot
            lines=[f'슬롯 {self.slot+1}에 장착할까요?',item_name(item),'기존 장착 장비는 인벤토리에 남습니다.']
        elif operation=='enhance':
            cost,chance=enhancement_offer(item)
            grown={**item,'enhancement':item['enhancement']+1}
            lines=[item_name(item),f'강화 +{item["enhancement"]} → +{grown["enhancement"]} / 성공률 {chance}%',
                   f'비용: {cost} GOLD · 실패 시 단계 유지',f'효과 {stat_value(item)*100:.2f}% → {stat_value(grown)*100:.2f}%']
        elif operation=='sell':
            gold=GEAR['rarities'][definition(item)['rarity']]['sale']
            lines=[item_name(item),f'{gold} GOLD에 판매할까요?','강화·중첩 비용은 판매가에 추가되지 않습니다.']
        elif operation=='lock':
            self.ask(app,'lock',args,['장비 잠금 설정 변경'])
            self.operate(app)
            return
        else:return
        self.ask(app,operation,args,lines)

    def draw_equipment(self,app):
        profile=app.store.profile
        art=app.art
        inventory=profile['items']
        by_id={i['id']:i for i in inventory}
        self.slot=min(self.slot,profile['unlocked_slots']-1)
        for slot in range(3):
            left=100+slot*250
            rect=(left,460,left+220,490)
            rounded_box(rect,(240,207,139) if slot==self.slot else (231,221,192))
            item=by_id.get(profile['equipment_slots'][slot])
            text=f'{slot+1} · '+(GEAR['types'][definition(item)['type']]['name'] if item else '빈 슬롯' if slot<profile['unlocked_slots'] else f'잠금 {GEAR["slot_costs"][slot]} G')
            art.text(text,left+110,475,15,INK,True)
            app.buttons.append((rect,('lobby','slot',slot),slot<=profile['unlocked_slots']))
        target=by_id.get(self.material_target)
        shown=[item for item in inventory if material_allowed(profile,target,item)] if target else inventory
        self.page=min(self.page,max(0,(len(shown)-1)//5))
        art.text('소모할 재료 선택' if target else f'보유 장비  {len(inventory)}개',100,435,18,INK)
        for index,item in enumerate(shown[self.page*5:self.page*5+5]):
            y=392-index*42
            rect=(100,y-18,490,y+18)
            rounded_box(rect,(240,207,139) if item['id']==self.item_id else (231,221,192))
            art.text(item_name(item),112,y+5,16,INK)
            if item.get('is_new',False):
                NEW_BADGE.draw(art,461,y+5,scale=.8)
            status=('잠금 · ' if item['locked'] else '')+('장착 · ' if item['id'] in profile['equipment_slots'] else '')+f'강화 +{item["enhancement"]} / 중첩 {item["stacks"]}'
            art.text(status,112,y-11,12,INK)
            app.buttons.append((rect,('lobby','item',item['id']),True))
        if not shown:
            art.text('사용 가능한 재료가 없습니다.' if target else '상점에서 장비를 뽑아보세요.',295,335,18,INK,True)
        if self.item_id not in by_id:
            self.item_id=shown[0]['id'] if shown else None
        selected=by_id.get(self.item_id)
        if selected:
            spec=definition(selected)
            art.text(item_name(selected),535,435,20,INK)
            art.text(f'{GEAR["types"][spec["type"]]["label"]} +{stat_value(selected)*100:.2f}%',535,403,17,INK)
            art.text(f'강화 +{selected["enhancement"]} / 중첩 {selected["stacks"]}',535,375,16,INK)
            app.button('장착',(540,315,675,357),('lobby','gear','equip'))
            app.button('해제',(705,315,840,357),('lobby','gear','unequip'),profile['equipment_slots'][self.slot] is not None)
            cost,chance=enhancement_offer(selected)
            app.button('강화',(540,260,675,302),('lobby','gear','enhance'),selected['enhancement']<10 and profile['gold']>=cost)
            app.button('중첩',(705,260,840,302),('lobby','gear','stack_pick'),selected['stacks']<10)
            app.button('잠금 해제' if selected['locked'] else '잠금',(540,205,675,247),('lobby','gear','lock'))
            app.button('판매',(705,205,840,247),('lobby','gear','sell'),not selected['locked'] and selected['id'] not in profile['equipment_slots'])
        total=bonuses(profile)
        art.text(f'적용 공격+{total["damage"]*100:.1f}% 이동+{total["move_speed"]*100:.1f}% 대시-{total["dash_reduction"]*100:.1f}%',535,174,12,INK)
        app.button('이전',(100,90,235,132),('lobby','page',-1),self.page>0)
        app.button('다음',(355,90,490,132),('lobby','page',1),(self.page+1)*5<len(shown))
        art.text(f'{self.page+1}/{max(1,(len(shown)+4)//5)}',295,111,16,INK,True)
        if target:
            app.button('재료 선택 취소',(550,90,835,132),('lobby','cancel_material'))

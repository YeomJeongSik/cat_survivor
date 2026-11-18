"""Lobby layout and panel state; economic actions belong to later features."""
from uuid import uuid4
import pico2d as p
from .characters import BLACK_PRICE, CHARACTERS
from .visuals import REWARD_ART, NEW_BADGE, EQUIPMENT_ART
from .gacha import GachaReveal
from .achievements import ACHIEVEMENTS, progress
from .equipment import RULES as GEAR, item_name, definition, stat_value, enhancement_offer, material_allowed, bonuses
from .rewards import level_cost
from .ui import ACCENT, ERROR, FRAME, INK, LINE, PRIMARY, ROW, SECONDARY, SELECTED

PANEL=(100,100,860,552)
CLOSE=(696,492,836,526)
CONTROLS=(275,190,685,490)
SHOP=(28,34,932,608)
SHOP_CATEGORIES={'all':'전체','character':'캐릭터','equipment':'장비'}
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
        self.shop_category='all'

    @property
    def bounds(self):
        if self.reveal:
            return self.reveal.BOUNDS
        if self.confirm:
            return (210,170,750,470)
        if self.panel=='shop':
            return SHOP
        return CONTROLS if self.panel=='controls' else (40,70,920,552) if self.panel=='equipment' else PANEL

    def open(self,app,name):
        if app.store.pending:
            return
        if name not in (*MENU,'settings','controls'):
            return
        self.close(app)
        self.panel=name
        self.message=''
        self.shop_category='all'
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
        if args[0]=='shop_category' and self.panel=='shop' and not self.confirm:
            self.shop_category=args[1]
            app.buttons=[]
        elif args[0]=='page':
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
            self.ask(app,'buy_character',{'character_id':'black'},['흑냥이를 구매할까요?',f'비용: {BLACK_PRICE:,} GOLD','구매 후 캐릭터 창에서 선택할 수 있습니다.'])
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

    def draw_lobby(self,app):
        art=app.art
        profile=app.store.profile
        selected=profile['selected_character_id']
        info=CHARACTERS[selected]
        character=profile['characters'][selected]
        app.panel(28,566,227,616)
        art.text('산책 준비',48,592,24,INK)
        app.panel(664,566,932,616)
        REWARD_ART['gold'].draw(art,694,592,app.ui_clock,scale=1.4)
        art.text(f'GOLD   {profile["gold"]:,}',720,592,20,ACCENT)
        app.panel(28,238,352,536)
        art.text(info['name'],52,489,28,INK)
        art.text(f'Lv. {character["level"]}',263,489,18,INK)
        art.text(info['features'],52,452,15,SECONDARY)
        p.draw_line(52,429,328,429,*LINE)
        maximum=character['level']==50
        exp=character['exp']
        label='EXP  MAX' if maximum else f'EXP  {exp:g} / {level_cost(character["level"])}'
        REWARD_ART['exp'].draw(art,64,404,app.ui_clock,scale=1.3)
        art.text(label,88,404,16,INK)
        p.draw_rectangle(52,371,328,378,*LINE,filled=True)
        ratio=1. if maximum else exp/level_cost(character['level'])
        if ratio:
            p.draw_rectangle(52,371,52+276*ratio,378,*PRIMARY,filled=True)
        art.text(f'미사용 스킬 포인트  {character["skill_points"]}',52,333,16,INK)
        app.buttons.append(((46,317,340,351),('lobby','open','skills'),True))
        inventory={item['id']:item for item in profile['items']}
        for i,rect in enumerate(SLOTS):
            p.draw_rectangle(*rect,*(SELECTED if contains(rect,*app.mouse) else ROW),filled=True)
            x=(rect[0]+rect[2])/2
            equipped=inventory.get(profile['equipment_slots'][i])
            label=GEAR['types'][definition(equipped)['type']]['name'] if equipped else '빈 슬롯' if i<profile['unlocked_slots'] else '잠금'
            if equipped:
                EQUIPMENT_ART.draw(art,equipped,x,294,app.ui_clock,size=28)
                art.text(label,x,272,10,INK,True)
            else:
                art.text(label,x,287,13,INK,True)
            app.buttons.append((rect,('lobby','open','equipment'),True))
        app.cat(483,132,'groom' if app.ui_clock%8>4 else 'idle',app.ui_clock,skin=info['skin'],scale=3.5)
        p.draw_rectangle(871,178,889,526,*FRAME,filled=True)
        p.draw_rectangle(875,182,884,526,107,88,63,filled=True)
        for name,(label,rect) in MENU.items():
            app.button(label,rect,('lobby','open',name),wayfinding=True)
        app.button('출전하기',(630,80,920,128),'start',primary=True)
        app.button('설정',(30,84,165,126),('lobby','open','settings'))
        app.button('키 설명',(185,84,320,126),('lobby','open','controls'))
        app.button('타이틀',(30,28,165,70),'title')
        art.outlined_text('Enter',775,54,14)

    def draw(self,app):
        art=app.art
        app.background()
        if app.store.pending:
            self.panel=self.panel or 'shop'
            self.confirm=dict(operation=app.store.pending['operation'],args=app.store.pending['args'],lines=['저장이 끝나지 않은 거래가 있습니다.','같은 결과로 저장을 재시도합니다.'])
        if self.panel!='shop':
            self.draw_lobby(app)
        if self.panel:
            app.buttons=[]
            if self.reveal:
                self.reveal.draw(app)
                return
            if self.panel=='controls':
                app.controls_panel()
                return
            if self.panel=='shop':
                self.draw_shop(app)
            else:
                self.draw_panel(app)
            if self.message or self.error:
                x,y={'equipment':(480,150),'shop':(577,76)}.get(self.panel,(480,115))
                art.text(('저장 실패 · 확인 버튼으로 재시도' if app.store.pending else (self.error or self.message))[:38],x,y,14,INK,True)
            if self.confirm:
                app.modal(210,170,750,470)
                app.buttons=[]
                art.text('거래 확인',480,430,24,INK,True)
                for i,line in enumerate(self.confirm['lines']):
                    art.text(line,480,382-i*32,17,INK,True)
                app.button('취소',(290,205,425,247),('lobby','cancel'),not bool(app.store.pending))
                app.button('저장 재시도' if app.store.pending else '확인',(535,205,670,247),('lobby','confirm'),primary=True)

    def draw_shop(self,app):
        art=app.art
        profile=app.store.profile
        gold=profile['gold']
        app.shade()
        app.panel(28,34,212,608)
        app.panel(228,538,932,608)
        app.button('‹  로비로',(44,552,196,592),('lobby','close'))
        art.text('상점',252,573,27,INK)
        REWARD_ART['gold'].draw(art,731,573,app.ui_clock,scale=1.3)
        art.text(f'{gold:,} GOLD',753,573,19,ACCENT)
        for i,(category,label) in enumerate(SHOP_CATEGORIES.items()):
            y=474-i*56
            app.button(label,(44,y,196,y+44),('lobby','shop_category',category),
                       primary=self.shop_category==category,wayfinding=True)

        price=GEAR['gacha_price']
        offers=(
            ('character','흑냥이','근접 캐릭터',BLACK_PRICE,('lobby','buy_black')),
            ('equipment','장비 뽑기 ×1','장비 1개',price,('lobby','gacha')),
            ('equipment','장비 뽑기 ×10','장비 10개',price*10,('lobby','gacha',10)),
        )
        visible=[offer for offer in offers if self.shop_category in ('all',offer[0])]
        for i,(category,label,description,cost,action) in enumerate(visible):
            left=228+i*240
            x=left+112
            rect=(left,207,left+224,513)
            owned=category=='character' and 'black' in profile['characters']
            enabled=not owned and gold>=cost
            hovered=enabled and contains(rect,*app.mouse)
            app.panel(*rect)
            p.draw_rectangle(left+10,330,left+214,503,*(SELECTED if hovered else ROW),filled=True)
            if category=='character':
                app.cat(x,356,'idle',app.ui_clock,skin=CHARACTERS['black']['skin'],scale=3.)
            else:
                art.draw('ui/equipment_chest.png',x,417,118,106,alpha=1. if enabled else .7)
            art.text(label,x,305,20,INK,True)
            art.text(description,x,275,14,SECONDARY,True)
            p.draw_rectangle(left+8,215,left+216,250,*(PRIMARY if hovered else FRAME),filled=True)
            status='보유 완료' if owned else f'{cost:,} GOLD'
            if not enabled and not owned:
                status+=' · 부족'
            art.text(status,x,233,15,FRAME if hovered else INK if enabled else SECONDARY,True)
            app.buttons.append((rect,action,enabled))

        if self.shop_category!='character':
            app.panel(228,120,932,177)
            odds='   /   '.join(f'{tier["name"]} {tier["weight"]}%' for tier in GEAR['rarities'].values())
            art.text('장비 등급 확률',250,148,15,INK)
            art.text(odds,650,148,14,SECONDARY,True)

    def draw_panel(self,app):
        art=app.art
        profile=app.store.profile
        selected=profile['selected_character_id']
        info=CHARACTERS[selected]
        character=profile['characters'][selected]
        title=MENU[self.panel][0] if self.panel in MENU else '설정'
        app.modal(*((40,70,920,552) if self.panel=='equipment' else PANEL))
        art.text(title,124,520,24,ACCENT)
        app.button('닫기',CLOSE,('lobby','close'))
        if self.panel=='character':
            p.draw_line(480,195,480,482,*LINE)
            for index,key in enumerate(k for k in profile['characters'] if k in CHARACTERS):
                rect=(132,378-index*110,456,474-index*110)
                color=SELECTED if key==self.preview or contains(rect,*app.mouse) else ROW
                p.draw_rectangle(*rect,*color,filled=True)
                if key==self.preview:
                    p.draw_rectangle(rect[0],rect[1],rect[0]+3,rect[3],*ACCENT,filled=True)
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
            app.button('선택하기',(525,130,815,178),('lobby','select'),primary=True)
            if self.error:
                art.text('선택 저장 실패 · 선택하기로 재시도',480,195,16,ERROR,True)
        elif self.panel=='skills':
            art.text(f'{info["name"]}   Lv. {character["level"]}',132,451,22,INK)
            art.text(f'미사용 스킬 포인트  {character["skill_points"]}',132,409,18,INK)
            art.text('스킬 디자인 준비 중',480,300,24,INK,True)
            art.text('스킬 구성이 정해지면 이곳에서 포인트를 사용할 수 있습니다.',480,255,17,INK,True)
        elif self.panel=='equipment':
            self.draw_equipment(app)
        elif self.panel=='achievements':
            self.page=min(self.page,(len(ACHIEVEMENTS)-1)//5)
            for i,achievement in enumerate(ACHIEVEMENTS[self.page*5:self.page*5+5]):
                y=442-i*55
                p.draw_line(132,y-32,826,y-32,*LINE)
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
            p.draw_rectangle(*rect,*(SELECTED if slot==self.slot else ROW),filled=True)
            if slot==self.slot:
                p.draw_rectangle(left,460,left+220,462,*ACCENT,filled=True)
            item=by_id.get(profile['equipment_slots'][slot])
            text=f'{slot+1} · '+(GEAR['types'][definition(item)['type']]['name'] if item else '빈 슬롯' if slot<profile['unlocked_slots'] else f'잠금 {GEAR["slot_costs"][slot]} G')
            if item:
                EQUIPMENT_ART.draw(art,item,left+20,475,app.ui_clock,size=20)
            art.text(text,left+120 if item else left+110,475,15,INK,True)
            app.buttons.append((rect,('lobby','slot',slot),slot<=profile['unlocked_slots']))
        target=by_id.get(self.material_target)
        shown=[item for item in inventory if material_allowed(profile,target,item)] if target else inventory
        self.page=min(self.page,max(0,(len(shown)-1)//5))
        art.text('소모할 재료 선택' if target else f'보유 장비  {len(inventory)}개',100,435,18,INK)
        for index,item in enumerate(shown[self.page*5:self.page*5+5]):
            y=392-index*42
            rect=(100,y-18,490,y+18)
            highlighted=item['id']==self.item_id
            p.draw_rectangle(*rect,*(SELECTED if highlighted else ROW),filled=True)
            if highlighted:
                p.draw_rectangle(100,y-18,103,y+18,*ACCENT,filled=True)
            EQUIPMENT_ART.draw(art,item,122,y,app.ui_clock,size=30)
            art.text(item_name(item),149,y+5,16,INK)
            if item.get('is_new',False):
                NEW_BADGE.draw(art,461,y+5,scale=.8)
            status=('잠금 · ' if item['locked'] else '')+('장착 · ' if item['id'] in profile['equipment_slots'] else '')+f'강화 +{item["enhancement"]} / 중첩 {item["stacks"]}'
            art.text(status,149,y-11,12,INK)
            app.buttons.append((rect,('lobby','item',item['id']),True))
        if not shown:
            art.text('사용 가능한 재료가 없습니다.' if target else '상점에서 장비를 뽑아보세요.',295,335,18,INK,True)
        if self.item_id not in by_id:
            self.item_id=shown[0]['id'] if shown else None
        selected=by_id.get(self.item_id)
        if selected:
            spec=definition(selected)
            EQUIPMENT_ART.draw(art,selected,820,419,app.ui_clock,size=58)
            art.text(item_name(selected),535,435,20,INK)
            art.text(f'{GEAR["types"][spec["type"]]["label"]} +{stat_value(selected)*100:.2f}%',535,403,17,INK)
            art.text(f'강화 +{selected["enhancement"]} / 중첩 {selected["stacks"]}',535,375,16,INK)
            app.button('장착',(540,315,675,357),('lobby','gear','equip'),primary=True)
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

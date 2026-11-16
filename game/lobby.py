"""Lobby layout and panel state; economic actions belong to later features."""
import pico2d as p
from .characters import CHARACTERS
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

    @property
    def bounds(self):
        return CONTROLS if self.panel=='controls' else PANEL

    def open(self,app,name):
        if name not in (*MENU,'settings','controls'):
            return
        self.close(app)
        self.panel=name
        app.buttons=[]
        self.preview=app.store.profile['selected_character_id']

    def close(self,app):
        if app.dragging:
            app.dragging=None
            app.save()
        self.panel=None
        self.error=''
        app.buttons=[]
        app.keys.clear()

    def action(self,app,args):
        if args[0]=='open':
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
        art.text(f'GOLD   {profile["gold"]:,}',720,592,20,INK)
        app.panel(28,238,358,536)
        app.cat(110,440,'idle',app.ui_clock,skin=info['skin'],scale=2.)
        art.text(info['name'],196,493,24,INK)
        art.text(f'Lv. {character["level"]}',196,460,21,INK)
        maximum=character['level']==50
        exp=character['exp']
        label='EXP  MAX' if maximum else f'EXP  {exp:g} / {level_cost(character["level"])}'
        art.text(label,52,404,16,INK)
        p.draw_rectangle(52,367,334,381,*INK,filled=True)
        p.draw_rectangle(54,369,332,379,208,197,163,filled=True)
        ratio=1. if maximum else exp/level_cost(character['level'])
        if ratio:
            p.draw_rectangle(54,369,54+278*ratio,379,84,141,104,filled=True)
        art.text(f'미사용 스킬 포인트  {character["skill_points"]}',52,333,16,INK)
        app.buttons.append(((46,317,340,351),('lobby','open','skills'),True))
        for i,rect in enumerate(SLOTS):
            rounded_box(rect,(240,207,139) if contains(rect,*app.mouse) else (231,221,192))
            x=(rect[0]+rect[2])/2
            art.text('빈 슬롯' if i==0 else '잠금',x,287,14,INK,True)
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
        if self.panel:
            app.buttons=[]
            if self.panel=='controls':
                app.controls_panel()
                return
            self.draw_panel(app)

    def draw_panel(self,app):
        art=app.art
        profile=app.store.profile
        selected=profile['selected_character_id']
        info=CHARACTERS[selected]
        character=profile['characters'][selected]
        title=MENU[self.panel][0] if self.panel in MENU else '설정'
        app.panel(*PANEL)
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
            for i in range(3):
                left=164+i*236
                rounded_box((left,350,left+160,450),(231,221,192))
                art.text(f'슬롯 {i+1}',left+80,422,17,INK,True)
                art.text('빈 슬롯' if i==0 else '잠금',left+80,385,19,INK,True)
            art.text('보유 장비가 없습니다.',480,285,23,INK,True)
            art.text('장착·해금·강화 기능 준비 중',480,242,17,INK,True)
        elif self.panel=='shop':
            art.text(f'보유 GOLD   {profile["gold"]:,}',132,454,18,INK)
            art.text('흑냥이',310,374,24,INK,True)
            art.text('근접 캐릭터',310,337,17,INK,True)
            art.text('500 GOLD',310,296,21,INK,True)
            art.text('장비 뽑기',650,374,24,INK,True)
            art.text('1회 뽑기',650,337,17,INK,True)
            art.text('150 GOLD',650,296,21,INK,True)
            app.button('구매 준비 중',(168,193,453,235),None,False)
            app.button('뽑기 준비 중',(508,193,793,235),None,False)
        elif self.panel=='achievements':
            art.text('업적 목록 준비 중',480,355,24,INK,True)
            art.text('업적의 진행 상태와 보상은 이곳에서 확인합니다.',480,302,18,INK,True)
            art.text('업적 EXP·GOLD는 판 정산과 별도로 관리합니다.',480,182,16,INK,True)
        elif self.panel=='settings':
            app.volume('bgm_volume',352,365)
            app.volume('sfx_volume',352,260)

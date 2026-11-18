"""pico2d presentation with versioned art and aspect-preserving drawing."""
import argparse
import ctypes
import json
import math
import time
from pathlib import Path
import pico2d as p
import pico2d.pico2d as native
from .model import ROOT, BALANCE, WORLD_WIDTH, World
from .storage import Store
from .lobby import Lobby, contains as lobby_contains
from .characters import CHARACTERS
from .visuals import CHARACTER_ART, REWARD_ART
from .equipment import bonuses as equipment_bonuses
from .rewards import settle_run
from .framework import capture, run, scene_machine
from .audio import Audio
from .ui import ACCENT, ERROR, FRAME, HUD, INK, LINE, PRIMARY, ROW, SECONDARY, SELECTED, SURFACE

ART = ROOT/'output/nyangi_art_v1'
ART_V2 = ROOT/'output/nyangi_art_v2'
ART_V3 = ROOT/'output/nyangi_art_v3'
ART_V4 = ROOT/'output/nyangi_art_v4'
ART_V5 = ROOT/'output/nyangi_art_v5'
ART_V6 = ROOT/'output/nyangi_art_v6'
ART_V7 = ROOT/'output/nyangi_art_v7'
KEY_BINDINGS = {p.SDLK_a:'left',p.SDLK_d:'right',p.SDLK_w:'up',p.SDLK_s:'down'}
CONTROLS_BUTTON = (335,132,625,178)
CONTROLS_PANEL = (275,190,685,490)
RESULT_SECONDS = 3.
TEXT_RASTER_SCALE = 2
UI_WIDTH = 960


def contains(rect,x,y):
    return rect[0]<=x<=rect[2] and rect[1]<=y<=rect[3]


def enemy_frame_state(enemy):
    if enemy.species=='snake' and enemy.state=='CHARGE':
        return 'idle'
    return 'fly' if enemy.state=='RECOVER' else enemy.state.lower()


def fit_size(source_width,source_height,width=None,height=None):
    if width is None and height is None:
        return source_width,source_height
    scale = min(width/source_width if width is not None else float('inf'),
                height/source_height if height is not None else float('inf'))
    return source_width*scale,source_height*scale


def tile_segments(left,right):
    if right-left < 64:
        raise ValueError('Terrain span needs two 32px caps')
    yield left,32,'left'
    x = left+32
    while x < right-32:
        width = min(32,right-32-x)
        yield x,width,'center'
        x += width
    yield right-32,32,'right'


class Art:
    def __init__(self):
        manifest = json.loads((ART/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.specs = {entry['file']:entry for entry in manifest['entries']}
        versioned = json.loads((ART_V2/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v2_specs = {entry['file']:entry for entry in versioned['entries']}
        badge = json.loads((ART_V3/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v3_specs = {entry['file']:entry for entry in badge['entries']}
        latest = json.loads((ART_V4/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v4_specs = {entry['file']:entry for entry in latest['entries']}
        self.specs.update(self.v4_specs)
        additions = json.loads((ART_V5/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v5_specs = {entry['file']:entry for entry in additions['entries']}
        self.specs.update(self.v5_specs)
        shop = json.loads((ART_V6/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v6_specs = {entry['file']:entry for entry in shop['entries']}
        self.specs.update(self.v6_specs)
        equipment = json.loads((ART_V7/'assets_manifest.json').read_text(encoding='utf-8-sig'))
        self.v7_specs = {entry['file']:entry for entry in equipment['entries']}
        self.specs.update(self.v7_specs)
        self.overrides = versioned['overrides']
        for original,replacement in self.overrides.items():
            self.specs[original] = {**self.v2_specs[replacement],'file':original}
        self.images, self.fonts, self.labels = {}, {}, {}

    def image(self, name):
        if name not in self.images:
            if name in self.v7_specs:
                path = ART_V7/'png'/name
            elif name in self.v6_specs:
                path = ART_V6/'png'/name
            elif name in self.v5_specs:
                path = ART_V5/'png'/name
            elif name in self.v4_specs:
                path = ART_V4/'png'/name
            elif name.startswith('v3/'):
                path = ART_V3/'png'/name[3:]
            elif name.startswith('v2/'):
                path = ART_V2/'png'/name[3:]
            elif name in self.overrides:
                path = ART_V2/'png'/self.overrides[name]
            else:
                path = ART/'png'/name
            self.images[name] = p.load_image(str(path))
            p.SDL_SetTextureScaleMode(self.images[name].texture,p.SDL_ScaleModeNearest)
        return self.images[name]

    def draw(self,name,x,y,w=None,h=None,alpha=1.):
        image = self.image(name)
        image.opacify(alpha)
        width,height = fit_size(image.w,image.h,w,h)
        image.draw(x,y,width,height)
        image.opacify(1.)

    def sprite(self,name,x,y,clock=0.,flip=False,alpha=1.,foot=False,scale=1.,rotation=0.):
        spec = self.specs[name]
        image = self.image(name)
        fw,fh = spec['frame_width'],spec['frame_height']
        frame = int(clock*spec['fps'])
        frame = frame % spec['frames'] if spec['loop'] else min(spec['frames']-1,frame)
        if foot:
            x += (fw/2-spec['pivot'][0])*scale
            y += (spec['pivot'][1]-fh/2)*scale
        image.opacify(alpha)
        image.clip_composite_draw(frame*fw,0,fw,fh,rotation,'h' if flip else '',x,y,fw*scale,fh*scale)
        image.opacify(1.)

    def text(self,text,x,y,size=18,color=INK,center=False):
        key = (text,size,color)
        if key not in self.labels:
            if size not in self.fonts:
                font = Path('C:/Windows/Fonts/malgunbd.ttf')
                if not font.exists():
                    raise FileNotFoundError('Korean font is required: C:/Windows/Fonts/malgunbd.ttf')
                self.fonts[size] = p.load_font(str(font),size*TEXT_RASTER_SCALE)
            surface = p.TTF_RenderUTF8_Blended(self.fonts[size].font,text.encode('utf-8'),p.SDL_Color(*color))
            if not surface:
                raise RuntimeError('Could not render text')
            texture = p.SDL_CreateTextureFromSurface(native.renderer,surface)
            p.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError('Could not create text texture')
            p.SDL_SetTextureScaleMode(texture,p.SDL_ScaleModeLinear)
            if len(self.labels) >= 300:
                self.labels.clear()
            label = p.Image(texture)
            label.w = round(label.w/TEXT_RASTER_SCALE)
            label.h = round(label.h/TEXT_RASTER_SCALE)
            self.labels[key] = label
        label = self.labels[key]
        label.draw(x if center else x+label.w/2,y)

    def outlined_text(self,text,x,y,size=64,color=INK,center=True):
        for dx,dy in ((-2,-2),(0,-2),(2,-2),(-2,0),(2,0),(-2,2),(0,2),(2,2)):
            self.text(text,x+dx,y+dy,size,FRAME,center)
        self.text(text,x,y,size,color,center)


class App:
    def __init__(self,save_folder=None):
        self.art = Art()
        self.store = Store(save_folder or ROOT/'save')
        self.world = None
        self.lobby = Lobby()
        self.scene_machine = scene_machine(self)
        self.keys, self.buttons = set(), []
        self.mouse, self.dragging = (0,0), None
        self.scene_viewport = None
        self.running, self.fullscreen = True, False
        self.ui_clock, self.last_mode = 0., None
        self.saved_result, self.error = False, ''
        self.settlement = None
        self.result_clock = 0.
        self.exit_confirm = False
        self.controls_popup = False
        self.audio = Audio(self.store.profile)
        self.audio.scene(self.scene)
        self.last_countdown = None
        if not self.audio.available:
            self.error = '오디오 장치를 열 수 없습니다. 소리 없이 플레이합니다.'

    def close(self):
        self.audio.close()
        self.art.labels.clear()
        self.art.images.clear()

    def enter_lobby(self):
        if self.scene=='RESULT':
            if not self.saved_result:
                return
            if self.result_clock<RESULT_SECONDS:
                self.result_clock=RESULT_SECONDS
                return
        self.lobby.close(self)
        self.controls_popup=False
        self.exit_confirm=False
        self.show_lobby()
        self.audio.scene('LOBBY')

    def start(self):
        if self.store.pending:
            self.error='미완료 거래를 먼저 재시도하세요.'
            return
        if self.scene=='LOBBY' and self.lobby.panel:
            return
        if self.scene=='RESULT':
            if not self.saved_result:
                return
            if self.result_clock<RESULT_SECONDS:
                self.result_clock=RESULT_SECONDS
                return
        self.controls_popup = False
        self.world = World(seed=time.time_ns() & 0xffffffff,character_id=self.store.profile['selected_character_id'],bonuses=equipment_bonuses(self.store.profile))
        self.show_play()
        self.saved_result = False
        self.settlement = None
        self.result_clock = 0.
        self.exit_confirm = False
        self.error = ''
        self.keys.clear()
        self.last_countdown = None
        self.audio.scene('PLAY')

    def retry_settlement(self):
        try:
            self.settlement = self.store.settle(self.world)
            self.saved_result = True
            self.error = ''
        except (OSError,ValueError) as exc:
            self.saved_result = False
            self.error = f'보상 저장 실패: {exc}'

    def save(self):
        try:
            self.store.save_profile()
            self.error = ''
        except (OSError,ValueError) as exc:
            self.error = f'저장 실패: {exc}'

    def update(self,dt):
        self.ui_clock += dt
        if self.scene=='LOBBY':
            self.lobby.update(dt)
        if self.scene == 'PLAY':
            if self.world.mode == 'PLAYING':
                self.world.aim = self.mouse
            self.world.update(dt,self.keys)
            if self.world.mode=='GAME_OVER' and self.world.end_reason=='death':
                self.settlement = settle_run(self.store.profile,self.world)
                self.result_clock = 0.
                self.keys.clear()
                self.show_result()
                self.retry_settlement()
            for event in self.world.events:
                self.audio.play(event)
            self.world.events.clear()
            if self.world.mode == 'COUNTDOWN':
                number=max(1,math.ceil(self.world.countdown))
                if number!=self.last_countdown:
                    self.audio.play('countdown')
                    self.last_countdown=number
            else:
                self.last_countdown=None
        if self.scene=='RESULT' and self.saved_result:
            self.result_clock=min(RESULT_SECONDS,self.result_clock+dt)
        self.audio.scene(self.scene)

    def button(self,label,rect,action,enabled=True,*,primary=False,wayfinding=False):
        left,bottom,right,top = rect
        hover = contains(rect,*self.mouse)
        fill,detail,ink = HUD,(65,91,79),(153,177,159)
        if enabled:
            if primary:
                fill,detail,ink = ((204,229,175) if hover else PRIMARY),(128,166,112),FRAME
            else:
                fill,detail,ink = (SELECTED if hover else ROW),(ACCENT if hover else LINE),INK
        p.draw_rectangle(left+3,bottom,right-3,top,*FRAME,filled=True)
        p.draw_rectangle(left,bottom+3,right,top-3,*FRAME,filled=True)
        p.draw_rectangle(left+3,bottom+4,right-3,top-3,*fill,filled=True)
        p.draw_rectangle(left+6,top-4,right-6,top-3,*detail,filled=True)
        y=(bottom+top)/2
        if wayfinding:
            self.art.text(label,left+24,y,18,ink)
            marker=ink
            p.draw_rectangle(right-25,y-5,right-23,y+5,*marker,filled=True)
            p.draw_rectangle(right-22,y-3,right-20,y+3,*marker,filled=True)
            p.draw_rectangle(right-19,y-1,right-17,y+1,*marker,filled=True)
        elif label:
            self.art.text(label,(left+right)/2,y,18,ink,True)
        self.buttons.append((rect,action,enabled))

    def panel(self,left,bottom,right,top):
        p.draw_rectangle(left+6,bottom,right-6,top,*FRAME,filled=True)
        p.draw_rectangle(left,bottom+6,right,top-6,*FRAME,filled=True)
        p.draw_rectangle(left+3,bottom+3,right-3,top-3,*ROW,filled=True)
        p.draw_rectangle(left+6,bottom+6,right-6,top-6,*SURFACE,filled=True)
        p.draw_rectangle(left+6,top-5,right-6,top-3,*LINE,filled=True)

    def shade(self):
        viewport = p.SDL_Rect()
        p.SDL_RenderGetViewport(native.renderer,ctypes.byref(viewport))
        if self.scene_viewport is not None:
            p.SDL_RenderSetViewport(native.renderer,self.scene_viewport)
        p.SDL_SetRenderDrawBlendMode(native.renderer,p.SDL_BLENDMODE_BLEND)
        p.SDL_SetRenderDrawColor(native.renderer,*FRAME,102)
        p.SDL_RenderFillRect(native.renderer,None)
        p.SDL_SetRenderDrawBlendMode(native.renderer,p.SDL_BLENDMODE_NONE)
        p.SDL_RenderSetViewport(native.renderer,viewport)

    def modal(self,left,bottom,right,top):
        self.shade()
        self.panel(left,bottom,right,top)

    def cat(self,x,y,state='idle',clock=0.,skin=None,flip=False,alpha=1.,scale=1.):
        character_id=self.world.character_id if self.scene in ('PLAY','RESULT') and self.world else self.store.profile['selected_character_id']
        CHARACTER_ART[character_id].draw(self.art,x,y,state,clock,skin=skin,flip=flip,alpha=alpha,scale=scale)

    def background(self):
        name = 'backgrounds/campus_title_duel_wide.png' if self.scene=='TITLE' else 'backgrounds/campus_field_wide.png'
        self.art.draw(name,p.get_canvas_width()/2,320)

    def gameplay(self):
        w,c = self.world,self.world.cat
        for left,right,floor in BALANCE['surfaces']:
            kind = 'ground' if floor == BALANCE['ground'] else 'platform'
            for x,width,part in tile_segments(left,right):
                image = self.art.image(f'v2/tiles/{kind}_{part}.png')
                image.clip_draw(0,0,width,32,x+width/2,floor-16,width,32)
        self.aim_guide()
        for x,y,angle,radius,born,special in w.swings:
            CHARACTER_ART[w.character_id].attack.draw(self.art,x+math.cos(angle)*radius*.4,
                y+math.sin(angle)*radius*.4,w.time-born,rotation=angle,scale=radius/45)
        for item in w.items:
            if item.state=='PRE_SPAWN_WARNING':
                continue
            self.art.sprite(f'sprites/items/{item.kind}.png',item.x,item.y+math.sin(item.clock*4)*3,item.clock)
        if w.bandage_due is not None:
            center = WORLD_WIDTH/2
            p.draw_circle(center,BALANCE['ground']+8,24,78,173,118)
            for i in range(0,360,30):
                a = math.radians(i)
                p.draw_line(center+math.cos(a)*28,88+math.sin(a)*9,center+math.cos(a+.15)*28,88+math.sin(a+.15)*9,130,140,135)
        for e in w.enemies:
            state = enemy_frame_state(e)
            if e.species == 'snake' and state == 'return_underground':
                state = 'return_underground'
            name = f'sprites/enemies/{e.species}/{state}.png'
            flip = e.vx < 0 if e.species == 'squirrel' else e.attack_dx < 0 if e.state in ('RUSH','DASH','DIVE') else e.vx < 0
            if e.grade:
                grade = 'awakened' if e.grade == 1 else 'super_awakened'
                outline = f'effects/outlines/{e.species}/{state}_{grade}.png'
                self.art.sprite(outline,e.x,e.y,e.clock,flip)
            alpha = .35 if e.hit_flash and int(e.hit_flash*50)%2 else .55 if e.spawn_grace else 1.
            self.art.sprite(name,e.x,e.y,e.clock,flip,alpha=alpha)
            outline = f'effects/outlines/{e.species}/{state}_warning.png'
            if outline in self.art.specs:
                self.art.sprite(outline,e.x,e.y,e.clock,flip)
            if e.species=='snake' and e.state=='CHARGE':
                p.draw_circle(e.x,BALANCE['ground']+10,18,255,255,255)
            if e.targetable:
                p.draw_rectangle(e.x-19,e.y+35,e.x+19,e.y+42,34,33,35,filled=True)
                p.draw_rectangle(e.x-18,e.y+37,e.x+18,e.y+40,90,83,86,filled=True)
                p.draw_rectangle(e.x-18,e.y+37,e.x-18+36*e.hp/e.max_hp,e.y+40,245,124,99,filled=True)
        for x,y,facing,born in w.trails:
            self.cat(x,y,'dash',0,flip=facing<0,alpha=.4*(1-(w.time-born)/.23))
        states = {'MOVE':'walk'}
        state = states.get(c.state,c.state.lower())
        if c.attack_left > 0 and c.grounded and c.state in ('IDLE','GROOM'):
            state = 'attack'
        self.cat(c.x,c.y,state,c.clock,flip=c.facing<0,alpha=.4 if w.mode=='PLAYING' and c.invincible and int(w.time*12)%2 else 1.)
        if c.heal_left:
            p.draw_circle(c.x,c.y+26,int(34*(1-c.heal_left/.6)),75,216,151)
        for projectile in w.projectiles:
            CHARACTER_ART[w.character_id].attack.draw(self.art,projectile.x,projectile.y,projectile.clock,
                            scale=projectile.scale,rotation=math.atan2(projectile.dy,projectile.dx))

    def gameplay_ui(self):
        w,c = self.world,self.world.cat
        for i in range(3):
            self.art.draw(f'ui/heart_{"full" if i<c.hp else "empty"}.png',28+i*34,24,28,28)
        self.art.outlined_text('근접' if w.character_id=='black' else '일반탄',128,24,16,center=False)
        for i in range(0 if w.character_id=='black' else BALANCE['ammo_max']):
            self.art.draw(f'ui/ammo_{"full" if i<c.ammo else "empty"}.png',208+i*23,24,20,20)
        self.charge_hud()
        self.art.outlined_text(f'{int(w.time)//60:02d}:{int(w.time)%60:02d}',480,605,30)
        if w.warning_message:
            self.art.outlined_text(w.warning_message,480,578,15,ACCENT)
        if w.mode == 'PAUSED':
            self.pause_panel()
        elif w.mode == 'COUNTDOWN':
            self.art.outlined_text(str(max(1,math.ceil(w.countdown))),480,330)
        if self.exit_confirm:
            self.modal(275,210,685,430)
            self.art.text('이번 판 보상을 포기할까요?',480,386,23,INK,True)
            self.art.text('획득한 EXP와 GOLD는 저장되지 않습니다.',480,346,16,INK,True)
            self.buttons=[]
            self.button('취소',(315,259,450,301),'cancel_exit')
            self.button('포기하기',(510,259,645,301),'confirm_exit')


    def volume(self,key,x,y):
        value = self.store.profile[key]
        label=('BGM' if key == 'bgm_volume' else 'SFX')+f'   {value}'
        self.art.text(label,x,y+28,17,INK)
        end = 8+240*value/100
        p.draw_rectangle(x+8,y-2,x+248,y+2,*LINE,filled=True)
        if value:
            p.draw_rectangle(x+8,y-2,x+end,y+2,*ACCENT,filled=True)
        p.draw_rectangle(x+end-5,y-9,x+end+5,y+9,*INK,filled=True)
        self.buttons.append(((x,y-15,x+256,y+15),('volume',key,x),True))

    def pause_panel(self):
        self.modal(285,120,675,495)
        self.art.text('잠깐 쉬어가기',480,455,28,INK,True)
        self.volume('bgm_volume',352,375)
        self.volume('sfx_volume',352,295)
        self.button('계속하기',(335,210,625,252),'resume',primary=True)
        self.button('로비로 나가기',(335,150,625,192),'exit_run')

    def result(self):
        self.modal(125,45,835,600)
        self.art.text('이번 산책의 기록',166,555,28,INK)
        p.draw_line(166,526,794,526,*LINE)
        result=self.settlement
        self.cat(214,424,'idle',self.ui_clock,scale=2.)
        self.art.text(f'{CHARACTERS[result["character_id"]]["name"]}   Lv. {result["level_after"]}',278,468,23,INK)
        seconds=int(result['survival_time'])
        self.art.text('생존 시간',733,484,15,SECONDARY,True)
        self.art.text(f'{seconds//60:02d}:{seconds%60:02d}',733,444,36,INK,True)
        if result['level_before']!=result['level_after']:
            self.art.text(f'Lv. {result["level_before"]} → {result["level_after"]}   스킬 포인트 +{result["skill_points_gained"]}',278,431,16,SECONDARY)
        def progress(start):
            t=max(0.,min(1.,(self.result_clock-start)/1.3))
            return 1-(1-t)**3
        def number(value):
            return f'{value:,.2f}'.rstrip('0').rstrip('.')
        exp=result['applied_exp']*progress(0)
        gold=int(result['gold_gained']*progress(1.4))
        for y,kind,value,percent in ((354,'exp',number(exp),result['exp_percent']),
                                    (273,'gold',f'{gold:,}',result['gold_percent'])):
            p.draw_line(166,y+31,794,y+31,*LINE)
            REWARD_ART[kind].draw(self.art,186,y,scale=1.4)
            self.art.text(f'획득 {kind.upper()}',217,y+6,20,INK)
            self.art.text(f'생존 배율 ×{percent/100:.2f}',217,y-20,15,SECONDARY)
            self.art.text(value,695,y,28,INK,True)
        if result['overflow_exp']:
            self.art.text(f'만렙 초과 EXP {number(result["overflow_exp"])} → GOLD +{result["converted_gold"]}',480,175,16,INK,True)
        if self.saved_result:
            self.art.text('저장 완료' if self.result_clock>=RESULT_SECONDS else '클릭 또는 Enter로 합산 완료',480,145,14,INK,True)
            self.button('다시 시작하기',(165,77,455,125),'start',primary=True)
            self.button('로비로',(505,77,795,125),'lobby')
        else:
            self.art.text('보상을 저장하지 못했습니다. 저장 후 이동할 수 있습니다.',480,155,16,ERROR,True)
            self.button('저장 재시도',(335,77,625,125),'retry_save',primary=True)

    def controls_panel(self):
        self.modal(*CONTROLS_PANEL)
        self.art.text('조작 방법',480,459,24,INK,True)
        black=self.store.profile['selected_character_id']=='black'
        rows=(('A / D','좌우 이동'),('W / SPACE','더블 점프'),('S + SPACE','발판 아래로 내려가기'),
              ('SHIFT','대시 2회 · 공유 충전'),('마우스 좌','전방 근접 공격' if black else '조준 방향 일반탄'),('마우스 우',('광역 발톱' if black else '관통탄')+' · 츄르 10개 충전'),
              ('ESC','일시정지 / 계속하기'),('F11','전체 화면'))
        for i,(key,description) in enumerate(rows):
            y=419-i*27
            p.draw_rectangle(294,y-10,406,y+10,*ROW,filled=True)
            self.art.text(key,350,y,15,INK,True)
            self.art.text(description,420,y,16)

    def aim_guide(self):
        w,c=self.world,self.world.cat
        x,y=c.x,c.y+26
        dx,dy=w.aim_direction()
        distances=[(bound-origin)/direction for origin,direction,bounds in
                   ((x,dx,(0,WORLD_WIDTH)),(y,dy,(BALANCE['ground'],560))) if abs(direction)>1e-9
                   for bound in bounds if (bound-origin)/direction>=0]
        length=min(distances,default=0.)

        def stroke(ax,ay,bx,by):
            span=math.hypot(bx-ax,by-ay)
            if span<1e-9:
                return
            nx,ny=-(by-ay)/span,(bx-ax)/span
            for width,color in ((3,(26,35,43)),(1,(255,226,69))):
                for offset in range(-width,width+1):
                    p.draw_line(ax+nx*offset,ay+ny*offset,bx+nx*offset,by+ny*offset,*color)

        if w.character_id=='black':
            angle=math.atan2(dy,dx)
            points=[(x+math.cos(angle+math.radians(-55+110*i/20))*90,y+math.sin(angle+math.radians(-55+110*i/20))*90) for i in range(21)]
            for first,second in zip(points,points[1:]):
                stroke(*first,*second)
            stroke(x,y,*points[0])
            stroke(x,y,*points[-1])
            length=0
        for distance in range(28,int(length),24):
            end=min(distance+15,length)
            stroke(x+dx*distance,y+dy*distance,x+dx*end,y+dy*end)
        mx,my=w.aim
        if 0<=mx<=WORLD_WIDTH and BALANCE['ground']<=my<=560:
            for radii,color in ((range(10,15),(26,35,43)),(range(11,14),(255,226,69))):
                for radius in radii:
                    p.draw_circle(mx,my,radius,*color)
            for ax,ay,bx,by in ((mx-21,my,mx-7,my),(mx+7,my,mx+21,my),
                               (mx,my-21,mx,my-7),(mx,my+7,mx,my+21)):
                stroke(ax,ay,bx,by)

    def charge_hud(self):
        c=self.world.cat
        self.art.outlined_text(f'대시 {c.dash_charges}/2',319,24,15,center=False)
        progress=1-c.dash_cd/self.world.dash_cooldown
        for i in range(BALANCE['dash_max_charges']):
            left=405+i*54
            p.draw_rectangle(left-2,18,left+47,29,*FRAME,filled=True)
            p.draw_rectangle(left,20,left+45,27,*LINE,filled=True)
            fill=1. if i<c.dash_charges else progress if i==c.dash_charges else 0.
            if fill>0:
                p.draw_rectangle(left,20,left+45*fill,27,*PRIMARY,filled=True)
        self.art.outlined_text('광역' if self.world.character_id=='black' else '관통',566,24,15,center=False)
        for i in range(BALANCE['pierce_max_charges']):
            x=644+i*44
            ready=i<c.pierce_charges
            self.art.draw(f'ui/ammo_{"full" if ready else "empty"}.png',x,25,24,24)
            if ready:
                gold=int(195+24*math.sin(self.ui_clock*7+i))
                p.draw_rectangle(x-10,8,x+10,12,*FRAME,filled=True)
                p.draw_rectangle(x-8,9,x+8,11,237,gold,111,filled=True)

    def draw(self):
        p.clear_canvas()
        self.buttons = []
        self.background()
        if self.scene == 'PLAY':
            self.gameplay()
        viewport = p.SDL_Rect()
        p.SDL_RenderGetViewport(native.renderer,ctypes.byref(viewport))
        padding = (p.get_canvas_width()-UI_WIDTH)//2
        self.scene_viewport = viewport
        p.SDL_RenderSetViewport(native.renderer,p.SDL_Rect(viewport.x+padding,viewport.y,UI_WIDTH,viewport.h))
        try:
            self.draw_ui()
        finally:
            p.SDL_RenderSetViewport(native.renderer,viewport)
            self.scene_viewport = None

    def draw_ui(self):
        if self.scene == 'PLAY':
            self.gameplay_ui()
        elif self.scene == 'RESULT':
            self.result()
        elif self.scene == 'LOBBY':
            self.lobby.draw(self)
        else:
            self.art.draw('ui/title_wordmark_trail.png',480,499)
            self.button('시작하기',(335,182,625,230),'start',primary=True)
            self.button('키 설명',CONTROLS_BUTTON,'controls')
            if self.controls_popup:
                self.controls_panel()
        if self.error:
            self.panel(30,10,930,42)
            self.art.text(self.error[:80],45,26,13,ERROR)

    def action(self,action,x):
        if self.exit_confirm and action not in ('cancel_exit','confirm_exit'):
            return
        if action is not None:
            self.audio.play('click')
        if self.scene=='RESULT' and action!='retry_save':
            if not self.saved_result:
                return
            if self.result_clock<RESULT_SECONDS:
                self.result_clock=RESULT_SECONDS
                return
        if isinstance(action,tuple):
            if action[0]=='lobby' and self.scene=='LOBBY':
                self.lobby.action(self,action[1:])
            elif action[0] == 'volume':
                _,key,left = action
                self.dragging = (key,left)
                self.change_volume(x)
            return
        if action == 'start':
            if self.scene=='TITLE':
                self.enter_lobby()
            else:
                self.start()
        elif action == 'lobby':
            self.enter_lobby()
        elif action == 'resume':
            self.world.pause()
            self.keys.clear()
        elif action == 'exit_run' and self.world.mode=='PAUSED':
            self.exit_confirm = True
        elif action == 'cancel_exit':
            self.exit_confirm = False
        elif action == 'confirm_exit' and self.exit_confirm:
            self.world.finish_run()
            self.exit_confirm = False
            self.keys.clear()
            self.enter_lobby()
        elif action == 'title':
            self.show_title()
            self.controls_popup = False
        elif action == 'controls' and self.scene=='TITLE':
            self.controls_popup = not self.controls_popup
        elif action == 'retry_save' and self.scene=='RESULT' and not self.saved_result:
            self.retry_settlement()

    def change_volume(self,x):
        if self.dragging:
            key,left = self.dragging
            self.store.profile[key] = max(0,min(100,int((x-left-8)/240*10+.5)*10))
            self.audio.volumes(self.store.profile)

    def click(self,x,y):
        if self.scene=='LOBBY' and self.lobby.panel:
            if not lobby_contains(self.lobby.bounds,x,y):
                self.lobby.close(self)
                return
        if self.exit_confirm:
            if contains((315,259,450,301),x,y):
                self.action('cancel_exit',x)
            elif contains((510,259,645,301),x,y):
                self.action('confirm_exit',x)
            return
        if self.controls_popup and self.scene=='TITLE':
            if contains(CONTROLS_BUTTON,x,y):
                self.action('controls',x)
            elif not contains(CONTROLS_PANEL,x,y):
                self.controls_popup=False
                self.audio.play('click')
            return
        if self.scene=='RESULT' and self.saved_result and self.result_clock<RESULT_SECONDS:
            self.result_clock=RESULT_SECONDS
            return
        for rect,action,enabled in reversed(self.buttons):
            if contains(rect,x,y):
                if enabled:
                    self.action(action,x)
                break

    def events(self):
        event = p.SDL_Event()
        mapping = KEY_BINDINGS
        while p.SDL_PollEvent(ctypes.byref(event)):
            if event.type == p.SDL_QUIT:
                self.running = False
            elif event.type == p.SDL_WINDOWEVENT and event.window.event == p.SDL_WINDOWEVENT_FOCUS_LOST:
                self.keys.clear()
                if self.scene == 'PLAY' and self.world.mode == 'PLAYING':
                    self.world.pause()
            elif event.type in (p.SDL_KEYDOWN,p.SDL_KEYUP):
                key = event.key.keysym.sym
                down = event.type == p.SDL_KEYDOWN
                if key in mapping:
                    if down:
                        self.keys.add(mapping[key])
                    else:
                        self.keys.discard(mapping[key])
                if not down or event.key.repeat:
                    continue
                if key == p.SDLK_F11:
                    self.fullscreen = not self.fullscreen
                    p.SDL_SetWindowFullscreen(native.window,p.SDL_WINDOW_FULLSCREEN_DESKTOP if self.fullscreen else 0)
                elif key == p.SDLK_ESCAPE:
                    if self.controls_popup:
                        self.controls_popup=False
                    elif self.exit_confirm:
                        self.exit_confirm=False
                    elif self.scene=='PLAY':
                        self.world.pause()
                        self.keys.clear()
                    elif self.scene=='RESULT':
                        self.action('lobby',0)
                    elif self.scene=='LOBBY':
                        if self.lobby.panel:
                            self.lobby.close(self)
                        else:
                            self.lobby.open(self,'settings')
                elif key == p.SDLK_RETURN:
                    if self.scene in ('TITLE','LOBBY','RESULT'):
                        self.action('start',0)
                    elif self.world.mode=='PAUSED' and not self.exit_confirm:
                        self.world.pause()
                elif self.scene=='PLAY':
                    if key in (p.SDLK_SPACE,p.SDLK_w):
                        self.world.jump(self.keys)
                    elif key in (p.SDLK_LSHIFT,p.SDLK_RSHIFT):
                        self.world.dash(self.keys)
            elif event.type in (p.SDL_MOUSEMOTION,p.SDL_MOUSEBUTTONDOWN,p.SDL_MOUSEBUTTONUP):
                data = event.motion if event.type == p.SDL_MOUSEMOTION else event.button
                padding = (p.get_canvas_width()-UI_WIDTH)//2
                self.mouse = data.x-padding,640-data.y
                if self.scene=='PLAY' and self.world.mode=='PLAYING':
                    self.world.aim=data.x,self.mouse[1]
                if event.type == p.SDL_MOUSEMOTION:
                    self.change_volume(self.mouse[0])
                elif event.type == p.SDL_MOUSEBUTTONDOWN:
                    playing=self.scene=='PLAY' and self.world.mode=='PLAYING'
                    if playing and event.button.button==p.SDL_BUTTON_LEFT:
                        self.keys.add('shoot')
                        self.world.shoot()
                    elif playing and event.button.button==p.SDL_BUTTON_RIGHT:
                        self.world.shoot(piercing=True)
                    elif event.button.button==p.SDL_BUTTON_LEFT:
                        self.click(*self.mouse)
                elif event.type == p.SDL_MOUSEBUTTONUP:
                    if event.button.button==p.SDL_BUTTON_LEFT:
                        self.keys.discard('shoot')
                    if self.dragging:
                        self.dragging=None
                        self.save()


def main():
    parser = argparse.ArgumentParser(description='냥이 서바이버 · Python + pico2d')
    parser.add_argument('--smoke',type=int,default=0,metavar='FRAMES',help='run gameplay then exit after N frames')
    parser.add_argument('--screenshot',type=Path,help='save final rendered frame as PNG')
    args = parser.parse_args()
    run(App, '냥이 서바이버', smoke=args.smoke, screenshot=args.screenshot)

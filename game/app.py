"""pico2d presentation with versioned art and aspect-preserving drawing."""
import argparse
import ctypes
import json
import math
import time
from pathlib import Path
import pico2d as p
import pico2d.pico2d as native
from .model import ROOT, BALANCE, SKINS, ACHIEVEMENTS, World
from .storage import Store
from .framework import capture, run, scene_machine
from .audio import Audio

ART = ROOT/'output/nyangi_art_v1'
ART_V2 = ROOT/'output/nyangi_art_v2'
ART_V3 = ROOT/'output/nyangi_art_v3'
INK = (48,45,52)
CREAM = (255,247,224)
SKIN_NAMES = ('토비냥','까치냥','청설모냥','벌냥','뱀냥','무지개냥')
KEY_BINDINGS = {p.SDLK_a:'left',p.SDLK_d:'right',p.SDLK_w:'up',p.SDLK_s:'down'}
CONTROLS_BUTTON = (335,132,625,178)
CONTROLS_PANEL = (275,190,685,490)
ACHIEVEMENT_CLOSE = (410,187,550,221)
ACHIEVEMENT_INFO = {a['skin_id']:a for a in ACHIEVEMENTS}
# Source rectangles remove transparent UI padding without changing the supplied PNGs.
UI_REGIONS = {'wave_banner':(68,14,3,36)}


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
        self.overrides = versioned['overrides']
        for original,replacement in self.overrides.items():
            self.specs[original] = {**self.v2_specs[replacement],'file':original}
        self.images, self.fonts, self.labels = {}, {}, {}

    def image(self, name):
        if name not in self.images:
            if name.startswith('v3/'):
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
        region = UI_REGIONS.get(Path(name).stem) if name.startswith('ui/') else None
        if region:
            left,top,fw,fh = region
            image.clip_draw(left,image.h-top-fh,fw,fh,x,y,w or fw,h or fh)
        else:
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
                self.fonts[size] = p.load_font(str(font),size)
            surface = p.TTF_RenderUTF8_Blended(self.fonts[size].font,text.encode('utf-8'),p.SDL_Color(*color))
            if not surface:
                raise RuntimeError('Could not render text')
            texture = p.SDL_CreateTextureFromSurface(native.renderer,surface)
            p.SDL_FreeSurface(surface)
            if len(self.labels) >= 300:
                self.labels.clear()
            self.labels[key] = p.Image(texture)
        label = self.labels[key]
        label.draw(x if center else x+label.w/2,y)

    def outlined_text(self,text,x,y,size=64):
        for dx,dy in ((-3,-3),(0,-3),(3,-3),(-3,0),(3,0),(-3,3),(0,3),(3,3)):
            self.text(text,x+dx,y+dy,size,(255,255,255),True)
        self.text(text,x,y,size,INK,True)


class App:
    def __init__(self,save_folder=None):
        self.art = Art()
        self.store = Store(save_folder or ROOT/'save')
        self.world = None
        self.scene_machine = scene_machine(self)
        self.keys, self.buttons = set(), []
        self.mouse, self.dragging = (0,0), None
        self.running, self.fullscreen = True, False
        self.ui_clock, self.last_mode = 0., None
        self.skin_popup, self.selected_skin = False, self.store.profile['equipped_skin_id']
        self.new_record, self.saved_result, self.error = False, False, ''
        self.controls_popup = False
        self.achievement_queue = []
        self.run_owned = set(self.store.profile['unlocked_skin_ids'])
        self.audio = Audio(self.store.profile)
        self.audio.scene(self.scene)
        self.last_countdown = None
        if not self.audio.available:
            self.error = '오디오 장치를 열 수 없습니다. 소리 없이 플레이합니다.'

    def close(self):
        self.audio.close()
        self.art.labels.clear()
        self.art.images.clear()

    def start(self):
        self.run_owned = set(self.store.profile['unlocked_skin_ids'])
        self.achievement_queue = []
        self.controls_popup = False
        self.world = World(seed=time.time_ns() & 0xffffffff)
        self.world.unlocked.update(self.store.profile['unlocked_skin_ids'])
        self.show_play()
        self.saved_result, self.skin_popup = False, False
        self.keys.clear()
        self.last_countdown = None
        self.audio.scene('PLAY')

    def save(self):
        try:
            self.store.save_profile()
        except OSError as exc:
            self.error = f'저장 실패: {exc}'

    def update(self,dt):
        self.ui_clock += dt
        if self.scene == 'PLAY':
            if self.world.mode == 'PLAYING':
                self.world.aim = self.mouse
            self.world.update(dt,self.keys)
            try:
                self.store.unlock(self.world.unlocked)
                if self.world.mode == 'GAME_OVER' and not self.saved_result:
                    self.new_record = self.store.record(self.world)
                    self.saved_result = True
                    self.achievement_queue = [s for s in SKINS[1:] if s in self.world.unlocked and s not in self.run_owned]
                    self.show_result()
            except OSError as exc:
                self.error = f'기록 저장 실패: {exc}'
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
        self.audio.scene(self.scene)

    def button(self,label,rect,action,enabled=True):
        left,bottom,right,top = rect
        hover = contains(rect,*self.mouse)
        state = 'disabled' if not enabled else 'hover' if hover else 'normal'
        self.art.draw(f'v2/ui/buttons/{state}_{right-left}x{top-bottom}.png',(left+right)/2,(bottom+top)/2)
        self.art.text(label,(left+right)/2,(bottom+top)/2,18,INK if enabled else (105,100,98),True)
        self.buttons.append((rect,action,enabled))

    def panel(self,left,bottom,right,top):
        p.draw_rectangle(left,bottom,right,top,*CREAM,filled=True)
        p.draw_rectangle(left,bottom,right,top,99,79,68)

    def cat(self,x,y,state='idle',clock=0.,skin=None,flip=False,alpha=1.,scale=1.):
        skin = skin or self.store.profile['equipped_skin_id']
        self.art.sprite(f'sprites/cat/{skin}/{state}.png',x,y,clock,flip,alpha,foot=True,scale=scale)

    def background(self,title=False):
        self.art.draw('backgrounds/campus_title.png' if title else 'backgrounds/campus_gameplay.png',480,320,960,640)

    def gameplay(self):
        w,c = self.world,self.world.cat
        self.background()
        for left,right,floor in BALANCE['surfaces']:
            kind = 'ground' if floor == BALANCE['ground'] else 'platform'
            for x,width,part in tile_segments(left,right):
                image = self.art.image(f'v2/tiles/{kind}_{part}.png')
                image.clip_draw(0,0,width,32,x+width/2,floor-16,width,32)
        self.aim_guide()
        for item in w.items:
            if item.state=='PRE_SPAWN_WARNING':
                continue
            self.art.sprite(f'sprites/items/{item.kind}.png',item.x,item.y+math.sin(item.clock*4)*3,item.clock)
        if w.bandage_due is not None:
            p.draw_circle(480,BALANCE['ground']+8,24,78,173,118)
            for i in range(0,360,30):
                a = math.radians(i)
                p.draw_line(480+math.cos(a)*28,88+math.sin(a)*9,480+math.cos(a+.15)*28,88+math.sin(a+.15)*9,130,140,135)
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
            self.art.sprite('sprites/projectiles/paw_000.png',projectile.x,projectile.y,projectile.clock,
                            scale=projectile.scale,rotation=math.atan2(projectile.dy,projectile.dx))
        p.draw_rectangle(0,562,960,640,43,55,60,filled=True)
        p.draw_rectangle(0,0,960,46,43,55,60,filled=True)
        for i in range(3):
            self.art.draw(f'ui/heart_{"full" if i<c.hp else "empty"}.png',28+i*34,24,28,28)
        self.art.text('츄르',142,24,17,CREAM)
        for i in range(BALANCE['ammo_max']):
            self.art.draw(f'ui/ammo_{"full" if i<c.ammo else "empty"}.png',208+i*23,24,20,20)
        self.charge_hud()
        self.art.text('무한 생존',28,611,22,CREAM)
        self.art.text(f'생존 시간  {int(w.time)//60:02d}:{int(w.time)%60:02d}',28,581,18,(186,214,210))
        self.art.text('ESC  일시정지',780,580,14,(186,214,210))
        if w.warning_message:
            self.art.draw('ui/wave_banner.png',480,541,960,32)
            self.art.text('WARNING  ·  '+w.warning_message,480,541,19,CREAM,True)
        if w.notices and w.time-w.notices[-1][1] < 3:
            skin = w.notices[-1][0]
            self.panel(300,480,660,515)
            self.art.text(f'{SKIN_NAMES[SKINS.index(skin)]} 해금!',480,498,18,INK,True)
        if w.mode == 'PAUSED':
            self.pause_panel()
        elif w.mode == 'COUNTDOWN':
            self.art.outlined_text(str(max(1,math.ceil(w.countdown))),480,330)

    def volume(self,key,x,y):
        value = self.store.profile[key]
        label=('BGM' if key == 'bgm_volume' else 'SFX')+f'   {value}'
        self.art.text(label,x,y+28,17,INK)
        self.art.draw('ui/volume/track_base.png',x+128,y,256,32)
        fill = self.art.image('ui/volume/track_fill.png')
        end = 8+240*value/100
        if value:
            fill.clip_draw_to_origin(0,0,int(end),32,x,y-16,int(end),32)
        # A one-pixel texture row can disappear at 0.75x; SDL lines keep the axis readable.
        p.draw_line(x+8,y,x+248,y,135,137,137)
        if value:
            p.draw_line(x+8,y,x+end,y,224,145,53)
        self.art.draw('ui/volume/ticks.png',x+128,y,256,32)
        self.art.draw('ui/volume/knob.png',x+end,y,24,24)
        self.buttons.append(((x,y-15,x+256,y+15),('volume',key,x),True))

    def pause_panel(self):
        self.panel(285,120,675,495)
        self.art.text('잠깐 쉬어가기',480,455,28,INK,True)
        self.volume('bgm_volume',352,375)
        self.volume('sfx_volume',352,295)
        self.button('계속하기',(335,210,625,252),'resume')
        self.button('타이틀로 나가기',(335,150,625,192),'exit_run')

    def ranking(self,left,bottom,width=490):
        self.art.text('Record Score',left+300,bottom+10*34,14,INK)
        for i in range(10):
            y = bottom+(9-i)*34
            self.art.draw('ui/rank_row.png',left+width/2,y,width,30)
            self.art.text(f'{i+1:02}',left+120,y,15,CREAM)
            if i < len(self.store.records):
                row = self.store.records[i]
                self.art.text('LOCAL'+('  CLEAR' if row['cleared'] else ''),left+164,y,14,CREAM)
                self.art.text(f'{row["score"]:,}',left+300,y,15,CREAM)
            else:
                self.art.text('기록 없음',left+164,y,14,CREAM)

    def result(self):
        self.background(True)
        self.panel(35,40,925,600)
        title = '이번 산책의 기록' if self.scene == 'RESULT' else '로컬 랭킹'
        self.art.text(title,480,560,32,INK,True)
        if self.scene == 'RESULT':
            self.art.text(f'{self.world.score:,} 점  ·  생존 {self.world.time:.1f}초',480,513,22,INK,True)
            if self.new_record:
                self.art.draw('v3/ui/new_record.png',180,547)
        self.ranking(65,125,490)
        self.button('코스튬',(580,420,715,462),'costume')
        self.volume('bgm_volume',600,325)
        self.volume('sfx_volume',600,240)
        self.button('다시 시작하기' if self.scene == 'RESULT' else '시작하기',(580,115,865,164),'start')
        self.button('타이틀',(580,57,865,99),'title')
        if self.skin_popup:
            self.panel(725,320,915,555)
            self.buttons.append(((725,320,915,555),None,True))
            self.art.text('장착 중',820,537,13,INK,True)
            self.cat(820,463,'idle',self.ui_clock)
            for i,skin in enumerate(SKINS):
                x,y = 758+(i%3)*58,438-(i//3)*42
                owned = skin in self.store.profile['unlocked_skin_ids']
                if skin == self.selected_skin and owned:
                    self.art.sprite(f'sprites/cat/{skin}/groom.png',x,y-14,self.ui_clock,foot=True,scale=.5)
                else:
                    self.art.draw(f'ui/portraits/{skin}.png',x,y,32,32,alpha=1 if owned else .3)
                if not owned:
                    self.art.draw('ui/lock.png',x,y,16,16)
                if skin == self.selected_skin:
                    p.draw_rectangle(x-18,y-18,x+18,y+18,232,142,50)
                self.buttons.append(((x-20,y-18,x+20,y+18),('skin',skin),owned))
            self.button('장착',(751,332,891,366),'equip')
        if self.achievement_queue and self.scene=='RESULT':
            self.achievement_popup()

    def achievement_popup(self):
        skin=self.achievement_queue[0]
        info=ACHIEVEMENT_INFO[skin]
        self.panel(275,160,685,510)
        self.art.text('업적 달성!',480,478,26,INK,True)
        self.art.text(info['name'],480,437,22,INK,True)
        self.art.text(info['description'],480,401,16,INK,True)
        self.cat(480,300,'groom',self.ui_clock,skin,scale=2.)
        self.art.text(f'{SKIN_NAMES[SKINS.index(skin)]} 해금!',480,269,20,INK,True)
        self.buttons.append(((0,0,960,640),None,True))
        self.button('X',ACHIEVEMENT_CLOSE,'achievement_close')

    def controls_panel(self):
        self.panel(*CONTROLS_PANEL)
        self.art.text('조작 방법',480,459,24,INK,True)
        rows=(('A / D','좌우 이동'),('W / SPACE','더블 점프'),('S + SPACE','발판 아래로 내려가기'),
              ('SHIFT','대시 2회 · 공유 충전'),('마우스 좌','조준 방향 일반탄'),('마우스 우','관통탄 · 츄르 10개 충전'),
              ('ESC','일시정지 / 계속하기'),('F11','전체 화면'))
        for i,(key,description) in enumerate(rows):
            y=419-i*27
            self.art.text(key,296,y,16)
            self.art.text(description,420,y,16)

    def aim_guide(self):
        w,c=self.world,self.world.cat
        x,y=c.x,c.y+26
        dx,dy=w.aim_direction()
        distances=[(bound-origin)/direction for origin,direction,bounds in
                   ((x,dx,(0,960)),(y,dy,(BALANCE['ground'],560))) if abs(direction)>1e-9
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

        for distance in range(28,int(length),24):
            end=min(distance+15,length)
            stroke(x+dx*distance,y+dy*distance,x+dx*end,y+dy*end)
        mx,my=w.aim
        if 0<=mx<=960 and BALANCE['ground']<=my<=560:
            for radii,color in ((range(10,15),(26,35,43)),(range(11,14),(255,226,69))):
                for radius in radii:
                    p.draw_circle(mx,my,radius,*color)
            for ax,ay,bx,by in ((mx-21,my,mx-7,my),(mx+7,my,mx+21,my),
                               (mx,my-21,mx,my-7),(mx,my+7,mx,my+21)):
                stroke(ax,ay,bx,by)

    def charge_hud(self):
        c=self.world.cat
        self.art.text(f'대시 {c.dash_charges}/2',315,24,15,CREAM)
        progress=1-c.dash_cd/BALANCE['dash_cooldown']
        for i in range(BALANCE['dash_max_charges']):
            left=405+i*54
            p.draw_rectangle(left,16,left+49,31,91,109,112,filled=True)
            fill=1. if i<c.dash_charges else progress if i==c.dash_charges else 0.
            if fill>0:
                p.draw_rectangle(left+1,17,left+1+47*fill,30,131,222,188,filled=True)
        for i in range(BALANCE['pierce_max_charges']):
            x=662+i*56
            ready=i<c.pierce_charges
            self.art.sprite('sprites/projectiles/paw_000.png',x,24,self.ui_clock,scale=.84,alpha=1. if ready else .22)
            if ready:
                points=[]
                for j in range(40):
                    angle=j*math.tau/40
                    radius=19+2*math.sin(angle*5+self.ui_clock*7+i)
                    points.append((x+math.cos(angle)*radius,24+math.sin(angle)*radius))
                for a,b in zip(points,points[1:]+points[:1]):
                    p.draw_line(*a,*b,255,203,107)
        self.art.text(f'츄르 {c.churu_collected}/10',831,24,14,CREAM)

    def draw(self):
        p.clear_canvas()
        self.buttons = []
        if self.scene == 'PLAY':
            self.gameplay()
        elif self.scene in ('RESULT','RANKING'):
            self.result()
        else:
            self.background(True)
            self.art.draw('ui/title_logo.png',480,477,420,280)
            self.cat(480,255,'groom' if self.ui_clock%8>4 else 'idle',self.ui_clock)
            self.button('시작하기',(335,182,625,230),'start')
            self.button('키 설명',CONTROLS_BUTTON,'controls')
            if self.controls_popup:
                self.controls_panel()
        if self.error:
            self.panel(30,10,930,42)
            self.art.text(self.error[:80],45,26,13,(151,44,44))

    def action(self,action,x):
        if action is not None:
            self.audio.play('click')
        if isinstance(action,tuple):
            if action[0] == 'volume':
                _,key,left = action
                self.dragging = (key,left)
                self.change_volume(x)
            elif action[0] == 'skin':
                self.selected_skin = action[1]
            return
        if action == 'start':
            self.start()
        elif action == 'resume':
            self.world.pause()
            self.keys.clear()
        elif action == 'exit_run':
            if self.world.mode in ('PLAYING','PAUSED','COUNTDOWN'):
                self.world.finish_run()
        elif action == 'title':
            self.show_title()
            self.skin_popup = False
            self.controls_popup = False
        elif action == 'controls' and self.scene=='TITLE':
            self.controls_popup = not self.controls_popup
        elif action == 'achievement_close' and self.achievement_queue:
            self.achievement_queue.pop(0)
        elif action == 'ranking':
            self.show_ranking()
        elif action == 'costume':
            self.skin_popup = not self.skin_popup
            self.selected_skin = self.store.profile['equipped_skin_id']
        elif action == 'equip':
            if self.selected_skin in self.store.profile['unlocked_skin_ids']:
                self.store.profile['equipped_skin_id'] = self.selected_skin
                self.save()
                self.skin_popup = False

    def change_volume(self,x):
        if self.dragging:
            key,left = self.dragging
            self.store.profile[key] = max(0,min(100,int((x-left-8)/240*10+.5)*10))
            self.audio.volumes(self.store.profile)

    def click(self,x,y):
        if self.controls_popup and self.scene=='TITLE':
            if contains(CONTROLS_BUTTON,x,y):
                self.action('controls',x)
            elif not contains(CONTROLS_PANEL,x,y):
                self.controls_popup=False
                self.audio.play('click')
            return
        if self.achievement_queue and self.scene=='RESULT':
            if contains(ACHIEVEMENT_CLOSE,x,y):
                self.action('achievement_close',x)
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
                elif self.achievement_queue and self.scene=='RESULT':
                    continue
                elif key == p.SDLK_ESCAPE:
                    if self.controls_popup:
                        self.controls_popup=False
                    elif self.skin_popup:
                        self.skin_popup = False
                    elif self.scene == 'PLAY':
                        self.world.pause()
                        self.keys.clear()
                    elif self.scene != 'TITLE':
                        self.show_title()
                elif key == p.SDLK_RETURN:
                    if self.scene in ('TITLE','RESULT','RANKING'):
                        self.start()
                    elif self.world.mode == 'PAUSED':
                        self.world.pause()
                elif self.scene == 'PLAY':
                    if key in (p.SDLK_SPACE,p.SDLK_w):
                        self.world.jump(self.keys)
                    elif key in (p.SDLK_LSHIFT,p.SDLK_RSHIFT):
                        self.world.dash(self.keys)
            elif event.type in (p.SDL_MOUSEMOTION,p.SDL_MOUSEBUTTONDOWN,p.SDL_MOUSEBUTTONUP):
                data = event.motion if event.type == p.SDL_MOUSEMOTION else event.button
                self.mouse = data.x,640-data.y
                if self.scene=='PLAY' and self.world.mode=='PLAYING':
                    self.world.aim=self.mouse
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

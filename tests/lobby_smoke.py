"""Real SDL lobby navigation, data binding, modal isolation and viewport checks."""
from pathlib import Path
import copy
import ctypes
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App, p, native, capture, INK, RESULT_SECONDS
from game.lobby import MENU
from game.model import DEATH_SECONDS

OUTPUT=ROOT/'output/preview2_step3'
OUTPUT.mkdir(parents=True,exist_ok=True)


def main():
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
        app=App(folder)
        try:
            app.store.profile['gold']=321
            app.store.profile['characters']['nabi'].update(level=4,exp=37,skill_points=3)
            app.store.save_profile()
            records=[]
            original_text=app.art.text
            def checked_text(text,x,y,size=18,color=INK,center=False):
                original_text(text,x,y,size,color,center)
                label=app.art.labels[(text,size,color)]
                left=x-label.w/2 if center else x
                assert 0<=left and left+label.w<=960,(text,left,label.w)
                assert 0<=y-label.h/2 and y+label.h/2<=640,(text,y,label.h)
                records.append(text)
            app.art.text=checked_text
            def key(code):
                event=p.SDL_Event()
                event.type=p.SDL_KEYDOWN
                event.key.keysym.sym=code
                p.SDL_PushEvent(ctypes.byref(event))
                app.events()
            app.draw()
            capture(OUTPUT/'title_before_lobby.png')
            app.click(480,205)
            assert app.scene=='LOBBY' and app.world is None
            app.draw()
            assert 'GOLD   321' in records and 'EXP  37 / 175' in records
            capture(OUTPUT/'lobby.png')
            for name,(_,rect) in MENU.items():
                app.draw()
                app.click((rect[0]+rect[2])/2,(rect[1]+rect[3])/2)
                assert app.lobby.panel==name
                records.clear()
                app.draw()
                capture(OUTPUT/f'lobby_{name}.png')
                if name=='character':
                    assert '???' not in records
                if name=='shop':
                    before=copy.deepcopy(app.store.profile)
                    assert app.lobby.shop_category=='equipment'
                    assert '전체' not in records
                    app.click(580,417)
                    assert app.lobby.confirm is None
                    app.click(120,440)
                    app.draw()
                    assert app.lobby.shop_category=='character'
                    assert [action for _,action,_ in app.buttons if action[1] in ('buy_black','gacha')]==[('lobby','buy_black')]
                    app.click(120,496)
                    app.draw()
                    assert app.lobby.shop_category=='equipment'
                    assert [action for _,action,_ in app.buttons if action[1] in ('buy_black','gacha')]==[('lobby','gacha'),('lobby','gacha',10)]
                    app.click(340,417)
                    assert app.lobby.confirm['args']=={'count':1}
                    assert app.store.profile==before
                    app.action(('lobby','cancel'),0)
                    assert app.lobby.shop_category=='equipment'
                    app.draw()
                    app.click(120,440)
                key(p.SDLK_RETURN)
                assert app.scene=='LOBBY' and app.world is None
                key(p.SDLK_ESCAPE)
                assert app.lobby.panel is None
                if name=='shop':
                    app.lobby.open(app,'shop')
                    assert app.lobby.shop_category=='equipment'
                    app.lobby.close(app)
            app.draw()
            assert 'title' not in [action for _,action,_ in app.buttons]
            app.click(907,591)
            assert app.lobby.panel=='settings'
            app.draw()
            capture(OUTPUT/'lobby_settings.png')
            app.click(480,365)
            assert app.lobby.panel=='sound'
            sound_bounds=app.lobby.bounds
            app.draw()
            capture(OUTPUT/'lobby_sound.png')
            app.click(360,365)
            assert app.store.profile['bgm_volume']==0
            if app.audio.available:assert p.Mix_VolumeMusic(-1)==0
            app.change_volume(600)
            assert app.store.profile['bgm_volume']==100
            app.click(50,50)
            assert app.dragging is None and app.lobby.panel=='settings'
            app.draw()
            app.click(480,282)
            assert app.lobby.panel=='controls'
            assert app.lobby.bounds==sound_bounds
            app.draw()
            capture(OUTPUT/'lobby_controls.png')
            # Outside click closes the panel without activating the launch behind it.
            app.click(775,104)
            assert app.lobby.panel=='settings' and app.scene=='LOBBY' and app.world is None
            key(p.SDLK_ESCAPE)
            assert app.lobby.panel is None
            app.draw()
            key(p.SDLK_RETURN)
            assert app.scene=='PLAY'
            app.world.run_exp,app.world.run_gold=240,80
            app.world.time=90
            app.world.begin_death()
            app.update(DEATH_SECONDS+.01)
            assert app.scene=='RESULT' and app.saved_result
            app.result_clock=RESULT_SECONDS
            app.draw()
            app.click(775,104)
            assert app.scene=='LOBBY'
            records.clear()
            app.draw()
            assert 'GOLD   401' in records and 'Lv. 5' in records and 'EXP  102 / 200' in records
            capture(OUTPUT/'lobby_after_settlement.png')
            assert '0' not in records
            app.store.profile['stats'].update(kills=100,bee=30)
            records.clear()
            app.draw()
            assert '3' in records
            capture(OUTPUT/'lobby_claimable.png')
            app.click(775,255)
            app.draw()
            app.click(757,438)
            app.draw()
            app.click(602,226)
            app.draw()
            app.click(766,509)
            records.clear()
            app.draw()
            assert '2' in records and '3' not in records
            # Every panel is also rendered at both supported representative sizes.
            for width,height in ((720,480),(1280,720)):
                p.SDL_SetWindowSize(native.window,width,height)
                for _ in range(4):
                    p.SDL_PumpEvents()
                    app.draw()
                    p.update_canvas()
                app.draw()
                capture(OUTPUT/f'lobby_{width}x{height}.png')
                for name in (*MENU,'settings','sound','controls'):
                    app.lobby.open(app,name)
                    app.draw()
                    capture(OUTPUT/f'lobby_{name}_{width}x{height}.png')
                    app.lobby.close(app)
                x,y=ctypes.c_float(),ctypes.c_float()
                p.SDL_RenderWindowToLogical(native.renderer,width//2,height//2,ctypes.byref(x),ctypes.byref(y))
                assert abs(x.value-480)<1 and abs(y.value-320)<1
            app.action('title',0)
            app.draw()
            key(p.SDLK_RETURN)
            assert app.scene=='LOBBY'
            print('LOBBY SDL PASS: lobby panels, sound and keys navigation, live claimable count, purchase confirmations and volume')
            print('LOBBY BOUNDS PASS: all rendered text fits 960x640; 720x480 and 1280x720 panels and logical centers')
        finally:
            app.close()
            p.close_canvas()


if __name__=='__main__':
    main()

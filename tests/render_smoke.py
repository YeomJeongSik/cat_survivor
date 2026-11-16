"""Real SDL rendering of every manifest asset and interactive screen; uses disposable saves."""
from pathlib import Path
import ctypes
import sys
import tempfile
import time
import statistics
from unittest.mock import patch
import copy

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'output/preview2_step2'
OUTPUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
from game.app import App, capture, p, native
from game.model import Enemy, SKINS, DEATH_SECONDS
from game.audio import COMBAT_SOUNDS, CHANNELS


def main():
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
        app=App(folder)
        try:
            assert not app.scene_machine.auto_transitions
            app.draw()
            capture(OUTPUT/'title_first_run.png')
            assert [action for _,action,_ in app.buttons]==['start','controls']
            app.click(480,155)
            assert app.controls_popup
            app.draw()
            capture(OUTPUT/'title_controls.png')
            app.click(480,320)
            assert app.controls_popup
            app.click(480,155)
            assert not app.controls_popup
            app.click(480,155)
            app.click(20,20)
            assert not app.controls_popup and app.scene=='TITLE'
            app.show_title()  # Repeated menu clicks must remain harmless.
            app.start()
            app.world.cat.x,app.world.cat.y=200,195
            for event_type,key in ((p.SDL_KEYDOWN,p.SDLK_s),(p.SDL_KEYDOWN,p.SDLK_SPACE)):
                event=p.SDL_Event()
                event.type=event_type
                event.key.keysym.sym=key
                p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert app.world.cat.state=='FALL' and app.world.cat.y<195
            for key in (p.SDLK_s,p.SDLK_SPACE):
                event=p.SDL_Event()
                event.type=p.SDL_KEYUP
                event.key.keysym.sym=key
                p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert 'down' not in app.keys
            app.start()
            def mouse(event_type,x,y,button=p.SDL_BUTTON_LEFT):
                event=p.SDL_Event()
                event.type=event_type
                data=event.motion if event_type==p.SDL_MOUSEMOTION else event.button
                data.x,data.y=int(x),640-int(y)
                if event_type!=p.SDL_MOUSEMOTION:
                    event.button.button=button
                p.SDL_PushEvent(ctypes.byref(event))
                app.events()
            mouse(p.SDL_MOUSEBUTTONDOWN,850,350)
            assert app.world.cat.ammo==3 and 'shoot' in app.keys
            bullet=app.world.projectiles[0]
            direction=(bullet.dx,bullet.dy)
            mouse(p.SDL_MOUSEMOTION,50,250)
            app.update(.26)
            assert (bullet.dx,bullet.dy)==direction
            assert app.world.cat.ammo==2
            mouse(p.SDL_MOUSEBUTTONUP,50,250)
            assert 'shoot' not in app.keys
            app.world.cat.pierce_charges=1
            app.world.cat.ammo=0
            mouse(p.SDL_MOUSEBUTTONDOWN,800,400,p.SDL_BUTTON_RIGHT)
            assert app.world.cat.pierce_charges==0 and app.world.cat.ammo==0
            assert app.world.projectiles[-1].piercing
            mouse(p.SDL_MOUSEBUTTONUP,800,400,p.SDL_BUTTON_RIGHT)
            app.world.cat.pierce_charges=3
            app.world.cat.ammo=4
            app.world.cat.churu_collected=9
            app.world.cat.dash_charges=1
            app.world.cat.dash_cd=.7
            app.draw()
            capture(OUTPUT/'combat_charges_current.png')
            app.ui_clock+=.2
            app.draw()
            capture(OUTPUT/'combat_charges_ripple.png')
            app.draw()
            assert not any(isinstance(action,tuple) and action[0]=='volume' for _,action,_ in app.buttons)
            app.world.enemies=[Enemy(200,480,species='magpie'),Enemy(350,250,species='squirrel'),
                               Enemy(600,350,species='bee'),Enemy(480,102,species='snake',state='CHARGE')]
            app.world.enemies[0].damage()
            app.draw()
            capture(OUTPUT/'enemy_hp_snake_charge.png')
            app.world.time=27.1
            app.draw()
            capture(OUTPUT/'warning_bee.png')
            assert app.world.warning_message
            assert app.world.rules['start']==0
            app.world.time=30
            assert not app.world.warning_message and app.world.rules['start']==30
            app.world.time=537.1
            app.draw()
            capture(OUTPUT/'warning_combination.png')
            assert app.world.warning_message
            app.world.time=0
            app.world.time=600
            app.world.enemies=[]
            for index in range(500):
                app.world.spawn_enemy(('magpie','squirrel','bee','snake')[index%4])
                if sum(e.alive for e in app.world.enemies)==24:
                    break
            assert sum(e.alive for e in app.world.enemies)==24
            timings=[]
            for _ in range(120):
                before=time.perf_counter()
                app.draw()
                p.update_canvas()
                timings.append((time.perf_counter()-before)*1000)
                app.ui_clock+=1/60
            capture(OUTPUT/'cap_24_enemies.png')
            print(f'RENDER TIMING (24 enemies, no vsync): mean={statistics.mean(timings):.2f}ms p95={sorted(timings)[114]:.2f}ms')
            app.world.time=0
            app.world.enemies=[]

            app.world.pause()
            app.draw()
            capture(OUTPUT/'pause_first_run.png')
            app.action(('volume','bgm_volume',352),360)
            assert app.store.profile['bgm_volume']==0
            app.change_volume(600)
            assert app.store.profile['bgm_volume']==100
            if app.audio.available:
                assert p.Mix_VolumeMusic(-1)==128
                app.change_volume(360)
                assert p.Mix_VolumeMusic(-1)==0
                app.change_volume(600)
                app.audio.play('siren')
                assert p.Mix_Playing(5)==1
                assert p.Mix_PlayingMusic()==1
                assert app.audio.current=='jelly_rush'
                app.store.profile['sfx_volume']=0
                app.audio.volumes(app.store.profile)
                assert p.Mix_Volume(0,-1)==0 and p.Mix_VolumeMusic(-1)==128
                app.store.profile['sfx_volume']=70
                app.audio.volumes(app.store.profile)
                for name in COMBAT_SOUNDS:
                    app.audio.play(name)
                    channel=CHANNELS[name]
                    assert p.Mix_Playing(channel)==1,name
                    assert ctypes.cast(p.Mix_GetChunk(channel),ctypes.c_void_p).value==ctypes.cast(app.audio.sounds[name].wav,ctypes.c_void_p).value,name
                for species in ('magpie','squirrel','bee','snake'):
                    assert p.Mix_Playing(CHANNELS[species+'_attack'])==1
                print('COMBAT AUDIO PASS: all 8 v2 WAVs play on the expected SDL channels')
                print('AUDIO MIXER PASS: real BGM playback, live 0/100 volume, siren SFX channel')
            app.dragging=None
            app.world.pause()
            app.draw()
            capture(OUTPUT/'countdown_current.png')
            app.world.update(3)
            app.world.cat.invincible=99999
            app.world.spawn_enemy('magpie')
            app.world.shoot()
            app.world.update(.05)
            assert app.world.projectiles
            app.draw()
            capture(OUTPUT/'mouse_aim_current.png')
            for species in ('magpie','squirrel','bee','snake'):
                prefix=f'sprites/enemies/{species}/'
                for file in app.art.specs:
                    if file.startswith(prefix):
                        state=Path(file).stem.upper()
                        for grade in range(3):
                            app.world.enemies=[Enemy(400,230,state=state,species=species,grade=grade)]
                            app.draw()
            for skin in SKINS:
                for state in ('idle','walk','jump','fall','dash','attack','hit','dead','groom'):
                    app.cat(480,100,state,.2,skin)
            app.world.run_exp=240
            app.world.run_gold=80
            app.world.cat.hp=0
            app.world.begin_death()
            app.update(DEATH_SECONDS/2)
            assert app.scene=='PLAY' and app.world.mode=='DYING'
            app.draw()
            capture(OUTPUT/'cat_death_current.png')
            app.update(DEATH_SECONDS/2+.01)
            assert app.scene=='RESULT'
            assert app.saved_result
            assert app.store.profile['gold']==80
            assert app.store.profile['characters']['nabi']['level']==3
            original_id=app.world.run_id
            app.result_clock=0
            app.draw()
            capture(OUTPUT/'result_count_start.png')
            app.update(.8)
            app.draw()
            capture(OUTPUT/'result_count_exp.png')
            app.update(.9)
            app.draw()
            capture(OUTPUT/'result_count_gold.png')
            event=p.SDL_Event()
            event.type=p.SDL_KEYDOWN
            event.key.keysym.sym=p.SDLK_RETURN
            p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert app.scene=='RESULT' and app.world.run_id==original_id and app.result_clock==3
            app.draw()
            capture(OUTPUT/'result_complete.png')
            assert [action for _,action,_ in app.buttons]==['start','title']
            assert not hasattr(app,'show_ranking')
            # A later, separate Enter restarts.
            p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert app.scene=='PLAY' and app.world.run_id!=original_id
            before=copy.deepcopy(app.store.profile)
            app.world.run_exp,app.world.run_gold=12,8
            app.world.begin_death()
            with patch.object(app.store,'write',side_effect=OSError('test: disk unavailable')):
                app.update(DEATH_SECONDS+.01)
            assert app.scene=='RESULT' and not app.saved_result
            assert app.store.profile==before
            app.draw()
            capture(OUTPUT/'result_save_failed.png')
            for key in (p.SDLK_RETURN,p.SDLK_ESCAPE):
                event.key.keysym.sym=key
                p.SDL_PushEvent(ctypes.byref(event))
                app.events()
                assert app.scene=='RESULT' and not app.saved_result
            app.click(480,100)
            assert app.saved_result and app.store.profile['gold']==88
            app.click(480,320)
            app.start()
            app.store.profile['characters']['nabi'].update(level=50,exp=0,skill_points=50)
            app.world.run_exp,app.world.run_gold=123,9
            app.world.begin_death()
            app.update(DEATH_SECONDS+.01)
            app.result_clock=3
            app.draw()
            capture(OUTPUT/'result_max_level.png')
            assert app.settlement['applied_exp']==0 and app.settlement['converted_gold']==62
            for file in app.art.specs:
                image=app.art.image(file)
                assert image.w==app.art.specs[file]['width'] and image.h==app.art.specs[file]['height'],file
            for file,spec in app.art.v2_specs.items():
                image=app.art.image('v2/'+file)
                assert (image.w,image.h)==(spec['width'],spec['height']),file
            for file,spec in app.art.v3_specs.items():
                image=app.art.image('v3/'+file)
                assert (image.w,image.h)==(spec['width'],spec['height']),file
            app.start()
            app.world.run_exp,app.world.run_gold=100,100
            before=copy.deepcopy(app.store.profile)
            app.world.pause()
            app.draw()
            app.click(480,170)
            app.draw()
            capture(OUTPUT/'abandon_confirm.png')
            assert app.exit_confirm
            app.click(380,280)
            assert app.world.mode=='PAUSED' and not app.exit_confirm
            app.draw()
            app.click(480,170)
            app.draw()
            app.click(580,280)
            assert app.scene=='TITLE' and app.store.profile==before
            assert app.world.run_exp==app.world.run_gold==0
            app.start()
            app.world.pause()
            for width,height in ((720,480),(1280,720)):
                p.SDL_SetWindowSize(native.window,width,height)
                for _ in range(5):
                    p.SDL_PumpEvents()
                    app.draw()
                    p.update_canvas()
                x,y=ctypes.c_float(),ctypes.c_float()
                p.SDL_RenderWindowToLogical(native.renderer,width//2,height//2,ctypes.byref(x),ctypes.byref(y))
                assert abs(x.value-480)<1 and abs(y.value-320)<1,(x.value,y.value)
                app.draw()
                capture(OUTPUT/f'pause_{width}x{height}.png')
            print(f'RENDER PASS: {len(app.art.specs)} manifest assets; title/play/pause/result; 6 skins; all enemy states/grades; volume endpoints')
            print('VIEWPORT PASS: 720x480 and 1280x720 logical center/mouse transform')
        finally:
            app.audio.close()
            app.art.labels.clear()
            app.art.images.clear()
            p.close_canvas()


if __name__=='__main__':
    main()

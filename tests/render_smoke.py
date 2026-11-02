"""Real SDL rendering of every manifest asset and interactive screen; uses disposable saves."""
from pathlib import Path
import ctypes
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
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
            capture(ROOT/'output/title_first_run.png')
            assert [action for _,action,_ in app.buttons]==['start','controls']
            app.click(480,155)
            assert app.controls_popup
            app.draw()
            capture(ROOT/'output/title_controls.png')
            app.click(480,320)
            assert app.controls_popup
            app.click(480,155)
            assert not app.controls_popup
            app.click(480,155)
            app.click(20,20)
            assert not app.controls_popup and app.scene=='TITLE'
            app.show_ranking()
            assert app.scene=='RANKING'
            app.draw()
            app.show_title()
            app.show_title()  # Repeated menu clicks must remain harmless.
            app.start()
            app.world.cat.x,app.world.cat.y=200,195
            for event_type,key in ((p.SDL_KEYDOWN,p.SDLK_DOWN),(p.SDL_KEYDOWN,p.SDLK_SPACE)):
                event=p.SDL_Event()
                event.type=event_type
                event.key.keysym.sym=key
                p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert app.world.cat.state=='FALL' and app.world.cat.y<195
            for key in (p.SDLK_DOWN,p.SDLK_SPACE):
                event=p.SDL_Event()
                event.type=p.SDL_KEYUP
                event.key.keysym.sym=key
                p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert 'down' not in app.keys
            app.start()
            app.draw()
            assert not any(isinstance(action,tuple) and action[0]=='volume' for _,action,_ in app.buttons)
            app.world.enemies=[Enemy(200,480,species='magpie'),Enemy(350,250,species='squirrel'),
                               Enemy(600,350,species='bee'),Enemy(480,102,species='snake',state='CHARGE')]
            app.world.enemies[0].damage()
            app.draw()
            capture(ROOT/'output/enemy_hp_snake_charge.png')
            app.world.pause()
            app.draw()
            capture(ROOT/'output/pause_first_run.png')
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
            capture(ROOT/'output/countdown_current.png')
            app.world.update(3)
            app.world.cat.invincible=99999
            app.world.spawn_enemy('magpie')
            app.world.shoot()
            app.world.update(.05)
            assert app.world.projectiles
            app.draw()
            capture(ROOT/'output/homing_first_run.png')
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
            app.world.unlocked.update(('bee_golden','snake_silver'))
            app.world.cat.hp=0
            app.world.begin_death()
            app.update(DEATH_SECONDS/2)
            assert app.scene=='PLAY' and app.world.mode=='DYING'
            app.draw()
            capture(ROOT/'output/cat_death_current.png')
            app.update(DEATH_SECONDS/2+.01)
            assert app.scene=='RESULT'
            assert app.achievement_queue==['bee_golden','snake_silver']
            app.draw()
            capture(ROOT/'output/achievement_current.png')
            app.click(700,135)  # The underlying restart button must stay blocked.
            assert app.scene=='RESULT' and len(app.achievement_queue)==2
            event=p.SDL_Event()
            event.type=p.SDL_KEYDOWN
            event.key.keysym.sym=p.SDLK_RETURN
            p.SDL_PushEvent(ctypes.byref(event))
            app.events()
            assert app.scene=='RESULT' and len(app.achievement_queue)==2
            app.click(480,204)
            assert app.achievement_queue==['snake_silver']
            app.draw()
            app.click(480,204)
            assert not app.achievement_queue
            assert {'bee_golden','snake_silver'}<=set(app.store.profile['unlocked_skin_ids'])
            app.store.profile['unlocked_skin_ids']=list(SKINS)
            app.skin_popup=True
            app.draw()
            capture(ROOT/'output/result_first_run.png')
            assert app.new_record
            assert 35 < 180-120 and 180+120 < 330 and 40 < 547-48 < 547+48 < 600
            # The popup is to the costume button's right and completely inside the main panel.
            assert 715<725<915<925 and 40<320<555<600
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
            app.world.finish_run()
            app.update(0)
            assert app.scene=='RESULT' and not app.achievement_queue
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
                capture(ROOT/f'output/pause_{width}x{height}.png')
            print(f'RENDER PASS: {len(app.art.specs)} manifest assets; title/play/pause/result; 6 skins; all enemy states/grades; volume endpoints')
            print('VIEWPORT PASS: 720x480 and 1280x720 logical center/mouse transform')
        finally:
            app.audio.close()
            app.art.labels.clear()
            app.art.images.clear()
            p.close_canvas()


if __name__=='__main__':
    main()

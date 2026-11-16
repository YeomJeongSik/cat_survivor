"""Actual SDL walkthrough of buying, combat, equipment, achievements and recovery."""
from pathlib import Path
import ctypes
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App,p,native,capture,INK,RESULT_SECONDS
from game.model import Enemy,DEATH_SECONDS
from game.equipment import material_allowed,bonuses
OUTPUT=ROOT/'output/preview2_complete'
OUTPUT.mkdir(parents=True,exist_ok=True)


def main():
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
        app=App(folder)
        def checked_text():
            original=app.art.text
            def text(value,x,y,size=18,color=INK,center=False):
                original(value,x,y,size,color,center)
                label=app.art.labels[(value,size,color)]
                left=x-label.w/2 if center else x
                assert left>=0 and left+label.w<=960,(value,left,label.w)
                assert y-label.h/2>=0 and y+label.h/2<=640,(value,y,label.h)
            app.art.text=text
        def draw(name=None):
            app.draw()
            if name:capture(OUTPUT/(name+'.png'))
            p.update_canvas()
        def click(x,y):
            app.click(x,y)
            draw()
        def confirm():
            click(602,226)
        try:
            checked_text()
            app.store.profile['gold']=100000
            app.store.save_profile()
            draw();click(480,205)
            click(775,317);click(310,214);draw('buy_black_confirmation');confirm()
            assert 'black' in app.store.profile['characters']
            assert app.store.profile['selected_character_id']=='nabi'
            click(766,509);click(775,503);click(200,316)
            assert app.store.profile['selected_character_id']=='nabi'
            draw('black_character');click(670,154)
            assert app.store.profile['selected_character_id']=='black'
            draw('black_lobby')
            click(775,104)
            w=app.world
            w.next_spawn_at=float('inf')
            w.enemies=[Enemy(w.cat.x+60,w.cat.y+26,species='squirrel')]
            event=p.SDL_Event()
            event.type=p.SDL_MOUSEBUTTONDOWN
            event.button.button=p.SDL_BUTTON_LEFT
            event.button.x,event.button.y=int(w.cat.x+80),640-int(w.cat.y+26)
            p.SDL_PushEvent(ctypes.byref(event));app.events()
            assert w.enemies[0].hp==.5 and not w.projectiles
            draw('black_melee')
            event.type=p.SDL_MOUSEBUTTONUP
            p.SDL_PushEvent(ctypes.byref(event));app.events()
            w.pause();draw();click(480,170);click(580,280)
            assert app.scene=='LOBBY'
            click(775,317)
            before=app.store.profile['gold']
            for _ in range(3):
                click(650,214);confirm()
            assert app.store.profile['gold']==before-450 and len(app.store.profile['items'])==3
            draw('gacha_result')
            def fixture(key,definition):
                return dict(id=key,definition=definition,enhancement=0,stacks=0,locked=False)
            app.store.profile['items'] += [fixture('target','bell_common'),fixture('material','bell_common'),fixture('sale','bell_legendary')]
            app.store.save_profile()
            click(766,509);click(775,379)
            click(200,266)
            assert app.lobby.item_id=='target'
            click(607,336);confirm()
            assert app.store.profile['equipment_slots'][0]=='target'
            assert bonuses(app.store.profile)['damage']==.08
            click(460,475);confirm()
            assert app.store.profile['unlocked_slots']==2
            click(210,475)
            click(607,281);draw('enhancement_confirmation');confirm()
            target=next(i for i in app.store.profile['items'] if i['id']=='target')
            click(772,281)
            shown=[i for i in app.store.profile['items'] if material_allowed(app.store.profile,target,i)]
            index=next(i for i,value in enumerate(shown) if value['id']=='material')
            app.lobby.page=index//5;draw()
            click(200,392-index%5*42);draw('stack_confirmation');confirm()
            target=next(i for i in app.store.profile['items'] if i['id']=='target')
            assert target['stacks']==1 and not any(i['id']=='material' for i in app.store.profile['items'])
            click(607,226)
            assert next(i for i in app.store.profile['items'] if i['id']=='target')['locked']
            click(607,226)
            click(772,336);confirm()
            assert app.store.profile['equipment_slots'][0] is None
            before=app.store.profile['gold']
            click(772,226);draw('sale_confirmation');confirm()
            assert app.store.profile['gold']==before+45
            draw('equipment')
            click(766,509);click(775,104)
            app.world.next_spawn_at=float('inf')
            app.world.enemies=[Enemy(app.world.cat.x+50,app.world.cat.y+26,species='bee')]
            app.world.aim=(960,app.world.cat.y+26)
            app.world.shoot()
            assert app.world.run_kills['bee']==1
            app.world.begin_death();app.update(DEATH_SECONDS+.01)
            app.result_clock=RESULT_SECONDS;draw('black_result');click(775,104)
            click(775,255)
            before=app.store.profile['gold']
            click(757,438);draw('achievement_claim');confirm()
            assert app.store.profile['gold']==before+30
            draw('achievements')
            click(766,509);click(775,317);click(650,214)
            write=app.store.write
            def fail_profile(name,value):
                if name=='profile.json':raise OSError('test: disk full')
                write(name,value)
            with patch.object(app.store,'write',side_effect=fail_profile):
                confirm()
            assert app.store.pending
            request_id=app.store.pending['id']
            before=app.store.profile['gold'];count=len(app.store.profile['items'])
            draw('transaction_retry')
            app.start()
            assert app.scene=='LOBBY'
            app.close()
            app=App(folder);checked_text()
            draw();click(480,205);draw('recovered_pending')
            assert app.store.pending['id']==request_id
            confirm()
            assert not app.store.pending
            assert app.store.profile['gold']==before-150 and len(app.store.profile['items'])==count+1
            for width,height in ((720,480),(1280,720)):
                p.SDL_SetWindowSize(native.window,width,height)
                for _ in range(3):p.SDL_PumpEvents();draw()
                for name in ('character','equipment','shop','achievements','skills'):
                    app.lobby.open(app,name);draw(f'{name}_{width}x{height}');app.lobby.close(app)
            print('COMPLETE SDL PASS: real character purchase/selection, melee input, gacha, equip/unlock/enhance/stack/lock/sale, death, achievement claim, process-reopen transaction retry')
            print('COMPLETE VIEWPORT PASS: text bounds and full panels at 720x480 / 1280x720')
        finally:
            app.close()
            p.close_canvas()


if __name__=='__main__':
    main()

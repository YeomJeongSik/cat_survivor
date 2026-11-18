"""Actual SDL walkthrough of ten-pull reveal, rarity light, NEW and save retry."""
from pathlib import Path
import ctypes
import sys
import tempfile
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App,p,native,capture,INK
from game.storage import Store
from game.gacha import GachaReveal
OUTPUT=ROOT/'output/nyangi_art_v6/verification'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            app=App(folder)
            original_text=app.art.text
            def text(value,x,y,size=18,color=INK,center=False):
                original_text(value,x,y,size,color,center)
                label=app.art.labels[(value,size,color)]
                left=x-label.w/2 if center else x
                assert 0<=left and left+label.w<=960,(value,left,label.w)
                assert 0<=y-label.h/2 and y+label.h/2<=640,(value,y,label.h)
            app.art.text=text
            def draw(name=None):
                app.draw()
                if name:capture(OUTPUT/(name+'.png'))
                p.update_canvas()
            def click(x,y):
                app.click(x,y)
                draw()
            def finish():
                for _ in range(21):app.update(.05)
                draw()
                assert app.lobby.reveal.ready
            try:
                app.store.profile['gold']=10000
                app.store.save_profile()
                draw()
                click(480,205)
                click(775,317)
                draw('shop_ten_draw')
                click(580,417)
                draw('ten_confirmation')
                rng=Mock()
                rng.choices.side_effect=[[r] for r in ['common','rare','unique','common','legendary']*2]
                rng.choice.return_value='bell'
                with patch('game.storage.random.Random',return_value=rng):
                    click(602,226)
                reveal=app.lobby.reveal
                assert reveal and reveal.result['highest_rarity']=='legendary'
                assert (len(app.store.profile['items']),app.store.profile['gold'])==(10,8500)
                draw('opening_start')
                app.lobby.action(app,('gacha',10))
                app.lobby.close(app)
                click(20,20)
                app.action('start',0)
                assert app.scene=='LOBBY' and app.lobby.reveal is reveal
                assert len(app.store.profile['items'])==10
                for _ in range(8):app.update(.05)
                with patch.object(app.art,'sprite',wraps=app.art.sprite) as sprites:
                    draw('opening_golden')
                    chest=[c.args[0] for c in sprites.call_args_list if '/shop/chest_open_' in c.args[0]]
                    assert chest==['sprites/shop/chest_open_legendary.png']
                finish()
                with patch.object(app.art,'sprite',wraps=app.art.sprite) as sprites:
                    draw('ten_results')
                    assert sum(c.args[0]=='ui/new_badge.png' for c in sprites.call_args_list)==4
                for width,height in ((720,480),(1280,720)):
                    p.SDL_SetWindowSize(native.window,width,height)
                    draw(f'ten_results_{width}x{height}')
                p.SDL_SetWindowSize(native.window,960,640)
                for rarity in ('common','rare','unique','legendary'):
                    result={**reveal.result,'highest_rarity':rarity}
                    preview=GachaReveal(result)
                    app.lobby.reveal=preview
                    preview.update(.5)
                    draw('opening_'+rarity)
                app.lobby.reveal=reveal
                draw()
                click(480,125)
                assert app.lobby.reveal is None
                click(120,573)
                click(775,379)
                draw('inventory_new')
                key=app.store.profile['items'][0]['id']
                assert app.store.profile['items'][0]['is_new']
                click(200,392)
                assert not app.store.profile['items'][0]['is_new']
                assert not Store(folder).profile['items'][0]['is_new']
                draw('inventory_seen')
                click(766,509)
                click(775,317)
                click(580,417)
                write=app.store.write
                def fail(name,value):
                    if name=='profile.json':raise OSError('test: disk unavailable')
                    write(name,value)
                with patch.object(app.store,'write',side_effect=fail):
                    click(602,226)
                assert app.store.pending and app.lobby.reveal is None
                assert (len(app.store.profile['items']),app.store.profile['gold'])==(10,8500)
                draw('save_failed_no_reveal')
                click(602,226)
                assert app.lobby.reveal and not app.store.pending
                assert (len(app.store.profile['items']),app.store.profile['gold'])==(20,7000)
                finish()
                click(480,125)
                assert app.lobby.reveal is None
                click(340,417)
                click(602,226)
                assert app.lobby.reveal.result['count']==1
                finish()
                draw('single_result')
                click(480,125)
                assert app.store.profile['gold']==6850
                for name,spec in app.art.v6_specs.items():
                    image=app.art.image(name)
                    assert (image.w,image.h)==(spec['width'],spec['height'])
                print('GACHA SDL PASS: 1/10 pulls, one highest-rarity opening, four light colors, input blocking, NEW acknowledgement, failed-save retry, two viewports')
            finally:
                app.audio.close()
    finally:
        p.close_canvas()


if __name__=='__main__':
    main()

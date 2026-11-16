"""SDL coverage of 20 shared icons, 80 definitions and looping rarity backdrops."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App,p,native,capture,INK
from game.equipment import RULES,DEFINITIONS,bonuses
from game.visuals import EQUIPMENT_ART
from game.gacha import GachaReveal
OUTPUT=ROOT/'output/nyangi_art_v7/verification'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            app=App(folder)
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
            try:
                app.ui_clock=.25
                for rarity in RULES['rarities']:
                    p.clear_canvas()
                    app.panel(0,0,960,640)
                    app.art.text(rarity.title()+' - 20 equipment',480,602,25,INK,True)
                    for index,(kind,spec) in enumerate(RULES['types'].items()):
                        x,y=150+index%4*220,535-index//4*100
                        EQUIPMENT_ART.draw(app.art,{'definition':kind+'_'+rarity},x,y,app.ui_clock,size=48)
                        app.art.text(spec['name'],x,y-39,16,INK,True)
                    capture(OUTPUT/('catalog_'+rarity+'.png'))
                p.clear_canvas()
                app.panel(0,0,960,640)
                for row,rarity in enumerate(RULES['rarities']):
                    app.art.text(rarity,20,550-row*140,18)
                    for frame in range(6):
                        EQUIPMENT_ART.effects[rarity].draw(app.art,200+frame*130,550-row*140,(frame+.01)/8)
                capture(OUTPUT/'all_rarity_frames.png')
                profile=app.store.profile
                profile['gold']=100000
                profile['items']=[dict(id=key,definition=key,enhancement=0,stacks=0,locked=False,is_new=True) for key in DEFINITIONS]
                profile['unlocked_slots']=3
                profile['equipment_slots']=['roller_skates_legendary','moon_badge_rare','magic_book_unique']
                app.store.save_profile()
                app.enter_lobby()
                draw('equipped_lobby')
                app.lobby.open(app,'equipment')
                for page in range(16):
                    app.lobby.page=page
                    draw('inventory_page_'+str(page) if page in (0,10,15) else None)
                app.lobby.item_id='roller_skates_legendary'
                draw('long_name_detail')
                app.lobby.close(app)
                sample=[profile['items'][i] for i in (0,5,10,15,20,25,30,35,40,45)]
                result=dict(count=10,cost=1500,items=sample,highest_rarity='legendary')
                app.lobby.open(app,'shop')
                app.lobby.reveal=GachaReveal(result)
                app.lobby.reveal.update(1.1)
                with patch.object(app.art,'sprite',wraps=app.art.sprite) as sprites:
                    draw('ten_equipment_results')
                    calls=[c.args[0] for c in sprites.call_args_list]
                    assert sum('/equipment_fx/' in name for name in calls)==13  # Three equipped slots plus ten results.
                    for i,name in enumerate(calls):
                        if '/equipment/' in name:
                            assert i and '/equipment_fx/' in calls[i-1]
                for width,height in ((720,480),(1280,720)):
                    p.SDL_SetWindowSize(native.window,width,height)
                    draw(f'ten_results_{width}x{height}')
                p.SDL_SetWindowSize(native.window,960,640)
                app.lobby.close(app)
                app.lobby.close(app)
                app.start()
                assert app.world.bonuses==bonuses(profile)
                draw('equipment_stats_in_game')
                for name,spec in app.art.v7_specs.items():
                    image=app.art.image(name)
                    assert (image.w,image.h)==(spec['width'],spec['height'])
                print('EQUIPMENT SDL PASS: 20 icons x 4 grades, 24 aura frames, 80-item paging, effects behind icons, equipped slots/stats, result cards and two viewports')
            finally:
                app.audio.close()
    finally:
        p.close_canvas()


if __name__=='__main__':
    main()

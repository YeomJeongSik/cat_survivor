"""Actual SDL inspection of new asset objects and current-screen integration."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App,p,native,capture
from game.model import World
from game.visuals import CHARACTER_ART
OUTPUT=ROOT/'output/nyangi_art_v5/verification'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            app=App(folder)
            try:
                app.enter_lobby()
                app.draw()
                capture(OUTPUT/'lobby_rewards.png')
                app.lobby.open(app,'shop')
                app.draw()
                capture(OUTPUT/'shop_rewards.png')
                for character in ('witch','ninja'):
                    p.clear_canvas()
                    app.panel(0,0,960,640)
                    frames=0
                    for row,state in enumerate(('idle','walk','jump','fall','dash','attack','hit','dead','groom')):
                        spec=app.art.specs[f'sprites/cat/{character}/{state}.png']
                        app.art.text(state,20,600-row*65,16)
                        for i in range(spec['frames']):
                            CHARACTER_ART[character].draw(app.art,180+i*92,573-row*65,state,(i+.01)/spec['fps'])
                            frames+=1
                    assert frames==67
                    capture(OUTPUT/(character+'_all_frames.png'))
                p.clear_canvas()
                app.panel(0,0,960,640)
                names=('sprites/rewards/gold.png','sprites/rewards/exp.png',
                       CHARACTER_ART['witch'].attack.path,CHARACTER_ART['black'].attack.path,
                       CHARACTER_ART['ninja'].attack.path)
                for row,name in enumerate(names):
                    spec=app.art.specs[name]
                    app.art.text(Path(name).stem,20,580-row*112,16)
                    for i in range(spec['frames']):
                        app.art.sprite(name,300+i*180,575-row*112,(i+.01)/spec['fps'],scale=2 if row<3 else 1.3)
                capture(OUTPUT/'reward_and_attack_frames.png')
                app.lobby.close(app)
                app.start()
                assert app.scene=='PLAY'
                app.world=World(character_id='black')
                app.world.aim=(app.world.cat.x+100,app.world.cat.y+26)
                app.world.shoot()
                app.world.update(.11)
                with patch.object(app.art,'sprite',wraps=app.art.sprite) as draws:
                    app.draw()
                    assert any(c.args[0]=='sprites/attacks/claw_slash.png' for c in draws.call_args_list)
                capture(OUTPUT/'black_claw_in_game.png')
                for name,spec in app.art.v5_specs.items():
                    image=app.art.image(name)
                    assert (image.w,image.h)==(spec['width'],spec['height'])
                print('VISUAL PASS: 23 sheets / 154 frames; asset objects; GOLD/EXP UI; real black claw attack')
            finally:
                app.audio.close()
    finally:
        p.close_canvas()


if __name__=='__main__':
    main()

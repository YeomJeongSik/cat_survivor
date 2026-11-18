"""Actual SDL verification of the new title, shop chest and every black-cat frame."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.app import App,p,native,capture

OUTPUT = ROOT/'output/nyangi_art_v4/verification'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    p.open_canvas(960,640,sync=False)
    p.hide_lattice()
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as folder:
            app = App(folder)
            try:
                with patch.object(app,'cat',side_effect=AssertionError('Title must not draw a separate cat')):
                    with patch.object(app.art,'draw',wraps=app.art.draw) as draws:
                        app.draw()
                        names = [call.args[0] for call in draws.call_args_list]
                        assert 'backgrounds/campus_title_duel.png' in names
                capture(OUTPUT/'intro_960x640.png')
                app.click(480,155)
                assert app.controls_popup
                app.draw()
                capture(OUTPUT/'intro_controls.png')
                app.click(480,155)
                p.SDL_SetWindowSize(native.window,720,480)
                for _ in range(4):
                    app.draw()
                    p.update_canvas()
                capture(OUTPUT/'intro_720x480.png')
                p.SDL_SetWindowSize(native.window,960,640)
                app.enter_lobby()
                app.lobby.open(app,'shop')
                with patch.object(app.art,'draw',wraps=app.art.draw) as draws:
                    app.draw()
                    names = [call.args[0] for call in draws.call_args_list]
                    assert 'ui/equipment_chest.png' in names
                    assert 'backgrounds/campus_title.png' in names
                    assert 'backgrounds/campus_title_duel.png' not in names
                assert any(rect==(508,193,793,235) and action==('lobby','gacha') for rect,action,_ in app.buttons)
                capture(OUTPUT/'shop_chest.png')
                p.clear_canvas()
                app.panel(0,0,960,640)
                frames = 0
                for row,(name,spec) in enumerate((n,s) for n,s in app.art.v4_specs.items() if n.startswith('sprites/cat/')):
                    app.art.text(Path(name).stem,20,600-row*65,16)
                    for frame in range(spec['frames']):
                        app.art.sprite(name,180+frame*92,592-row*65,(frame+.01)/spec['fps'])
                        frames += 1
                assert frames==67
                capture(OUTPUT/'black_all_67_frames.png')
                print('ART PASS: intro has no extra cat; battle background title-only; shop chest; 67 black-cat frames; 720x480')
            finally:
                app.audio.close()
    finally:
        p.close_canvas()


if __name__=='__main__':
    main()

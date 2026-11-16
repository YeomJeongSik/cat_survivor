"""Own the canvas, frame loop, scene transitions, and frame capture."""
import ctypes
import time
from pathlib import Path

import pico2d as p
import pico2d.pico2d as native

from .states import Machine


def scene_machine(app):
    return Machine(model=app,model_attribute='scene',initial='TITLE',
                   states=['TITLE','PLAY','RESULT'],auto_transitions=False,
                   transitions=[['show_play',['TITLE','RESULT','PLAY'],'PLAY'],
                                ['show_result','PLAY','RESULT'],
                                ['show_title',['TITLE','PLAY','RESULT'],'TITLE']])


def capture(path):
    width,height = ctypes.c_int(),ctypes.c_int()
    if p.SDL_GetRendererOutputSize(native.renderer,ctypes.byref(width),ctypes.byref(height)) != 0:
        raise RuntimeError('Could not query renderer size')
    surface = p.SDL_CreateRGBSurfaceWithFormat(0,width.value,height.value,32,p.SDL_PIXELFORMAT_RGBA32)
    if not surface:
        raise RuntimeError('Screenshot surface allocation failed')
    try:
        status = p.SDL_RenderReadPixels(native.renderer,None,p.SDL_PIXELFORMAT_RGBA32,surface.contents.pixels,surface.contents.pitch)
        if status != 0:
            raise RuntimeError('Could not capture renderer')
        path = Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        if p.IMG_SavePNG(surface,str(path.resolve()).encode('utf-8')) != 0:
            raise OSError('Could not save screenshot')
    finally:
        p.SDL_FreeSurface(surface)


def run(create_app, title, *, smoke=0, screenshot=None):
    p.SDL_SetHint(p.SDL_HINT_RENDER_SCALE_QUALITY,b'0')
    p.open_canvas(960,640,sync=True)
    p.hide_lattice()
    p.SDL_SetWindowTitle(native.window,title.encode('utf-8'))
    p.SDL_SetWindowResizable(native.window,p.SDL_TRUE)
    p.SDL_SetWindowMinimumSize(native.window,720,480)
    p.SDL_RenderSetLogicalSize(native.renderer,960,640)
    app = None
    try:
        app = create_app()
        if smoke:
            app.start()
        frames, previous = 0,time.perf_counter()
        while app.running:
            now = time.perf_counter()
            dt, previous = min(now-previous,.25),now
            app.events()
            app.update(dt)
            app.draw()
            frames += 1
            if screenshot and smoke and frames == smoke:
                capture(screenshot)
            p.update_canvas()
            if smoke and frames >= smoke:
                print(f'SMOKE PASS frames={frames} survival={app.world.time:.2f}s textures={len(app.art.images)}')
                break
    finally:
        if app is not None:
            app.close()
        p.close_canvas()

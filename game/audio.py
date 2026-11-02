"""Cached SDL_mixer playback; independent live BGM/SFX volume controls."""
from pathlib import Path
import pico2d as p
import pico2d.pico2d as native

ROOT=Path(__file__).resolve().parents[1]/'assets/audio'
TRACKS={'TITLE':'campus_stroll','RANKING':'campus_stroll','PLAY':'jelly_rush','RESULT':'sunset_record'}
CHANNELS={'shot':0,'dash':1,'jump':2,'land':2,'enemy_death':3,'magpie_attack':4,'bee_attack':11,
          'squirrel_attack':12,'snake_attack':13,'siren':5,'click':6,'countdown':6,
          'hurt':7,'cat_death':7,'pickup':8,'heal':8,'unlock':9,'clear':9,'empty':10,'no_target':10}


class Audio:
    def __init__(self,profile):
        self.available=native.audio_on
        self.music,self.sounds={},{}
        self.current=None
        if not self.available:
            return
        p.Mix_AllocateChannels(16)
        for name in set(TRACKS.values()):
            self.music[name]=p.load_music(str(ROOT/'bgm'/f'{name}.wav'))
        for name in CHANNELS:
            folder=ROOT/'sfx'
            self.sounds[name]=p.load_wav(str(folder/f'{name}.wav'))
        self.volumes(profile)

    def volumes(self,profile):
        if self.available:
            p.Mix_VolumeMusic(round(profile['bgm_volume']/100*128))
            p.Mix_Volume(-1,round(profile['sfx_volume']/100*128))

    def scene(self,scene):
        name=TRACKS[scene]
        if self.available and name!=self.current:
            self.music[name].repeat_play()
            self.current=name

    def play(self,name):
        if name in ('footstep','enemy_hit'):
            name='land'
        if self.available and name in self.sounds:
            p.Mix_PlayChannel(CHANNELS[name],self.sounds[name].wav,0)

    def close(self):
        if self.available:
            p.Mix_HaltMusic()
            p.Mix_HaltChannel(-1)
            self.music.clear()
            self.sounds.clear()

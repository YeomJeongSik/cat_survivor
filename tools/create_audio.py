"""Compose original local chiptune loops and cartoon SFX using only the standard library."""
from array import array
import json
import math
from pathlib import Path
import random
import wave

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'assets/audio'
RATE=22050
TAU=math.tau


def tone(track,start,duration,freq,gain=.1,kind='triangle',end=None):
    first=int(start*RATE)
    count=min(int(duration*RATE),len(track)-first)
    phase=0.
    for i in range(max(0,count)):
        t=i/RATE
        f=freq if end is None else freq+(end-freq)*i/max(1,count)
        phase += TAU*f/RATE
        sine=math.sin(phase)
        sample=(2/math.pi*math.asin(sine) if kind=='triangle' else
                .75*sine+.25*math.sin(2*phase) if kind=='bell' else
                (.65 if sine>=0 else -.65) if kind=='square' else sine)
        envelope=min(1,t/.008)*max(0,1-i/max(1,count))**.6
        track[first+i] += gain*envelope*sample


def noise(track,start,duration,gain,seed,decay=8):
    rng=random.Random(seed)
    first=int(start*RATE)
    for i in range(min(int(duration*RATE),len(track)-first)):
        t=i/RATE
        track[first+i] += gain*rng.uniform(-1,1)*math.exp(-decay*t/max(.01,duration))*min(1,t/.003)


def write(name,track):
    peak=max(abs(s) for s in track) or 1
    scale=min(1.,.82/peak)
    pcm=array('h',(round(max(-1,min(1,s*scale))*32767) for s in track))
    path=OUT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as stream:
        stream.setparams((1,2,RATE,0,'NONE','not compressed'))
        stream.writeframes(pcm.tobytes())
    return dict(file=name,seconds=round(len(track)/RATE,3),sample_rate=RATE,peak=round(peak*scale,4))


def midi(note):
    return 440*2**((note-69)/12)


def music(name,tempo,bars,energy):
    beat=60/tempo
    track=array('f',[0])*round(bars*4*beat*RATE)
    chords=((48,52,55),(45,48,52),(41,45,48),(43,47,50))
    melody=(0,2,4,2,1,3,5,4,2,1,0,2,4,3,1,2)
    scale=(72,74,76,77,79,81,83,84)
    for bar in range(bars):
        chord=chords[bar%4]
        for tick in range(8):
            time=(bar*4+tick*.5)*beat
            tone(track,time,beat*.43,midi(chord[tick%3]+12),.045,'bell')
        for step in range(8 if energy else 4):
            time=(bar*4+step*(.5 if energy else 1))*beat
            note=scale[(melody[(bar*3+step)%len(melody)]+(2 if bar%4==3 else 0))%8]
            tone(track,time,beat*(.4 if energy else .8),midi(note),.11 if energy else .08,'triangle' if energy else 'bell')
        for tick in range(4):
            time=(bar*4+tick)*beat
            tone(track,time,beat*.8,midi(chord[0]+(12 if tick%2 else 0)),.12,'triangle')
            if energy:
                if tick%2==0:
                    tone(track,time,.12,105,.20,'sine',40)
                else:
                    noise(track,time,.10,.11,bar*19+tick)
                noise(track,time+beat*.5,.035,.045,bar*23+tick,4)
    return write('bgm/'+name+'.wav',track)


def effect(name,duration,notes=(),noisy=0):
    track=array('f',[0])*int(duration*RATE)
    for start,length,freq,gain,kind,end in notes:
        tone(track,start,length,freq,gain,kind,end)
    if noisy:
        noise(track,0,duration,noisy,17,4)
    return write('sfx/'+name+'.wav',track)


def main():
    files=[music('campus_stroll',118,8,False),music('jelly_rush',128,16,True),music('sunset_record',110,8,False)]
    specifications={
        'jump':(.17,[(0,.17,420,.22,'triangle',850)],0),
        'dash':(.18,[(0,.18,1100,.16,'sine',190)],.23),
        'empty':(.09,[(0,.09,180,.14,'square',100)],0),
        'no_target':(.08,[(0,.08,380,.08,'sine',300)],0),
        'enemy_death':(.25,[(0,.12,660,.20,'square',330),(.09,.15,330,.16,'triangle',90)],.05),
        'hurt':(.20,[(0,.20,290,.20,'square',110)],.05),
        'cat_death':(.75,[(0,.25,523,.17,'triangle',392),(.22,.25,330,.17,'triangle',220),(.45,.3,196,.17,'triangle',98)],0),
        'magpie_attack':(.24,[(0,.24,1550,.12,'sine',420)],.17),
        'bee_attack':(.20,[(0,.20,190,.16,'square',430)],.04),
        'squirrel_attack':(.20,[(0,.20,340,.16,'triangle',720)],.04),
        'snake_attack':(.28,[(0,.28,160,.14,'sine',60)],.24),
        'pickup':(.21,[(0,.10,880,.15,'bell',None),(.08,.13,1320,.15,'bell',None)],0),
        'heal':(.45,[(0,.25,523,.13,'bell',None),(.12,.25,659,.13,'bell',None),(.24,.21,784,.13,'bell',None)],0),
        'unlock':(.6,[(0,.25,659,.13,'bell',None),(.13,.3,784,.13,'bell',None),(.28,.32,1047,.13,'bell',None)],0),
        'click':(.065,[(0,.065,900,.1,'triangle',1200)],0),
        'land':(.07,[(0,.07,150,.13,'sine',70)],.015),
        'countdown':(.09,[(0,.09,880,.12,'bell',None)],0),
        'clear':(.9,[(i*.13,.3,midi(n),.14,'bell',None) for i,n in enumerate((72,76,79,84,79))],0),
    }
    for name,(duration,notes,noisy) in specifications.items():
        files.append(effect(name,duration,notes,noisy))
    track=array('f',[0])*int(.28*RATE)
    phase=0.
    for i in range(len(track)):
        t=i/RATE
        u=t/.28
        frequency=760-350*u+150*math.sin(math.pi*u)+20*math.sin(TAU*8*t)
        phase += TAU*frequency/RATE
        track[i]=.18*math.sin(math.pi*u)**.7*(math.sin(phase)+.45*math.sin(2*phase)+.22*math.sin(3*phase))
    files.append(write('sfx/shot.wav',track))
    track=array('f',[0])*int(.24*RATE)
    phase=0.
    for i in range(len(track)):
        u=i/len(track)
        phase += TAU*(560+520*math.sin(math.pi*u))/RATE
        track[i]=.15*math.sin(math.pi*u)*math.sin(phase)
    files.append(write('sfx/siren.wav',track))
    assert len(files)==23
    assert all(0<f['peak']<=.82 for f in files)
    (OUT/'manifest.json').write_text(json.dumps(dict(author='Original local procedural composition',license='Project original audio; no third-party samples',bgm_style='Bright campus chiptune; C-Am-F-G; original melodies',files=files),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'AUDIO EXPORT PASS: {len(files)} original WAV files; max peak <= 0.82; no API/model/download')


if __name__=='__main__':
    main()

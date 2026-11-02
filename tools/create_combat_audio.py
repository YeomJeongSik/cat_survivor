"""Export v2 combat SFX locally; preserve the original audio and music."""
from array import array
import json
import math
import random
import create_audio as synth

OUT=synth.ROOT/'assets/audio/v2'


def vocal(duration,hurt=False):
    track=array('f',[0])*int(duration*synth.RATE)
    phase=0.
    for i in range(len(track)):
        t=i/synth.RATE
        u=i/len(track)
        frequency=(620-330*u+110*math.sin(math.pi*u) if hurt else
                   460-180*u+150*math.sin(math.pi*u))
        frequency+=18*math.sin(math.tau*(24 if hurt else 9)*t)
        phase+=math.tau*frequency/synth.RATE
        # Moving vowel resonances give the harmonic voice a short meow shape.
        formants=(1100-350*u,2600-1000*u)
        voice=0.
        for harmonic in range(1,10):
            freq=frequency*harmonic
            resonance=sum(math.exp(-((freq-f)/450)**2) for f in formants)
            voice+=math.sin(phase*harmonic)*(0.25+resonance)/harmonic
        rough=1+.2*math.sin(math.tau*43*t) if hurt else 1.
        track[i]=.26*math.sin(math.pi*u)**.7*voice*rough
    return track


def main():
    synth.OUT=OUT
    tracks={}
    tracks['shot']=(vocal(.28),'Short bright synthetic meow on projectile launch')
    tracks['hurt']=(vocal(.36,True),'Higher rough startled synthetic cat yelp on damage')

    jump=array('f',[0])*int(.20*synth.RATE)
    synth.tone(jump,0,.18,340,.22,'triangle',990)
    synth.tone(jump,.025,.175,680,.08,'bell',1540)
    tracks['jump']=(jump,'Soft rising cartoon spring for both jumps')

    hit=array('f',[0])*int(.13*synth.RATE)
    synth.noise(hit,0,.09,.32,71,6)
    synth.tone(hit,0,.11,520,.24,'triangle',105)
    synth.tone(hit,.012,.065,1460,.09,'bell',420)
    tracks['enemy_hit']=(hit,'Crisp paw impact on every projectile hit, including lethal hits')

    bird=array('f',[0])*int(.32*synth.RATE)
    for start in (0,.12):
        synth.tone(bird,start,.13,760,.20,'square',450)
        synth.tone(bird,start,.13,1520,.08,'sine',900)
        synth.noise(bird,start,.13,.11,32+int(start*100),3)
    synth.noise(bird,.20,.12,.13,61,2)
    tracks['magpie_attack']=(bird,'Two coarse bird calls with a wing rush at attack start')

    squirrel=array('f',[0])*int(.27*synth.RATE)
    for i in range(3):
        synth.tone(squirrel,i*.065,.075,1500+i*130,.19,'triangle',1000+i*80)
    synth.noise(squirrel,.12,.15,.09,18,3)
    tracks['squirrel_attack']=(squirrel,'Three quick squirrel chirps and a light launch rustle')

    bee=array('f',[0])*int(.30*synth.RATE)
    phase=0.
    for i in range(len(bee)):
        t=i/synth.RATE
        u=i/len(bee)
        phase+=math.tau*(180+210*u)/synth.RATE
        buzz=sum(math.sin(phase*h)/h for h in (1,2,3,5))
        bee[i]=.19*math.sin(math.pi*u)**.5*(.75+.25*math.sin(math.tau*48*t))*buzz
    tracks['bee_attack']=(bee,'Accelerating raspy wing buzz on the bee dash')

    snake=array('f',[0])*int(.34*synth.RATE)
    rng=random.Random(41)
    previous=0.
    for i in range(len(snake)):
        u=i/len(snake)
        current=rng.uniform(-1,1)
        snake[i]=.17*math.sin(math.pi*u)**.7*(current-previous)
        previous=current
    synth.tone(snake,0,.18,150,.19,'sine',55)
    synth.noise(snake,0,.13,.16,42,5)
    tracks['snake_attack']=(snake,'Airy snake hiss with a low dirt pop on emergence')

    files=[]
    for name,(track,description) in tracks.items():
        for i in range(len(track)):
            track[i]*=min(1.,i/(.004*synth.RATE),(len(track)-1-i)/(.008*synth.RATE))
        entry=synth.write(f'sfx/{name}.wav',track)
        entry['description']=description
        files.append(entry)
    assert len(files)==8 and all(0<f['peak']<=.82 for f in files)
    (OUT/'manifest.json').write_text(json.dumps({
        'author':'Project original local procedural SFX',
        'license':'Original synthesis; no recordings, third-party samples, API or cloud',
        'files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT AUDIO V2 PASS: 8 distinct WAVs; original audio preserved; no download/API')


if __name__=='__main__':
    main()

"""Repeatable model-only measurements; bot rates are not human-play balance."""
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from game.difficulty import SETTINGS, difficulty_at, monster_stats
from game.model import World


def sample(start, seconds=60, character_id='nabi'):
    world=World(17,character_id=character_id)
    world.time=start
    world.next_spawn_at=start+.25
    world.next_bandage_at=start+SETTINGS['bandage_interval']
    world.cat.invincible=99999
    seen={}
    rewarded=set()
    exp=gold=kills=peak=0
    costs=[]
    for _ in range(seconds*60):
        targets=[enemy for enemy in world.enemies if enemy.targetable]
        keys=set()
        if targets:
            target=min(targets,key=lambda e:math.hypot(e.x-world.cat.x,e.y-world.cat.y-26))
            world.aim=(target.x,target.y)
            world.cat.ammo=4  # Measurement bot only: ignores pickup and survival limits.
            world.shoot()
            if character_id=='black':
                if abs(target.x-world.cat.x)>40:
                    keys.add('right' if target.x>world.cat.x else 'left')
                if target.y>world.cat.y+80 and (world.cat.grounded or world.cat.jumps_used==1 and world.cat.vy<0):
                    world.jump()
        seen.update((id(enemy),enemy) for enemy in world.enemies)
        before=time.perf_counter()
        world.update(1/60,keys)
        costs.append((time.perf_counter()-before)*1000)
        for identity,enemy in seen.items():
            if not enemy.alive and identity not in rewarded:
                rewarded.add(identity)
                kills+=1
                exp+=enemy.exp_reward
                gold+=enemy.gold_reward
        peak=max(peak,sum(e.alive for e in world.enemies))
        world.events.clear()
    return dict(character_id=character_id,start_seconds=start,duration_seconds=seconds,kills=kills,
                hypothetical_exp_per_minute=exp*60/seconds,hypothetical_gold_per_minute=gold*60/seconds,
                peak_alive=peak,spawn_attempts=world.spawn_stats,
                model_frame_ms_mean=round(statistics.mean(costs),3),
                model_frame_ms_p95=round(sorted(costs)[int(len(costs)*.95)],3))


def main():
    stats={}
    for seconds in (0,120,420,600):
        rules=difficulty_at(seconds)
        stats[seconds]={kind:dict(**monster_stats(kind,rules),
                                 nabi_hits=math.ceil(monster_stats(kind,rules)['max_hp']),
                                 black_hits=math.ceil(monster_stats(kind,rules)['max_hp']/2))
                        for kind in SETTINGS['monsters']}
    result=dict(
        conditions='Model-only, seed 17, invincible bots, no rendering. Nabi is stationary with unlimited ammo; Black approaches targets and auto-jumps. Rewards shown are raw bot kill totals before survival bonuses. Human dodge difficulty and fair human character balance are not measured.',
        stats=stats,samples=[sample(start,character_id=character) for character in ('nabi','black') for start in (0,120,420,600)])
    path=ROOT/'output/preview2_complete/measurements.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result['samples'],indent=2))
    print(path)


if __name__=='__main__':
    main()

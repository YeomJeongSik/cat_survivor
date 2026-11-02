"""Versioned local saves. Damaged input is preserved for recovery."""
from pathlib import Path
import json
import math
import os
import time
from .model import SKINS


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.warnings = []
        self.profile = self.read('profile.json', {})
        owned = self.profile.get('unlocked_skin_ids', [])
        self.profile['unlocked_skin_ids'] = [s for s in SKINS if isinstance(owned,list) and s in owned or s == SKINS[0]]
        if self.profile.get('equipped_skin_id') not in self.profile['unlocked_skin_ids']:
            self.profile['equipped_skin_id'] = SKINS[0]
        for key in ('bgm_volume','sfx_volume'):
            value = self.profile.get(key,70)
            self.profile[key] = max(0,min(100,round(value/10)*10)) if isinstance(value,(float,int)) and math.isfinite(value) else 70
        raw = self.read('leaderboard.json', [])
        self.records = [r for r in raw if isinstance(r,dict) and isinstance(r.get('score'),int) and
                        isinstance(r.get('timestamp'),(int,float)) and math.isfinite(r['timestamp']) and isinstance(r.get('cleared'),bool)]

    def read(self, name, default):
        path = self.folder/name
        if not path.exists():
            return default
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if type(value) is not type(default):
                raise ValueError('Wrong save root type')
            return value
        except (OSError,ValueError):
            # Preserve corrupt data before a later explicit save replaces it.
            backup = path.with_name(path.name+f'.damaged-{time.time_ns()}')
            try:
                backup.write_bytes(path.read_bytes())
            except OSError as exc:
                raise OSError(f'Cannot preserve damaged save: {path}') from exc
            self.warnings.append(f'{name}: damaged file preserved as {backup.name}')
            return default

    def write(self, name, value):
        self.folder.mkdir(parents=True,exist_ok=True)
        path = self.folder/name
        temporary = path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)

    def save_profile(self):
        self.profile['version'] = 1
        self.write('profile.json',self.profile)

    def unlock(self, skins):
        owned = set(self.profile['unlocked_skin_ids']) | set(skins)
        if owned != set(self.profile['unlocked_skin_ids']):
            self.profile['unlocked_skin_ids'] = [s for s in SKINS if s in owned]
            self.save_profile()

    def record(self, world):
        result = dict(player_name='LOCAL',score=world.score,wave_reached=world.wave,
                      time_survived=round(world.time,2),cleared=world.mode=='CLEAR',timestamp=time.time())
        self.records.append(result)
        self.records.sort(key=lambda r:(not r['cleared'],-r['score'],r['timestamp']))
        self.records = self.records[:100]
        self.write('leaderboard.json',self.records)
        return result is self.records[0]

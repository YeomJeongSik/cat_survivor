"""Versioned local saves. Damaged input is preserved for recovery."""
from pathlib import Path
import json
import math
import os
import time
import copy
import hashlib
import random
from uuid import uuid4
from .transactions import apply_operation
from .characters import CHARACTERS
from .rewards import initial_character, validate_progress, settle_run


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.warnings = []
        self.profile = self.read('profile.json', {})
        version=self.profile.get('version',1)
        if type(version) is not int or version not in (1,2):
            raise ValueError('Unsupported profile version; original save was not changed')
        self.original_version=version
        if version==1:
            self.profile.update(version=2,gold=0,characters={'nabi':initial_character()},settled_runs={})
        self.profile.setdefault('transactions',{})
        self.profile.setdefault('claimed_achievements',{})
        self.profile.setdefault('stats',dict(kills=0,magpie=0,squirrel=0,bee=0,snake=0,
            runs=len(self.profile.get('settled_runs',{})),best_time=max((r['survival_time'] for r in self.profile.get('settled_runs',{}).values()),default=0)))

        self.pending=self.read('pending_transaction.json',{})
        if self.pending and not all(key in self.pending for key in ('id','operation','args','seed','base')):
            raise ValueError('Invalid pending transaction; original file preserved')
        validate_progress(self.profile)
        selected=self.profile.get('selected_character_id','nabi')
        self.profile['selected_character_id']=selected if isinstance(selected,str) and selected in self.profile['characters'] and selected in CHARACTERS else 'nabi'
        for key in ('bgm_volume','sfx_volume'):
            value = self.profile.get(key,70)
            self.profile[key] = max(0,min(100,round(value/10)*10)) if isinstance(value,(float,int)) and math.isfinite(value) else 70

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

    def _write_profile(self, candidate):
        validate_progress(candidate)
        if not isinstance(candidate.get('selected_character_id'),str) or candidate['selected_character_id'] not in CHARACTERS or candidate['selected_character_id'] not in candidate['characters']:
            raise ValueError('Cannot save an unowned or unavailable character')
        path=self.folder/'profile.json'
        if self.original_version==1 and path.exists():
            backup=self.folder/'profile.v1-backup.json'
            if not backup.exists():
                backup.write_bytes(path.read_bytes())
        self.write('profile.json',candidate)
        self.original_version=2

    def save_profile(self):
        self._require_no_pending()
        self._write_profile(self.profile)

    def select_character(self, character_id):
        self._require_no_pending()
        if not isinstance(character_id,str) or character_id not in self.profile['characters'] or character_id not in CHARACTERS:
            raise ValueError('Character is not owned or playable')
        if character_id==self.profile['selected_character_id']:
            return
        candidate=copy.deepcopy(self.profile)
        candidate['selected_character_id']=character_id
        self._write_profile(candidate)
        self.profile=candidate

    def settle(self, world):
        self._require_no_pending()
        if world.mode!='GAME_OVER' or world.end_reason!='death':
            raise ValueError('Abandoned or unfinished runs cannot settle')
        existing=self.profile['settled_runs'].get(world.run_id)
        if existing is not None:
            fields={'character_id':world.character_id,'raw_exp':world.run_exp,'raw_gold':world.run_gold,'survival_time':world.time}
            if any(existing[key]!=value for key,value in fields.items()):
                raise ValueError('Run ID already belongs to another result')
            return copy.deepcopy(existing)
        result=settle_run(self.profile,world)
        candidate=copy.deepcopy(self.profile)
        candidate['gold']+=result['gold_gained']
        candidate['characters'][world.character_id]=copy.deepcopy(result['character_after'])
        candidate['settled_runs'][world.run_id]=copy.deepcopy(result)
        candidate['stats']['runs']+=1
        candidate['stats']['best_time']=max(candidate['stats']['best_time'],world.time)
        for species,count in world.run_kills.items():
            candidate['stats'][species]+=count
            candidate['stats']['kills']+=count

        self._write_profile(candidate)
        self.profile=candidate
        return result

    def _require_no_pending(self):
        if self.pending:
            raise ValueError('미완료 거래를 먼저 재시도하세요.')

    def transact(self, operation, args, request_id=None):
        request_id=request_id or str(uuid4())
        existing=self.profile['transactions'].get(request_id)
        if existing:
            if existing['operation']!=operation or existing['args']!=args:
                raise ValueError('Transaction ID conflict')
            if self.pending and self.pending['id']==request_id:
                self.write('pending_transaction.json',{})
                self.pending={}
            return copy.deepcopy(existing['result'])
        fingerprint=hashlib.sha256(json.dumps(self.profile,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
        if self.pending:
            if (self.pending['id'],self.pending['operation'],self.pending['args'])!=(request_id,operation,args):
                raise ValueError('미완료 거래를 먼저 재시도하세요.')
            if self.pending['base']!=fingerprint:
                raise ValueError('저장 데이터가 변경되어 거래를 복구할 수 없습니다.')
            journal=self.pending
        else:
            journal=dict(id=request_id,operation=operation,args=copy.deepcopy(args),
                         seed=random.SystemRandom().getrandbits(64),base=fingerprint)
        candidate=copy.deepcopy(self.profile)
        result=apply_operation(candidate,operation,args,random.Random(journal['seed']),request_id)
        candidate['transactions'][request_id]=dict(operation=operation,args=copy.deepcopy(args),result=copy.deepcopy(result))
        self.pending=journal
        self.write('pending_transaction.json',journal)
        self._write_profile(candidate)
        self.profile=candidate
        self.write('pending_transaction.json',{})
        self.pending={}
        return result

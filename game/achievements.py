"""Lobby-only achievements; progress is updated by successfully settled runs."""
ACHIEVEMENTS=(
    dict(id='first_hunt',name='첫 사냥',description='적 1마리 처치',metric='kills',target=1,gold=30,exp=0),
    dict(id='hunter',name='캠퍼스 사냥꾼',description='적 100마리 처치',metric='kills',target=100,gold=100,exp=0),
    dict(id='bee_hunter',name='벌 퇴치',description='벌 30마리 처치',metric='bee',target=30,gold=0,exp=120),
    dict(id='crow_hunter',name='하늘의 수호자',description='까마귀 50마리 처치',metric='magpie',target=50,gold=100,exp=0),
    dict(id='snake_hunter',name='풀숲 탐험가',description='뱀 30마리 처치',metric='snake',target=30,gold=100,exp=0),
    dict(id='squirrel_hunter',name='발판 지킴이',description='다람쥐 50마리 처치',metric='squirrel',target=50,gold=0,exp=150),
    dict(id='survivor',name='긴 산책',description='한 판에서 180초 생존',metric='best_time',target=180,gold=0,exp=150),
    dict(id='veteran',name='캠퍼스의 전설',description='한 판에서 600초 생존',metric='best_time',target=600,gold=150,exp=0),
)


def progress(profile,achievement):
    return min(achievement['target'],profile['stats'][achievement['metric']])

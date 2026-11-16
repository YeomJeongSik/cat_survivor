"""One presentation object per committed equipment draw transaction."""
import pico2d as p
from .equipment import RULES, definition
from .visuals import CHEST_OPENING, NEW_BADGE

INK=(48,45,52)
RARITY_COLORS={'common':(218,218,218),'rare':(104,195,113),'unique':(187,133,224),'legendary':(234,184,67)}


class GachaReveal:
    BOUNDS=(100,90,860,550)
    DURATION=1.

    def __init__(self,result):
        self.result=result
        self.clock=0.

    @property
    def ready(self):
        return self.clock>=self.DURATION

    def update(self,dt):
        self.clock=min(self.DURATION,self.clock+dt)

    def draw(self,app):
        art=app.art
        rarity=self.result['highest_rarity']
        app.panel(*self.BOUNDS)
        app.buttons=[]
        count=self.result['count']
        art.text('10연뽑 결과' if count==10 else '장비 뽑기 결과',480,518,25,INK,True)
        art.text('최고 등급 · '+RULES['rarities'][rarity]['name'],480,486,18,INK,True)
        CHEST_OPENING[rarity].draw(art,480,425 if self.ready else 330,self.clock,scale=.65 if self.ready else 1.25)
        if not self.ready:
            art.text('상자를 여는 중...',480,155,18,INK,True)
            return
        for i,item in enumerate(self.result['items']):
            x=196+(i%5)*142 if count==10 else 480
            y=260-(i//5)*84
            spec=definition(item)
            p.draw_rectangle(x-64,y,x+64,y+74,*RARITY_COLORS[spec['rarity']],filled=True)
            p.draw_rectangle(x-62,y+2,x+62,y+72,255,247,224,filled=True)
            art.text(RULES['types'][spec['type']]['name'],x,y+44,15,INK,True)
            art.text(RULES['rarities'][spec['rarity']]['name'],x,y+20,13,INK,True)
            if item.get('is_new',False):
                NEW_BADGE.draw(art,x+43,y+62,scale=.83)
        art.text(f'{count}개 획득 · {self.result["cost"]:,} GOLD 사용',480,160,16,INK,True)
        app.button('확인',(335,105,625,147),('lobby','reveal_close'))

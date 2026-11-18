"""One presentation object per committed equipment draw transaction."""
from .equipment import RULES, definition
from .visuals import CHEST_OPENING, NEW_BADGE, EQUIPMENT_ART
from .ui import ACCENT, INK, SECONDARY

RARITY_COLORS={'common':SECONDARY,'rare':(152,202,132),'unique':(211,164,222),'legendary':ACCENT}


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
        app.modal(*self.BOUNDS)
        app.buttons=[]
        count=self.result['count']
        art.text('10연뽑 결과' if count==10 else '장비 뽑기 결과',480,518,25,ACCENT,True)
        art.text('최고 등급 · '+RULES['rarities'][rarity]['name'],480,486,16,SECONDARY,True)
        CHEST_OPENING[rarity].draw(art,480,420 if self.ready else 330,self.clock,scale=.54 if self.ready else 1.)
        if not self.ready:
            art.text('상자를 여는 중...',480,155,18,INK,True)
            return
        for i,item in enumerate(self.result['items']):
            x=196+(i%5)*142 if count==10 else 480
            y=260-(i//5)*84
            spec=definition(item)
            EQUIPMENT_ART.draw(art,item,x,y+49,app.ui_clock,size=32)
            art.text(RULES['types'][spec['type']]['name'],x,y+24,12,INK,True)
            art.text(RULES['rarities'][spec['rarity']]['name'],x,y+9,11,RARITY_COLORS[spec['rarity']],True)
            if item.get('is_new',False):
                NEW_BADGE.draw(art,x+43,y+62,scale=.83)
        art.text(f'{count}개 획득 · {self.result["cost"]:,} GOLD 사용',480,160,16,INK,True)
        app.button('확인',(335,105,625,147),('lobby','reveal_close'),primary=True)

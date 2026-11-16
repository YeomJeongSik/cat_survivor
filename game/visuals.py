"""Asset objects only; playable character rules remain in characters.py."""
from dataclasses import dataclass
from .equipment import RULES, definition


@dataclass(frozen=True)
class SpriteAsset:
    path: str

    def draw(self, art, x, y, clock=0., **options):
        art.sprite(self.path,x,y,clock,**options)


@dataclass(frozen=True)
class CharacterArt:
    skin: str
    attack: SpriteAsset

    def draw(self, art, x, y, state='idle', clock=0., skin=None, **options):
        art.sprite(f'sprites/cat/{skin or self.skin}/{state}.png',x,y,clock,foot=True,**options)


CHARACTER_ART = {
    'nabi': CharacterArt('tobi_default',SpriteAsset('sprites/projectiles/paw_000.png')),
    'black': CharacterArt('black',SpriteAsset('sprites/attacks/claw_slash.png')),
    # Art registration does not grant ownership or introduce unfinished combat rules.
    'witch': CharacterArt('witch',SpriteAsset('sprites/attacks/prophecy_orb.png')),
    'ninja': CharacterArt('ninja',SpriteAsset('sprites/attacks/thunder_strike.png')),
}
REWARD_ART = {kind:SpriteAsset(f'sprites/rewards/{kind}.png') for kind in ('gold','exp')}

CHEST_OPENING = {rarity:SpriteAsset(f'sprites/shop/chest_open_{rarity}.png')
                 for rarity in ('common','rare','unique','legendary')}
NEW_BADGE = SpriteAsset('ui/new_badge.png')


class EquipmentArt:
    def __init__(self):
        self.icons={key:SpriteAsset(f'sprites/equipment/{key}.png') for key in RULES['types']}
        self.effects={rarity:SpriteAsset(f'sprites/equipment_fx/{rarity}.png') for rarity in RULES['rarities']}

    def draw(self,art,item,x,y,clock=0.,size=48):
        spec=definition(item)
        self.effects[spec['rarity']].draw(art,x,y,clock,scale=size/64)
        self.icons[spec['type']].draw(art,x,y,0.,scale=size/64)


EQUIPMENT_ART = EquipmentArt()

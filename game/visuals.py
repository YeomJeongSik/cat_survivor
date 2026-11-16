"""Asset objects only; playable character rules remain in characters.py."""
from dataclasses import dataclass


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

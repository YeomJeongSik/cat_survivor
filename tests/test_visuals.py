"""Contracts for visual-only character/attack registration and new PNG sheets."""
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock
from game.characters import CHARACTERS
from game.visuals import CHARACTER_ART, REWARD_ART

ROOT=Path(__file__).resolve().parents[1]


class VisualAssetTests(unittest.TestCase):
    def test_new_sheets_match_metadata_and_original_timing(self):
        root=ROOT/'output/nyangi_art_v5'
        manifest=json.loads((root/'assets_manifest.json').read_text())
        old=json.loads((ROOT/'output/nyangi_art_v1/assets_manifest.json').read_text(encoding='utf-8-sig'))
        originals={Path(e['file']).stem:e for e in old['entries'] if '/cat/tobi_default/' in e['file']}
        self.assertEqual(len(manifest['entries']),23)
        self.assertEqual(sum(e['frames'] for e in manifest['entries']),154)
        for spec in manifest['entries']:
            with self.subTest(file=spec['file']):
                data=(root/'png'/spec['file']).read_bytes()
                self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II',data[16:24]),(spec['width'],spec['height']))
                self.assertEqual(hashlib.sha256(data).hexdigest(),spec['sha256'])
                self.assertEqual(spec['width'],spec['frame_width']*spec['frames'])
                self.assertGreater(spec['unique_frames'],1)
                if '/cat/' in spec['file']:
                    before=originals[Path(spec['file']).stem]
                    for key in ('frames','fps','loop','pivot','frame_width','frame_height'):
                        self.assertEqual(spec[key],before[key])

    def test_asset_objects_forward_animation_and_direction(self):
        art=Mock()
        CHARACTER_ART['witch'].draw(art,100,200,'walk',.5,flip=True,scale=2)
        art.sprite.assert_called_once_with('sprites/cat/witch/walk.png',100,200,.5,foot=True,flip=True,scale=2)
        art.reset_mock()
        CHARACTER_ART['ninja'].attack.draw(art,200,300,.1,rotation=1.2)
        art.sprite.assert_called_once_with('sprites/attacks/thunder_strike.png',200,300,.1,rotation=1.2)
        art.reset_mock()
        REWARD_ART['gold'].draw(art,20,30,.4)
        art.sprite.assert_called_once_with('sprites/rewards/gold.png',20,30,.4)

    def test_unfinished_characters_are_visual_only(self):
        self.assertEqual(set(CHARACTERS),{'nabi','black'})
        for key,spec in CHARACTERS.items():
            self.assertEqual(CHARACTER_ART[key].skin,spec['skin'])
        self.assertEqual(set(CHARACTER_ART),{'nabi','black','witch','ninja'})
        self.assertEqual(CHARACTER_ART['black'].attack.path,'sprites/attacks/claw_slash.png')

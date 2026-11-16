"""Versioned PNG and animation contracts without an image-library dependency."""
import hashlib
import json
from pathlib import Path
import struct
import unittest

from game.characters import CHARACTERS

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT/'output/nyangi_art_v4'


class ArtAssetTests(unittest.TestCase):
    def test_manifest_matches_png_files(self):
        manifest = json.loads((ART/'assets_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['entries']),11)
        for spec in manifest['entries']:
            with self.subTest(file=spec['file']):
                data = (ART/'png'/spec['file']).read_bytes()
                self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II',data[16:24]),(spec['width'],spec['height']))
                self.assertEqual(hashlib.sha256(data).hexdigest(),spec['sha256'])

    def test_black_character_keeps_existing_animation_timing(self):
        original = json.loads((ROOT/'output/nyangi_art_v1/assets_manifest.json').read_text(encoding='utf-8-sig'))
        latest = json.loads((ART/'assets_manifest.json').read_text(encoding='utf-8'))
        specs = {e['file']:e for e in original['entries']}
        sheets = [e for e in latest['entries'] if e['file'].startswith('sprites/cat/black/')]
        self.assertEqual(len(sheets),9)
        self.assertEqual(CHARACTERS['black']['skin'],'black')
        for spec in sheets:
            old = specs[spec['file'].replace('/black/','/tobi_default/')]
            for key in ('frame_width','frame_height','frames','fps','loop','pivot'):
                self.assertEqual(spec[key],old[key],(spec['file'],key))
            self.assertEqual(spec['width'],64*spec['frames'])
            self.assertGreater(spec['unique_frames'],1)

if __name__=='__main__':
    unittest.main()

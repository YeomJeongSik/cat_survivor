from array import array
import json
import hashlib
import unittest
import wave
from game.model import ROOT
from game.audio import COMBAT_SOUNDS, CHANNELS


class AudioAssetsTest(unittest.TestCase):
    def test_original_audio_files_are_valid_and_not_clipped(self):
        folder=ROOT/'assets/audio'
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['files']),23)
        tracks=0
        for entry in manifest['files']:
            with wave.open(str(folder/entry['file']),'rb') as stream:
                self.assertEqual((stream.getnchannels(),stream.getsampwidth(),stream.getframerate()),(1,2,22050))
                samples=array('h',stream.readframes(stream.getnframes()))
            self.assertTrue(samples)
            self.assertGreater(max(map(abs,samples)),100)
            self.assertLessEqual(max(map(abs,samples)),round(.82*32767)+1)
            if entry['file'].startswith('bgm/'):
                tracks+=1
                self.assertGreater(entry['seconds'],10)
                self.assertLessEqual(abs(samples[0]-samples[-1]),100)
        self.assertEqual(tracks,3)

    def test_combat_v2_has_distinct_valid_sounds_and_separate_attack_channels(self):
        folder=ROOT/'assets/audio/v2'
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual({entry['file'] for entry in manifest['files']},{f'sfx/{name}.wav' for name in COMBAT_SOUNDS})
        hashes=set()
        for entry in manifest['files']:
            path=folder/entry['file']
            hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
            with wave.open(str(path),'rb') as stream:
                self.assertEqual((stream.getnchannels(),stream.getsampwidth(),stream.getframerate()),(1,2,22050))
                samples=array('h',stream.readframes(stream.getnframes()))
            self.assertGreater(max(map(abs,samples)),1000)
            self.assertLessEqual(max(map(abs,samples)),round(.82*32767)+1)
            self.assertEqual((samples[0],samples[-1]),(0,0))
            self.assertAlmostEqual(len(samples)/22050,entry['seconds'],places=3)
        self.assertEqual(len(hashes),8)
        self.assertEqual(len({CHANNELS[name+'_attack'] for name in ('magpie','squirrel','bee','snake')}),4)
        self.assertNotIn(CHANNELS['enemy_hit'],(CHANNELS['land'],CHANNELS['enemy_death']))

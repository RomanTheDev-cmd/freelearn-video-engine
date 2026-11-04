#!/usr/bin/env python3
"""Small numeric/input checks in .venv-audio; no voice/music engine or subprocess."""
import sys
sys.dont_write_bytecode=True
import tempfile,unittest,json,contextlib,io
from pathlib import Path
from unittest.mock import patch
import numpy as np
import soundfile as sf
import process_audio as audio
import make_ambient


class AudioChecks(unittest.TestCase):
    def test_meditation_duck_override_preserves_lesson_and_input(self):
        original={'prompt_music_reduction_db':-6,'meditation_prompt_music_reduction_db':-2}
        self.assertEqual(audio.mix_settings(original,'meditation')['prompt_music_reduction_db'],-2)
        self.assertEqual(audio.mix_settings(original,'lesson')['prompt_music_reduction_db'],-6)
        self.assertEqual(audio.mix_settings(original,'meditation')['meditation_speech_lufs'],-30.5)
        self.assertEqual(original,{'prompt_music_reduction_db':-6,'meditation_prompt_music_reduction_db':-2})

    def test_invalid_meditation_duck_override_rejected(self):
        for value in [None,True,2,float('nan')]:
            with self.subTest(value=value),self.assertRaises(RuntimeError):audio.mix_settings({'meditation_prompt_music_reduction_db':value},'meditation')

    def test_ambient_held_voicing_has_no_repeated_attacks(self):
        for duration in [5,60,450]:
            events=make_ambient.composition(duration)
            on=[e for e in events if e.type=='note_on']
            off=[e for e in events if e.type=='note_off']
            self.assertEqual([e.note for e in on],[45,50,57,64])
            self.assertTrue(all(e.time==0 for e in on))
            self.assertEqual(sorted(e.note for e in on),sorted(e.note for e in off))
            self.assertTrue(all(0<e.time<duration for e in off))

    def test_ambient_rejects_nonfinite_and_empty_duration(self):
        for duration in [0,-1,float('nan'),float('inf')]:
            with self.subTest(duration=duration),self.assertRaises(RuntimeError):make_ambient.composition(duration)

    def setUp(self):
        self.external=patch('subprocess.run',side_effect=AssertionError('No external processes'))
        self.external.start();self.addCleanup(self.external.stop)

    def test_read_preserves_stereo_and_resamples_mono(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav';sf.write(path,np.full((100,2),.02,dtype='float32'),48000,subtype='FLOAT')
            self.assertEqual(audio.read(path,48000).shape,(100,2))
            sf.write(path,np.full(100,.02,dtype='float32'),24000,subtype='FLOAT');result=audio.read(path,48000)
            self.assertEqual(result.shape,(200,2));self.assertTrue(np.array_equal(result[:,0],result[:,1]))

    def test_empty_nonfinite_and_multichannel_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav'
            for data in [np.empty((0,1),dtype='float32'),np.full((100,1),np.nan,dtype='float32'),np.zeros((100,3),dtype='float32')]:
                sf.write(path,data,48000,subtype='FLOAT')
                with self.assertRaises(RuntimeError):audio.read(path,48000)

    def test_metrics_and_level_do_not_create_nan_or_raise_peak(self):
        t=np.arange(48000,dtype='float32')/48000;data=np.repeat((.3*np.sin(2*np.pi*300*t))[:,None],2,axis=1)
        quieter=audio.level(data,48000,-26);self.assertLessEqual(float(np.max(np.abs(quieter))),.85)
        self.assertAlmostEqual(audio.metrics(quieter,48000)['integrated_lufs'],-26,places=1)
        silence=np.zeros_like(data);self.assertIsNone(audio.metrics(silence,48000)['integrated_lufs']);self.assertTrue(np.array_equal(audio.level(silence,48000,-26),silence))

    def test_metrics_reject_empty_and_nan(self):
        for data in [np.empty((0,2)),np.full((10,2),np.nan)]:
            with self.assertRaises(RuntimeError):audio.metrics(data,48000)

    def test_music_length_mismatch_rejected_before_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);speech=folder/'speech.wav';music=folder/'music.wav';style=folder/'style.json';style.write_text('{"audio":{}}')
            sf.write(speech,np.zeros(4800),48000);sf.write(music,np.zeros(2400),48000)
            args=['process_audio.py','--speech',str(speech),'--music',str(music),'--output',str(folder/'out.wav'),'--style',str(style),'--type','meditation']
            with patch.object(sys,'argv',args),patch.object(audio,'Pedalboard',side_effect=AssertionError('No effects before validation')):
                with self.assertRaisesRegex(RuntimeError,'Длительности'):audio.main()
            self.assertFalse((folder/'out.wav').exists())

    def test_processed_fullscale_overflow_rejected_before_effects_and_output(self):
        for value,rate in [(2.,48000),(-2.,48000),(float(np.nextafter(np.float32(1),np.float32(2))),48000),(float(np.nextafter(np.float32(-1),np.float32(-2))),48000),(2.,192000)]:
            with self.subTest(value=value,rate=rate),tempfile.TemporaryDirectory() as folder:
                folder=Path(folder);speech=folder/'speech.wav';style=folder/'style.json';output=folder/'new'/'out.wav'
                style.write_text('{"audio":{}}');data=np.zeros(rate,dtype='float32');data[rate//2]=value
                sf.write(speech,data,rate,subtype='FLOAT')
                args=['process_audio.py','--speech',str(speech),'--speech-processed','--output',str(output),'--style',str(style),'--type','meditation']
                with patch.object(sys,'argv',args),patch.object(audio,'Pedalboard',side_effect=AssertionError('No effects before processed input validation')):
                    with self.assertRaisesRegex(RuntimeError,'PCM'):audio.main()
                self.assertFalse(output.parent.exists())

    def test_processed_gain_and_saved_stem_metrics_without_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);speech=folder/'speech.wav';style=folder/'style.json';output=folder/'out.wav'
            style.write_text('{"audio":{"meditation_speech_lufs":-50}}')
            t=np.arange(48000,dtype='float32')/48000
            data=np.column_stack((.2*np.sin(2*np.pi*300*t),.3*np.sin(2*np.pi*600*t))).astype('float32')
            data[100,0]=1.;data[101,0]=-1.
            sf.write(speech,data,48000,subtype='FLOAT')
            args=['process_audio.py','--speech',str(speech),'--speech-processed','--output',str(output),'--style',str(style),'--type','meditation']
            with patch.object(sys,'argv',args),patch.object(audio,'Pedalboard',side_effect=AssertionError('Processed speech must not enter effects')),contextlib.redirect_stdout(io.StringIO()):audio.main()
            saved,rate=sf.read(folder/'out.speech.wav',dtype='float32',always_2d=True)
            self.assertEqual(rate,48000);np.testing.assert_allclose(saved,data,atol=2**-23,rtol=0)
            report=json.loads((folder/'out.audio.json').read_text());self.assertTrue(report['reused_processed_speech'])
            for name in ['speech','music']:
                stem,rate=sf.read(folder/f'out.{name}.wav',dtype='float32',always_2d=True)
                measured=audio.metrics(stem,rate)
                for field in ['sample_peak_dbfs','integrated_lufs','rms_dbfs']:
                    if measured[field] is None:self.assertIsNone(report[name][field])
                    else:self.assertAlmostEqual(report[name][field],measured[field],delta=.02)

    def test_default_meditation_level_applies_without_music(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);speech=folder/'speech.wav';style=folder/'style.json';output=folder/'out.wav';style.write_text('{"audio":{}}')
            t=np.arange(48000,dtype='float32')/48000;sf.write(speech,.3*np.sin(2*np.pi*300*t),48000,subtype='FLOAT')
            args=['process_audio.py','--speech',str(speech),'--output',str(output),'--style',str(style),'--type','meditation']
            with patch.object(sys,'argv',args),patch.object(audio,'Pedalboard',return_value=lambda data,rate:data),contextlib.redirect_stdout(io.StringIO()):audio.main()
            saved,rate=sf.read(folder/'out.speech.wav',always_2d=True)
            self.assertAlmostEqual(audio.metrics(saved,rate)['integrated_lufs'],-30.5,delta=.02)

    def test_audio_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);speech=folder/'speech.wav';style=folder/'style.json';style.write_text('{"audio":{}}');speech.write_bytes(b'unchanged input')
            args=['process_audio.py','--speech',str(speech),'--output',str(speech),'--style',str(style),'--type','lesson']
            with patch.object(sys,'argv',args),self.assertRaisesRegex(RuntimeError,'исходниками'):audio.main()
            self.assertEqual(speech.read_bytes(),b'unchanged input')


if __name__=='__main__':unittest.main(verbosity=2)

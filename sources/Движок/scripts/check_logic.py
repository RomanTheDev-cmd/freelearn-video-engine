#!/usr/bin/env python3
"""Fast logic regressions: no MP4, model inference, network or synthesis."""
import copy
import hashlib
import contextlib
import io
import os
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
import build_video as build
import check_video
import check_speech
import doctor
from check_video import stream_errors,caption_matches,caption_region,review_metadata_errors,file_integrity_errors
from scenario import validate_scenario,number
from export_files import commit_bundle,validate_output_paths,validate_report_path
from audio_plan import merge_prompt_intervals,validate_mix_settings
from audio_plan import tts_filter_chain
from pcm_cache import validate_pcm
from check_speech import speech_events


from check_workflow_logic import WorkflowChecks
from check_review_logic import ReviewChecks


class LogicChecks(unittest.TestCase):
    def test_native_tts_omits_tempo_filter(self):
        self.assertEqual(tts_filter_chain(1.0),'loudnorm=I=-20:TP=-3:LRA=7')

    def test_explicit_tts_tempo_is_pitch_preserving(self):
        self.assertTrue(tts_filter_chain(1.55).startswith('atempo=0.64516129,'))

    def test_tts_tempo_rejects_invalid_values(self):
        for value in [True,0,.49,2.01,float('nan'),float('inf'),'1']:
            with self.subTest(value=value),self.assertRaises(RuntimeError):tts_filter_chain(value)

    def setUp(self):
        self.external=patch('subprocess.run',side_effect=AssertionError('No external process allowed in logic checks'))
        self.external.start();self.addCleanup(self.external.stop)

    def test_music_defaults(self):
        self.assertTrue(build.resolve_music({'type':'meditation'}))
        self.assertFalse(build.resolve_music({'type':'lesson'}))

    def test_music_false_rejected_for_meditation(self):
        with self.assertRaises(RuntimeError):build.resolve_music({'type':'meditation','music':False})

    def test_music_requires_boolean(self):
        for value in ['false','true',0,1,None]:
            with self.subTest(value=value),self.assertRaises(RuntimeError):build.resolve_music({'type':'lesson','music':value})

    def test_caption_intervals_preserve_tiny_gaps(self):
        scenes=[{'kind':'nature','caption':'Исходная','duration_seconds':1}]
        cues=[(.02,.4,'Первая'),(.42,.98,'Вторая')]
        result=build.split_caption_events(scenes,[0],[1],cues)
        self.assertAlmostEqual(sum(duration for _,duration in result),1)
        self.assertEqual(result[-1][0]['caption'],'Вторая')
        self.assertEqual(result[2][0]['caption'],'Первая')

    def test_caption_tail_holds_last_cue(self):
        result=build.split_caption_events([{'kind':'nature','caption':'Старая'}],[0],[10],[(1,3,'Новая')])
        self.assertEqual(result[-1][0]['caption'],'Новая')
        self.assertAlmostEqual(sum(d for _,d in result),10)

    def test_silent_scene_retains_caption_and_duration(self):
        result=build.split_caption_events([{'kind':'nature','caption':'Смотрите'}],[0],[10],[])
        self.assertEqual([(s['caption'],d) for s,d in result],[('Смотрите',10)])

    def test_valid_source_interval(self):
        self.assertAlmostEqual(build.validate_source_interval(1,5,6),3.75)

    def test_dissolve_keeps_normal_duration(self):
        self.assertEqual(build.dissolve_duration([{'duration':1},{'duration':30},{'duration':3}],30,.9),.9)

    def test_dissolve_fits_short_shots_at_both_frame_rates(self):
        for fps in [15,30]:
            for frames in [1,2,3,10]:
                with self.subTest(fps=fps,frames=frames):
                    result=build.dissolve_duration([{'duration':1},{'duration':frames/fps},{'duration':3}],fps,.9)
                    self.assertGreater(result,0)
                    self.assertLessEqual(result,frames/fps)
                    self.assertAlmostEqual(result*fps,round(result*fps))

    def test_dissolve_rejects_invalid_inputs(self):
        for value in [0,-1,True,float('nan'),float('inf')]:
            with self.subTest(value=value),self.assertRaises(RuntimeError):
                build.dissolve_duration([{'duration':1},{'duration':3}],30,value)
        for groups in [[],[{'duration':.001}],[{'duration':float('nan')}]]:
            with self.subTest(groups=groups),self.assertRaises(RuntimeError):build.dissolve_duration(groups,30,.9)

    def test_dissolve_does_not_retime_shots(self):
        groups=[{'duration':1},{'duration':2/30},{'duration':20},{'duration':3}]
        original=copy.deepcopy(groups)
        self.assertEqual(build.dissolve_duration(groups,30,.9),2/30)
        self.assertEqual(groups,original)

    def test_invalid_source_intervals(self):
        for values in [(float('nan'),5,6),(0,float('nan'),6),(0,float('inf'),6),(-1,3,6),(2,1,6),(0,7,6),(0,.2,6)]:
            with self.subTest(values=values),self.assertRaises(RuntimeError):build.validate_source_interval(*values)

    def test_missing_speech_cache(self):
        with tempfile.TemporaryDirectory() as folder:self.assertFalse(build.validate_cached_speech(Path(folder)/'missing.wav'))

    def test_valid_speech_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav'
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\x01\x00'*240)
            self.assertTrue(build.validate_cached_speech(path))

    def test_empty_or_truncated_cache_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav';path.write_bytes(b'')
            with self.assertRaises(RuntimeError):build.validate_cached_speech(path)
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\x01\x00'*240)
            path.write_bytes(path.read_bytes()[:-20])
            with self.assertRaises(RuntimeError):build.validate_cached_speech(path)

    def test_approval_checked_before_cache(self):
        with patch.dict(build.STYLE['voice'],approved_for_publication=False),patch.object(build,'speech_path',side_effect=AssertionError('approval must come first')):
            with self.assertRaisesRegex(RuntimeError,'не одобрен'):build.synthesize('Текст','approved',Path('.'),Path('.'))

    def test_truthy_string_cannot_approve_voice(self):
        with patch.dict(build.STYLE['voice'],approved_for_publication='false'):
            with self.assertRaisesRegex(RuntimeError,'не одобрен'):build.synthesize('Текст','approved',Path('.'),Path('.'))

    def streams(self):
        v={'codec_name':'h264','width':1920,'height':1080,'avg_frame_rate':'30/1','duration':'90','nb_frames':'2700'}
        a={'codec_name':'aac','sample_rate':'48000','channels':2,'duration':'90'}
        return v,a,{'duration_seconds':90,'format':'16:9','preview':False}

    def test_valid_streams(self):
        v,a,meta=self.streams();self.assertEqual(stream_errors(v,a,90,meta,'16:9',False),[])

    def test_truncated_video_uses_scenario_duration(self):
        v,a,meta=self.streams();v.update(duration='60',nb_frames='1800');a['duration']='60'
        self.assertTrue(stream_errors(v,a,60,meta,'16:9',False))

    def test_wrong_stream_formats_rejected(self):
        v,a,meta=self.streams()
        for field,value in [('sample_rate','24000'),('channels',1),('codec_name','mp3')]:
            bad=copy.deepcopy(a);bad[field]=value
            self.assertTrue(stream_errors(v,bad,90,meta,'16:9',False))
        v['avg_frame_rate']='15/1';v['nb_frames']='1350'
        self.assertTrue(stream_errors(v,a,90,meta,'16:9',False))

    def test_explicit_duration_cannot_hide_metadata_conflict(self):
        v,a,meta=self.streams();meta['duration_seconds']=120
        self.assertTrue(stream_errors(v,a,90,meta,'16:9',False,90))
        meta['duration_seconds']=float('nan')
        self.assertTrue(stream_errors(v,a,90,meta,'16:9',False,90))

    def test_empty_asr_is_not_success(self):
        with self.assertRaises((RuntimeError,ValueError)):speech_events({'duration_seconds':90,'caption_events':[]})

    def test_asr_intervals_validate_and_group(self):
        result=speech_events({'duration_seconds':5,'caption_events':[{'start':1,'end':2,'text':'Первая часть'},{'start':2,'end':3,'text':'и вторая'}]})
        self.assertEqual(len(result),1);self.assertEqual(result[0]['source_caption_count'],2)
        for start,end in [(float('nan'),3),(3,2),(-1,2),(1,6)]:
            with self.subTest(start=start,end=end),self.assertRaises((RuntimeError,ValueError)):speech_events({'duration_seconds':5,'caption_events':[{'start':start,'end':end,'text':'Текст'}]})

    def test_asr_overlap_rejected(self):
        with self.assertRaises((RuntimeError,ValueError)):speech_events({'duration_seconds':5,'caption_events':[{'start':1,'end':3,'text':'Текст'},{'start':2,'end':4,'text':'Другой'}]})


    def test_cached_overflow_stops_before_batch_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);wav=folder/'known.wav'
            with wave.open(str(wav),'wb') as f:
                f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\x01\0'*48000)
            scenes=[{'kind':'nature','narration':'Известная'},{'kind':'nature','narration':'Новая'}]
            with patch.object(build,'speech_path',side_effect=lambda text,*_:wav if text=='Известная' else folder/'missing.wav'),patch.object(build,'prepare_speech') as batch:
                with self.assertRaisesRegex(RuntimeError,'сцены 1'):build.make_narration(scenes,[0,1],[1,10],folder/'timeline.wav','review',folder,2.8)
                batch.assert_not_called();self.assertFalse((folder/'timeline.wav').exists())

    def test_cached_narration_keeps_pcm_length_and_sentence_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);wav=folder/'fixture.wav'
            with wave.open(str(wav),'wb') as f:
                f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(b'\x7c\x00'*2400)
            with patch.object(build,'speech_path',return_value=wav):
                cues=build.make_narration([{'kind':'nature','narration':'Раз. Два.'}],[0],[3],folder/'timeline.wav','review',folder,.6)
            self.assertEqual(len(cues),2);self.assertAlmostEqual(cues[1][0]-cues[0][1],.6)
            with wave.open(str(folder/'timeline.wav'),'rb') as f:
                self.assertEqual(f.getnframes(),72000);pcm=f.readframes(f.getnframes())
            self.assertEqual(pcm[9600*2:9601*2],b'\x7c\x00')
            self.assertEqual(pcm[14400*2:14401*2],b'\0\0')

    def test_cached_fit_accepts_unknown_lengths_without_generation(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(build,'speech_path',return_value=Path(folder)/'missing.wav'):
            build.check_cached_narration_fit([{'kind':'nature','narration':'Новая'}],[0],[10],'review',Path(folder),2.8)

    def test_pauses_alone_can_prove_overflow(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(build,'speech_path',return_value=Path(folder)/'missing.wav'):
            with self.assertRaisesRegex(RuntimeError,'не помещается'):build.check_cached_narration_fit([{'kind':'nature','narration':'Раз. Два. Три.'}],[0],[5],'review',Path(folder),2.8)

    def test_srt_short_cues_keep_real_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'captions.srt';build.write_srt([(0,.1,'Раз'),(.1,.2,'Два')],path)
            text=path.read_text();self.assertIn('00:00:00,000 --> 00:00:00,100',text);self.assertIn('00:00:00,100 --> 00:00:00,200',text)

    def test_srt_rejects_invalid_and_overlapping_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            for cues in [[(0,0,'Текст')],[(float('nan'),1,'Текст')],[(-1,1,'Текст')],[(0,.0001,'Текст')],[(0,1,'Раз'),(.5,2,'Два')]]:
                with self.subTest(cues=cues),self.assertRaises(RuntimeError):build.write_srt(cues,Path(folder)/'captions.srt')

    def test_srt_empty_and_long_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'captions.srt';build.write_srt([],path);self.assertEqual(path.read_text(),'')
            build.write_srt([(3661.123,3662.456,'Текст')],path);self.assertIn('01:01:01,123 --> 01:01:02,456',path.read_text())

    def test_theme_does_not_inherit_previous_render(self):
        with patch.dict(build.STYLE,theme='dark'):
            self.assertEqual(build.choose_theme({}),build.DEFAULT_THEME)
            self.assertEqual(build.choose_theme({'theme':'dark'}),'dark')
            self.assertEqual(build.choose_theme({'theme':'dark'},'light'),'light')

    def test_invalid_explicit_theme_is_not_silently_replaced(self):
        for data,override in [({'theme':''},None),({'theme':None},None),({},''),({'theme':'sepia'},None)]:
            with self.subTest(data=data,override=override),self.assertRaises(RuntimeError):build.choose_theme(data,override)

    def test_ocr_preserves_word_order_and_repeated_negation(self):
        self.assertFalse(caption_matches('Не спешите и не оценивайте','Не спешите и оценивайте'))
        self.assertFalse(caption_matches('Почувствуйте опору под телом','Под телом опору почувствуйте'))
        self.assertTrue(caption_matches('Не спешите и не оценивайте.','Не спешите и не оценивайте'))

    def test_ocr_handles_wrap_punctuation_and_yo(self):
        self.assertTrue(caption_matches('Мягко возвращайтесь. Всё хорошо.','Мягко возвращайтесь! Все\nхорошо.'))
        self.assertFalse(caption_matches('Текст',''))

    def test_ocr_crops_out_widget_title(self):
        for width,height in [(1920,1080),(960,540),(1080,1920),(540,960)]:
            x,y,right,bottom=build.geometry(width,height)['widget'];crop=caption_region(width,height)
            self.assertGreaterEqual(crop[1],y+(bottom-y)*.34)
            self.assertLess(crop[1],y+(bottom-y)*.38)
            self.assertEqual((crop[0],crop[2],crop[3]),(x,right,bottom))

    def test_reference_uses_audio_file_in_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);audio=root/'different-name.wav';audio.write_bytes(b'synthetic fixture')
            profile={'synthetic':True,'recording_of_person':False,'audio_file':audio.name,'sha256':hashlib.sha256(audio.read_bytes()).hexdigest()}
            path=root/'profile.json';path.write_text(json.dumps(profile))
            with patch.object(build,'ROOT',root):self.assertEqual(build.reference_fingerprint({'reference_profile':'profile.json'})[1],profile['sha256'])

    def test_reference_rejected_before_model_fingerprinting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'voice.wav').write_bytes(b'fixture');path=root/'profile.json';path.write_text(json.dumps({'synthetic':'false','recording_of_person':False,'audio_file':'voice.wav','sha256':'invalid'}))
            with patch.object(build,'ROOT',root),patch.dict(build.STYLE['voice'],reference_profile='profile.json'),patch.object(build,'model_fingerprint') as model:
                with self.assertRaises(RuntimeError):build.speech_path('Текст','review',root)
                model.assert_not_called()

    def test_speech_cache_tracks_filter_plan(self):
        root=build.ROOT;read=Path.read_bytes
        with patch.object(build,'model_fingerprint',return_value={'fixture':'same-model-content'}):
            first=build.speech_path('Текст','review',Path('/unused'))
            self.assertEqual(first,build.speech_path('Текст','review',Path('/unused')))
            def modified(path):return b'changed filter plan' if path==root/'scripts/audio_plan.py' else read(path)
            with patch.object(Path,'read_bytes',modified):
                self.assertNotEqual(first,build.speech_path('Текст','review',Path('/unused')))

    def test_stage_widget_holds_instruction_across_utterances(self):
        scene={'kind':'nature','caption':'Оставайтесь с ориентиром.','narration':'Первая. Вторая.','video_offset_seconds':2}
        original=copy.deepcopy(scene)
        result=build.make_display_plan([scene],[0],[60],[(3,5,'Первая.'),(8,10,'Вторая.')],'stage')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0][1],60)
        self.assertEqual(result[0][0]['caption'],original['caption'])
        self.assertEqual(result[0][0]['_video_offset_seconds'],2)
        self.assertNotIn('narration',result[0][0])
        self.assertEqual(scene,original)

    def test_speech_caption_mode_keeps_existing_behavior(self):
        scene={'kind':'nature','caption':'Этап'};cues=[(3,5,'Первая.'),(8,10,'Вторая.')]
        self.assertEqual(build.make_display_plan([scene],[0],[60],cues,'speech'),build.split_caption_events([scene],[0],[60],cues))

    def test_caption_mode_defaults_and_invalid_values(self):
        data=self.scenario()
        self.assertEqual(validate_scenario(data,'review',build.STYLE)['caption_mode'],'stage')
        lesson=self.scenario();lesson.update(type='lesson',target_duration_seconds=60);lesson['scenes'][1].update(duration_seconds=56,narration='Текст')
        self.assertEqual(validate_scenario(lesson,'review',build.STYLE)['caption_mode'],'speech')
        for mode in ['',None,True,{},'word']:
            bad=copy.deepcopy(data);bad['caption_mode']=mode
            with self.subTest(mode=mode),self.assertRaises(RuntimeError):validate_scenario(bad,'review',build.STYLE)


    def scenario(self):
        return {'type':'meditation','target_duration_seconds':6,'scenes':[{'kind':'intro','duration_seconds':1},{'kind':'nature','duration_seconds':2,'asset_id':'nature-1'},{'kind':'outro','duration_seconds':3}]}

    def test_all_shipped_scenarios_validate_without_mutation(self):
        for path in (build.ROOT/'assets/examples').glob('*.json'):
            data=json.loads(path.read_text());original=copy.deepcopy(data)
            validate_scenario(data,'review',build.STYLE);self.assertEqual(data,original)

    def test_malformed_scenarios_fail_without_external_process(self):
        for data in [None,[],{}, {'type':'meditation','scenes':'wrong'}]:
            with self.subTest(data=data),self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)

    def test_schema_rejects_wrong_field_types(self):
        for field,value in [('target_duration_seconds',True),('target_duration_seconds','6'),('format',{}),('music','false'),('approved_voice','false'),('theme',[]),('scenes',{})]:
            data=self.scenario();data[field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)
        for field,value in [('narration',None),('caption',42),('duration_seconds',True),('asset_id',[]),('points','text'),('image_crop',[0,0,float('nan'),1])]:
            data=self.scenario();data['scenes'][1][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)

    def test_schema_rejects_timing_and_unsupported_music_before_work(self):
        for target in [4,3601,float('inf'),10**1000]:
            data=self.scenario();data['target_duration_seconds']=target
            with self.subTest(target=str(target)[:20]),self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)
        data=self.scenario();data['target_duration_seconds']=6.019
        with self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)

    def test_schema_rejects_subframe_scenes_and_late_speech(self):
        data=self.scenario();data['scenes'][1]['duration_seconds']=.001;data['scenes'][2]['duration_seconds']=4.999
        with self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)
        data=self.scenario();data['scenes'][1].update(narration='Текст',narration_lead_seconds=2)
        with self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)

    def test_invalid_input_rejected_before_binary_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json';path.write_text('[]')
            with patch.object(build,'require_binary',side_effect=AssertionError('No binary lookup')):
                with self.assertRaises(RuntimeError):build.render(path,Path(folder)/'unused.mp4')

    def test_schema_rejects_ignored_video_crop(self):
        data=self.scenario();data['scenes'][1].update(video_asset_id='video',image_crop=[0,0,1,1])
        with self.assertRaisesRegex(RuntimeError,'только к фотографии'):validate_scenario(data,'review',build.STYLE)

    def test_output_paths_protect_source_and_companions(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);dest=folder/'video.mp4';source=folder/'video.render.json';source.write_text('{}')
            with self.assertRaises(RuntimeError):validate_output_paths(dest,[source])
            with self.assertRaises(RuntimeError):validate_output_paths(folder/'video.json')
            (folder/'directory.mp4').mkdir()
            with self.assertRaises(RuntimeError):validate_output_paths(folder/'directory.mp4')

    def test_report_paths_protect_mp4_metadata_and_skill(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'video.render.json';source.write_text('{}')
            for output in [folder/'video.mp4',source,build.ROOT/'report.json']:
                with self.subTest(output=output),self.assertRaises(RuntimeError):validate_report_path(output,[source],build.ROOT)
            validate_report_path(folder/'safe.json',[source],build.ROOT)

    def bundle(self,folder):
        source=folder/'source';dest=folder/'dest';source.mkdir();dest.mkdir();pairs=[]
        for name in ['result.mp4','result.srt','result.render.json']:
            a=source/name;b=dest/name;a.write_bytes(b'new '+name.encode());b.write_bytes(b'old '+name.encode());pairs.append((a,b))
        return pairs

    def test_bundle_commit_retains_previous_files(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs=self.bundle(Path(folder));history=commit_bundle(pairs)
            for source,dest in pairs:
                self.assertEqual(dest.read_bytes(),source.read_bytes());self.assertTrue((history/'previous'/dest.name).read_bytes().startswith(b'old '))
            self.assertEqual(json.loads((history/'manifest.json').read_text())['status'],'complete')

    def test_bundle_rolls_back_mid_commit_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs=self.bundle(Path(folder));replace=os.replace;calls=[]
            def fail_once(source,dest):
                calls.append(str(dest))
                if len(calls)==2:raise OSError('Injected disk error')
                return replace(source,dest)
            with patch('export_files.os.replace',side_effect=fail_once),self.assertRaises(OSError):commit_bundle(pairs)
            for _,dest in pairs:self.assertTrue(dest.read_bytes().startswith(b'old '))
            self.assertFalse(any(name.endswith('.mp4') for name in calls[:2]))

    def test_bundle_staging_failure_leaves_old_files(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs=self.bundle(Path(folder))
            with patch('export_files.shutil.copy2',side_effect=OSError('No space')),self.assertRaises(OSError):commit_bundle(pairs)
            for _,dest in pairs:self.assertTrue(dest.read_bytes().startswith(b'old '))

    def test_bundle_rolls_back_new_targets_without_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            pairs=self.bundle(Path(folder));pairs[1][1].unlink();replace=os.replace;calls=[]
            def fail_once(source,dest):
                calls.append(str(dest))
                if len(calls)==2:raise OSError('Injected error')
                return replace(source,dest)
            with patch('export_files.os.replace',side_effect=fail_once),self.assertRaises(OSError):commit_bundle(pairs)
            self.assertFalse(pairs[1][1].exists());self.assertTrue(pairs[0][1].read_bytes().startswith(b'old '))
            self.assertTrue(list((Path(folder)/'dest/.freelearn-cache').glob('export-*/failed/result.srt')))

    def test_metadata_rejects_malformed_events_and_gaps(self):
        for events in [[None],[{'start':'bad','duration':1}],[{'start':0,'duration':float('inf')}],[{'start':0,'duration':1,'caption':'A'},{'start':2,'duration':1,'caption':'B'}]]:
            with self.subTest(events=events):self.assertTrue(review_metadata_errors({'display_events':events},3,True))
        self.assertTrue(review_metadata_errors([],3))
        self.assertTrue(review_metadata_errors({},3,True))

    def test_metadata_valid_silent_timeline(self):
        meta={'scene_boundaries':[0,1],'display_events':[{'start':0,'duration':1,'caption':''},{'start':1,'duration':2,'caption':'Пауза'}],'caption_events':[]}
        self.assertEqual(review_metadata_errors(meta,3,True),[])

    def test_file_hash_detects_stale_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.bin';path.write_bytes(b'actual')
            self.assertEqual(file_integrity_errors(path,{'video_sha256':hashlib.sha256(b'actual').hexdigest()}),[])
            self.assertTrue(file_integrity_errors(path,{'video_sha256':hashlib.sha256(b'other').hexdigest()}))

    def test_checker_fails_early_without_frame_or_audio_scans(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);video=folder/'fixture.mp4';report=folder/'report.json';v,a,_=self.streams()
            info={'streams':[{**v,'codec_type':'video'},{**a,'codec_type':'audio'}],'format':{'duration':'90'}}
            with patch.object(sys,'argv',['check_video.py',str(video),'--ocr','--output',str(report)]),patch.object(check_video,'call',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(info).encode(),stderr=b'')) as call,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_video.main(),1);self.assertEqual(call.call_count,1)
            self.assertTrue(json.loads(report.read_text())['errors'])

    def test_asr_interruption_does_not_leave_old_success(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);video=folder/'fixture.mp4';video.write_bytes(b'placeholder');report=folder/'report.json';video.with_suffix('.render.json').write_text(json.dumps({'duration_seconds':3,'caption_events':[{'start':1,'end':2,'text':'Текст'}]}));report.write_text('{"all_exact_words":true}')
            with patch.object(sys,'argv',['check_speech.py',str(video),'--output',str(report)]),patch.dict(sys.modules,{'mlx_whisper':SimpleNamespace()}):
                with self.assertRaises(AssertionError):check_speech.main()
            self.assertFalse(json.loads(report.read_text())['all_exact_words']);self.assertEqual(json.loads(report.read_text())['status'],'incomplete')

    def test_ducking_intervals_sort_and_merge_without_lost_prompts(self):
        self.assertEqual(merge_prompt_intervals([[20,22],[1,3],[5,7],[6,8]],30),[[1.,8.],[20.,22.]])
        self.assertEqual(merge_prompt_intervals([],30),[])

    def test_ducking_intervals_reject_invalid_numbers(self):
        for cues in [[[float('nan'),2]],[[-1,2]],[[3,2]],[[0,31]],[[True,2]],['bad']]:
            with self.subTest(cues=cues),self.assertRaises(RuntimeError):merge_prompt_intervals(cues,30)

    def test_mix_settings_reject_nan_and_amplifying_reduction(self):
        for value in [float('nan'),float('inf'),True,10**1000,6]:
            with self.subTest(value=str(value)[:20]),self.assertRaises(RuntimeError):validate_mix_settings({'prompt_music_reduction_db':value},'meditation')
        self.assertEqual(validate_mix_settings({},'meditation')['meditation_speech_lufs'],-26)

    def test_ocr_extra_words_do_not_pass(self):
        self.assertFalse(caption_matches('Ничего не нужно менять','Ничего не нужно менять никогда'))
        self.assertFalse(caption_matches('Всё хорошо','Подсказка всё хорошо'))


    def test_pcm_cache_rejects_silence_wrong_duration_and_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.wav'
            with wave.open(str(path),'wb') as f:f.setparams((2,3,48000,0,'NONE','not compressed'));f.writeframes(b'\0'*48000*6)
            with self.assertRaises(RuntimeError):validate_pcm(path,48000,2,3,1)
            with wave.open(str(path),'wb') as f:f.setparams((2,3,48000,0,'NONE','not compressed'));f.writeframes(b'\1\0\0'*2*48000)
            self.assertTrue(validate_pcm(path,48000,2,3,1))
            with self.assertRaises(RuntimeError):validate_pcm(path,48000,2,3,2)
            path.write_bytes(path.read_bytes()[:-100])
            with self.assertRaises(RuntimeError):validate_pcm(path,48000,2,3,1)

    def mock_export(self,folder,fail_mux=False,voice="review",commands=None,data=None):
        script=folder/'scenario.json';script.write_text(json.dumps(self.scenario() if data is None else data));dest=folder/'video.mp4';dest.write_bytes(b'old video');dest.with_suffix('.mix.wav').write_bytes(b'old mix')
        frame=folder/'frame.png';frame.write_bytes(b'placeholder');probe={}
        def fake_run(args):
            args=[str(x) for x in args]
            if commands is not None:commands.append(args)
            if 'make_ambient.py' in args[1]:
                with wave.open(args[2],'wb') as f:f.setparams((2,3,48000,0,'NONE','not compressed'));f.writeframes(b'\1\0\0'*2*48000*6)
                return
            if 'process_audio.py' in args[1]:
                audio=Path(args[args.index('--output')+1]);audio.write_bytes(b'new mix')
                # Processor names are stem + suffix, not replacing the .mix part.
                for ext in ['.speech.wav','.music.wav']:Path(str(audio.with_suffix(''))+ext).write_bytes(b'new stem')
                audio.with_suffix('.audio.json').write_text('{}');return
            output=Path(args[-1])
            if '-c:a' in args and args[args.index('-c:a')+1]=='pcm_s24le':
                with wave.open(str(output),'wb') as f:f.setparams((2,3,48000,0,'NONE','not compressed'));f.writeframes(b'\1\0\0'*2*48000*round(float(args[args.index('-t')+1])))
                return
            if '-movflags' in args:
                self.assertNotEqual(output,Path(args[args.index('-i')+1]))
                if fail_mux:raise RuntimeError('Injected mux failure')
                output.write_bytes(b'complete mocked mux');return
            output.write_bytes(b'mocked picture stream')
            if '-frames:v' in args:frames=int(args[args.index('-frames:v')+1])
            elif '-t' in args:frames=round(float(args[args.index('-t')+1])*15)
            else:
                listing=Path(args[args.index('-i')+1]);frames=sum(probe[listing.parent/line.split("'")[1]]['nb_frames'] for line in listing.read_text().splitlines())
            probe[output]={'nb_frames':frames,'duration':frames/15}
        def fake_probe(args,**kwargs):
            path=Path(args[-1])
            if path.suffix=='.mp3':return SimpleNamespace(stdout=json.dumps({'streams':[{'codec_type':'audio','duration':'987.062856'}],'format':{'duration':'987.062856'}}),returncode=0,stderr='')
            record=probe[path]
            return SimpleNamespace(stdout=json.dumps({'streams':[record]}),returncode=0,stderr='')
        def fake_narration(scenes,starts,durations,output,*args,**kwargs):output.write_bytes(b'fixture timeline');return []
        with patch.object(build,'require_binary',return_value='ffmpeg'),patch.object(build,'make_slide',return_value=frame),patch.object(build,'make_media_overlay',return_value=frame),patch.object(build,'make_narration',side_effect=fake_narration),patch.object(build,'run',side_effect=fake_run),patch('subprocess.run',side_effect=fake_probe),contextlib.redirect_stdout(io.StringIO()):
            build.render(script,dest,preview=True,voice=voice)
        return dest


    def test_short_meditation_instruction_is_reported_before_export(self):
        with tempfile.TemporaryDirectory() as folder:
            data=self.scenario();data['scenes'][1]['caption']='Почувствуйте опору под телом';output=io.StringIO()
            with contextlib.redirect_stderr(output):dest=self.mock_export(Path(folder),data=data)
            self.assertIn('подсказк',output.getvalue().lower())
            self.assertTrue(json.loads(dest.with_suffix('.render.json').read_text()).get('warnings'))

    def test_normal_meditation_instruction_does_not_warn_about_intro_or_outro(self):
        with tempfile.TemporaryDirectory() as folder:
            data=self.scenario();data['target_duration_seconds']=44;data['scenes'][0]['caption']='Короткое интро';data['scenes'][1].update(duration_seconds=40,caption='Почувствуйте опору');data['scenes'][-1]['caption']='Короткое аутро';output=io.StringIO()
            with contextlib.redirect_stderr(output):dest=self.mock_export(Path(folder),data=data)
            self.assertNotIn('подсказк',output.getvalue().lower())

    def test_default_build_uses_current_recording_and_credits(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[];dest=self.mock_export(Path(folder),commands=calls)
            self.assertFalse(any('make_ambient.py' in ' '.join(c) for c in calls),'Отвергнутый pad не должен запускаться штатной сборкой')
            meta=json.loads(dest.with_suffix('.render.json').read_text())
            self.assertEqual(meta.get('music_source',{}).get('asset_id'),'music-tranquility')
            credits=dest.with_suffix('.credits.txt').read_text()
            self.assertIn('Tranquility',credits);self.assertNotIn('original sustained local MIDI pad',credits)

    def test_unknown_music_asset_stops_before_binary_or_synthesis(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scenario.json';data=self.scenario();data['music_asset_id']='not-a-registered-track';path.write_text(json.dumps(data))
            with patch.object(build,'require_binary',side_effect=AssertionError('Музыка не проверена до внешней работы')):
                with self.assertRaisesRegex(RuntimeError,'музык|music'):build.render(path,Path(folder)/'out.mp4',preview=True)

    def test_music_asset_cannot_be_silently_ignored_when_music_off(self):
        data=self.scenario();data.update(type='lesson',target_duration_seconds=60,music=False,music_asset_id='music-tranquility');data['scenes'][1].update(duration_seconds=56,narration='Текст')
        with self.assertRaisesRegex(RuntimeError,'music'):validate_scenario(data,'review',build.STYLE)

    def test_mocked_export_commits_all_companions_and_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            dest=self.mock_export(Path(folder));self.assertEqual(dest.read_bytes(),b'complete mocked mux')
            for ext in ['.srt','.credits.txt','.rights.txt','.render.json','.mix.wav','.mix.speech.wav','.mix.music.wav','.mix.audio.json']:self.assertTrue(dest.with_suffix(ext).exists(),ext)
            self.assertEqual(file_integrity_errors(dest,json.loads(dest.with_suffix('.render.json').read_text())),[])
            self.assertTrue(list((dest.parent/'.freelearn-cache').glob('export-*/previous/video.mp4')))

    def test_mocked_mux_failure_preserves_old_export_and_mix(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            with self.assertRaisesRegex(RuntimeError,'mux failure'):self.mock_export(folder,True)
            self.assertEqual((folder/'video.mp4').read_bytes(),b'old video');self.assertEqual((folder/'video.mix.wav').read_bytes(),b'old mix')
            self.assertFalse((folder/'video.render.json').exists())

    def test_caption_updates_do_not_hide_restart_of_reused_nature(self):
        first={'kind':'nature','asset_id':'nature-1','_scene_index':1,'caption':'A'}
        cue=dict(first,caption='B');following=dict(first,_scene_index=2)
        self.assertEqual(build.scene_shot_key(first),build.scene_shot_key(cue))
        self.assertNotEqual(build.scene_shot_key(first),build.scene_shot_key(following))
        self.assertNotEqual(build.scene_shot_key(first),build.scene_shot_key(dict(first,image_crop=[.2,0,1,1])))

    def test_asr_metadata_rejects_bool_strings_and_wrong_containers(self):
        for meta in [[],{'duration_seconds':'3','caption_events':[]},{'duration_seconds':True,'caption_events':[]},{'duration_seconds':3,'caption_events':[None]},{'duration_seconds':3,'caption_events':[{'start':True,'end':2,'text':'Текст'}]}]:
            with self.subTest(meta=meta),self.assertRaises((RuntimeError,ValueError)):speech_events(meta)

    def test_prompt_after_audio_end_is_rejected_not_inverted(self):
        with self.assertRaises(RuntimeError):merge_prompt_intervals([[6.0002,6.0005]],6)
        with self.assertRaises((RuntimeError,ValueError)):speech_events({'duration_seconds':6,'caption_events':[{'start':6.0002,'end':6.0005,'text':'Текст'}]})
        self.assertTrue(review_metadata_errors({'caption_events':[{'start':6.0002,'end':6.0005,'text':'Текст'}]},6))

    def test_huge_metadata_times_fail_as_input_errors(self):
        self.assertTrue(review_metadata_errors({'scene_boundaries':[10**1000]},6))
        self.assertTrue(review_metadata_errors({'display_events':[{'start':10**1000,'duration':1}]},6))

    def test_random_caption_partitions_keep_total_duration(self):
        import random
        rng=random.Random(28)
        for _ in range(400):
            knots=sorted(rng.random()*20 for _ in range(12));cues=[(knots[i],knots[i+1],str(i)) for i in range(0,12,2)]
            result=build.split_caption_events([{'kind':'nature','caption':'Начало'}],[0],[20],cues)
            self.assertAlmostEqual(sum(duration for _,duration in result),20)

    def test_uppercase_mp4_is_committed_last(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);src=folder/'src';dst=folder/'dst';src.mkdir();dst.mkdir();pairs=[]
            for name in ['result.MP4','result.srt']:
                (src/name).write_bytes(b'new');pairs.append((src/name,dst/name))
            replace=os.replace;written=[]
            def track(a,b):written.append(Path(b).name);return replace(a,b)
            with patch('export_files.os.replace',side_effect=track):commit_bundle(pairs)
            self.assertEqual(written[-1],'result.MP4')

    def test_ignored_media_fields_fail_early(self):
        data=self.scenario();data['scenes'][0]['asset_id']='nature-1'
        with self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)
        data=self.scenario();data['scenes'][1]['video_offset_seconds']=1
        with self.assertRaises(RuntimeError):validate_scenario(data,'review',build.STYLE)

    def test_asr_mismatched_hash_does_not_reach_recognizer(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);video=folder/'fixture.mp4';video.write_bytes(b'fixture');report=folder/'report.json'
            video.with_suffix('.render.json').write_text(json.dumps({'duration_seconds':3,'video_sha256':'0'*64,'caption_events':[{'start':1,'end':2,'text':'Текст'}]}))
            with patch.object(sys,'argv',['check_speech.py',str(video),'--output',str(report)]):self.assertEqual(check_speech.main(),1)
            self.assertFalse(json.loads(report.read_text())['all_exact_words'])

    def test_render_metadata_frame_count_cannot_disagree(self):
        v,a,meta=self.streams();meta['frame_count']=999
        self.assertTrue(stream_errors(v,a,90,meta,'16:9',False))
        meta['frame_count']=2700;meta['fps']=24
        self.assertTrue(stream_errors(v,a,90,meta,'16:9',False))

    def test_silent_approved_mode_does_not_claim_an_approved_voice(self):
        with patch.dict(build.STYLE['voice'],approved_for_publication=False):
            build.prepare_speech([{'kind':'intro'}],'approved',Path('/unused'),0)
            with tempfile.TemporaryDirectory() as folder:
                dest=self.mock_export(Path(folder),voice='approved')
                self.assertFalse(json.loads(dest.with_suffix('.render.json').read_text())['voice_approved'])

    def test_recorded_music_does_not_require_legacy_surge_binary(self):
        original=Path.exists
        def exists(path):return False if path.name=='Surge XT.vst3' else original(path)
        def process(command,**kwargs):
            return SimpleNamespace(returncode=0,stdout='{}' if '-c' in command else 'fixture version',stderr='')
        with patch.object(sys,'argv',['doctor.py']),patch.object(Path,'exists',exists),patch('subprocess.run',side_effect=process),contextlib.redirect_stdout(io.StringIO()) as output:
            code=doctor.main()
        self.assertEqual(code,0,output.getvalue())

    def test_doctor_interruption_does_not_leave_old_success(self):
        with tempfile.TemporaryDirectory() as folder:
            report=Path(folder)/'doctor.json';report.write_text('{"errors":[]}')
            with patch.object(sys,'argv',['doctor.py','--output',str(report)]),self.assertRaises(AssertionError):doctor.main()
            data=json.loads(report.read_text());self.assertEqual(data['status'],'incomplete');self.assertTrue(data['errors'])


if __name__=='__main__':unittest.main(verbosity=2)

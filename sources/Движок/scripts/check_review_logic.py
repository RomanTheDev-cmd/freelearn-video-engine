#!/usr/bin/env python3
"""Review report regressions; external decoders are mocked, no media is rendered."""
import contextlib,hashlib,io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.dont_write_bytecode=True
import check_video as review


class ReviewChecks(unittest.TestCase):
    def metadata(self):
        return {'duration_seconds':3,'fps':30,'frame_count':90,'format':'16:9','preview':False,
                'scene_boundaries':[0,1],
                'display_events':[{'start':0,'duration':1,'caption':''},{'start':1,'duration':2,'caption':'Пауза'}],
                'caption_events':[],'video_sha256':hashlib.sha256(b'original encoded fixture').hexdigest()}

    def run_cli(self,meta=None,flags=(),sidecars=None,change_video=False,audio_summary=None):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);video=root/'review.mp4';report=root/'report.json'
            video.write_bytes(b'original encoded fixture')
            video.with_suffix('.render.json').write_text(json.dumps(self.metadata() if meta is None else meta))
            values={'.srt':'','.credits.txt':'Recorded source and author','.rights.txt':'Recorded license terms'}
            values.update(sidecars or {})
            for suffix,text in values.items():video.with_suffix(suffix).write_text(text)
            streams=[{'codec_type':'video','codec_name':'h264','width':1920,'height':1080,'avg_frame_rate':'30/1','duration':'3','nb_frames':'90'},
                     {'codec_type':'audio','codec_name':'aac','sample_rate':'48000','channels':2,'duration':'3'}]
            if '--preview' in flags:streams[0].update(width=960,height=540,avg_frame_rate='15/1',nb_frames='45')
            calls=[]
            def external(command):
                calls.append(command)
                if str(command[0])=='ffprobe':return SimpleNamespace(returncode=0,stdout=json.dumps({'streams':streams,'format':{'duration':'3'}}).encode(),stderr=b'')
                if 'ebur128=peak=true' in command:
                    if change_video:video.write_bytes(b'replaced during scan')
                    return SimpleNamespace(returncode=0,stdout=b'',stderr=(b'Summary:\n I: -29.0 LUFS\n Peak: -12.0 dBFS\n' if audio_summary is None else audio_summary))
                return SimpleNamespace(returncode=1,stdout=b'',stderr=b'frame decoder deliberately mocked')
            with patch.object(sys,'argv',['check_video.py',str(video),'--output',str(report),*flags]),patch.object(review,'call',side_effect=external),contextlib.redirect_stdout(io.StringIO()):
                result=review.main()
            return result,json.loads(report.read_text()),calls

    def test_intentional_silent_preview_has_explicit_measurement_status(self):
        meta=self.metadata();meta.update(preview=True,fps=15,frame_count=45,music_enabled=False,music_source=None)
        for summary in [b'Summary: I: -inf LUFS Peak: -inf dBFS',b'Summary: I: -70.0 LUFS Peak: -inf dBFS']:
            with self.subTest(summary=summary):
                _,report,_=self.run_cli(meta,flags=['--preview'],audio_summary=summary)
                self.assertEqual(report['audio_scan'].get('measurement_status'),'intentional_silence')
                self.assertFalse(any('уровн' in error for error in report['errors']))
                self.assertTrue(any('тишин' in warning for warning in report['warnings']))

    def test_unknown_audio_measurements_are_not_a_successful_scan(self):
        for log in [b'unrecognized tool output',b'Summary: I: -inf LUFS Peak: -inf dBFS']:
            with self.subTest(log=log):
                _,report,_=self.run_cli(audio_summary=log)
                self.assertTrue(any('уровн' in error for error in report['errors']))

    def test_strict_cli_rejects_missing_review_contract_before_scans(self):
        result,report,calls=self.run_cli({})
        self.assertEqual(result,1)
        self.assertEqual(len(calls),1,'Incomplete metadata must fail before any frame/audio scan')
        self.assertTrue(any('duration_seconds' in error for error in report['errors']))

    def test_empty_credits_and_rights_fail_before_scans(self):
        for suffix in ['.credits.txt','.rights.txt']:
            with self.subTest(suffix=suffix):
                _,report,calls=self.run_cli(sidecars={suffix:'   '})
                self.assertEqual(len(calls),1)
                self.assertTrue(any(suffix in error for error in report['errors']))

    def test_spoken_export_requires_nonempty_srt(self):
        meta=self.metadata();meta['caption_events']=[{'start':1,'end':2,'text':'Почувствуйте опору.'}]
        _,report,calls=self.run_cli(meta)
        self.assertEqual(len(calls),1)
        self.assertTrue(any('SRT' in error for error in report['errors']))

    def test_silent_srt_is_allowed_and_completed_report_is_bound(self):
        _,report,calls=self.run_cli()
        self.assertGreater(len(calls),1)
        self.assertEqual(report.get('status'),'complete')
        self.assertEqual(report.get('video_sha256'),hashlib.sha256(b'original encoded fixture').hexdigest())
        self.assertEqual(report.get('checker_sha256'),hashlib.sha256(Path(review.__file__).read_bytes()).hexdigest())
        self.assertEqual(report.get('binding_status'),'unchanged')
        self.assertFalse(any('SRT' in error for error in report['errors']))

    def test_video_changed_during_scans_cannot_leave_completed_report(self):
        result,report,_=self.run_cli(change_video=True)
        self.assertEqual(result,1)
        self.assertEqual(report.get('status'),'incomplete')
        self.assertEqual(report.get('binding_status'),'changed')
        self.assertTrue(any('изменился' in error for error in report['errors']))

    def test_legacy_is_explicit_and_warns_about_missing_checks(self):
        _,report,calls=self.run_cli({},flags=['--legacy'])
        self.assertGreater(len(calls),1)
        self.assertTrue(any('legacy' in warning.lower() for warning in report['warnings']))
        self.assertTrue(any('display_events' in warning for warning in report['warnings']))
        self.assertEqual(report.get('video_sha256'),hashlib.sha256(b'original encoded fixture').hexdigest())

    def test_strict_rejects_invalid_types_or_missing_fields_without_scans(self):
        for field,value in [('duration_seconds',True),('fps',True),('frame_count',90.0),('format','square'),('preview',1),('scene_boundaries',[]),('display_events',[]),('caption_events',None),('video_sha256',None)]:
            with self.subTest(field=field):
                meta=self.metadata();meta[field]=value
                _,report,calls=self.run_cli(meta)
                self.assertEqual(len(calls),1)
                self.assertTrue(report['errors'])

    def test_partial_metadata_helper_remains_compatible(self):
        self.assertEqual(review.review_metadata_errors({'caption_events':[]},3),[])

    def test_unknown_video_binding_cannot_be_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            report=review.finish_report({'errors':[]},Path(folder)/'missing.mp4',None,'a'*64)
        self.assertEqual(report['status'],'incomplete')
        self.assertEqual(report['binding_status'],'unknown')
        self.assertIsNone(report['video_sha256'])
        self.assertTrue(report['errors'])

    def test_valid_strict_metadata_accepts_pauses_but_rejects_widget_gaps(self):
        meta=self.metadata();meta['caption_events']=[{'start':1.5,'end':2,'text':'Заметьте опору.'}]
        self.assertEqual(review.review_metadata_errors(meta,3,strict=True),[])
        meta['display_events'][1]['start']=1.5;meta['display_events'][1]['duration']=1.5
        self.assertTrue(review.review_metadata_errors(meta,3,strict=True))


if __name__=='__main__':
    with patch.object(subprocess,'run',side_effect=AssertionError('External process forbidden in logic tests')):
        unittest.main(verbosity=2)

"""Cache and poster regressions without rendering a frame or external process."""
import copy,hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
from types import SimpleNamespace
import music_source
import build_video as build
import visuals

class StopAfterKey(Exception):pass
class PosterCall(Exception):pass

class WorkflowChecks(unittest.TestCase):
    def music_fixture(self,folder):
        source=folder/'music.wav';source.write_bytes(b'original recorded audio fixture')
        asset={'id':'recording','file':'music.wav','media_type':'audio','title':'Recording','author':'Composer','source':'https://example.invalid/source','license':'CC BY 4.0','license_url':'https://creativecommons.org/licenses/by/4.0/','attribution':'Composer; changes: segment/fades/ducking','status':'candidate','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        style={'audio':{'music_asset_id':'recording'}}
        return source,asset,style

    def test_registered_recording_selection_and_rights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,asset,style=self.music_fixture(root)
            plan=music_source.select_music({'music':True},style,{'recording':asset},root)
            self.assertEqual(plan['path'],source.resolve());self.assertEqual(plan['sha256'],asset['sha256'])
            self.assertIsNone(music_source.select_music({'music':False},style,{},root))
            for change in [{'status':'rejected'},{'sha256':'0'*64},{'license':''},{'media_type':'video'}]:
                with self.subTest(change=change),self.assertRaises(RuntimeError):music_source.select_music({'music':True},style,{'recording':{**asset,**change}},root)
            source.write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError,'SHA-256'):music_source.select_music({'music':True},style,{'recording':asset},root)

    def test_short_recording_cannot_be_padded_or_looped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,asset,style=self.music_fixture(root);plan=music_source.select_music({'music':True},style,{'recording':asset},root)
            for length,accepted in [(4,False),(6,True),(20,True)]:
                probe=SimpleNamespace(stdout=json.dumps({'streams':[{'duration':str(length)}],'format':{'duration':str(length)}}))
                with patch.object(music_source.subprocess,'run',return_value=probe):
                    if accepted:music_source.validate_duration(plan,6,lambda x:x);self.assertEqual(plan['source_duration_seconds'],length)
                    else:
                        with self.assertRaisesRegex(RuntimeError,'короче'):music_source.validate_duration(plan,6,lambda x:x)
            probe=SimpleNamespace(stdout=json.dumps({'streams':[{'duration':'4'}],'format':{'duration':'12'}}))
            with patch.object(music_source.subprocess,'run',return_value=probe),self.assertRaisesRegex(RuntimeError,'короче'):music_source.validate_duration(plan,6,lambda x:x)
            settings=music_source.segment_settings(6);self.assertEqual(settings['fade_in_seconds'],3);self.assertEqual(settings['fade_out_seconds'],3)

    def test_current_rejected_generator_cannot_be_selected(self):
        with self.assertRaisesRegex(RuntimeError,'отклонён'):music_source.select_music({'music':True,'music_asset_id':'ambient-procedural'},build.STYLE,build.ASSET_MAP,build.ROOT)

    def test_short_video_poster_seeks_inside_selected_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);source=cache/'source.mp4';source.write_bytes(b'fixture')
            assets={'clip':{'file':str(source),'media_type':'video'}}
            for start,end in [(0,.75),(2,2.75)]:
                scene={'kind':'nature','video_asset_id':'clip','video_offset_seconds':start,'video_end_seconds':end}
                captured=[]
                def capture(command):captured.append(command);raise PosterCall()
                with patch.object(visuals.Image,'new'),patch.object(visuals.ImageDraw,'Draw'),self.assertRaises(PosterCall):
                    visuals.make_slide(scene,'16:9',cache,build.STYLE,build.ROOT,assets,capture,lambda x:x)
                args=captured[0];seek=float(args[args.index('-ss')+1]);self.assertGreaterEqual(seek,start);self.assertLess(seek,end)

    def test_changed_source_with_same_stat_cannot_reuse_slide(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp);source=cache/'fixture.jpg';source.write_bytes(b'AAAA');stat=source.stat()
            assets={'photo':{'file':str(source)}};scene={'kind':'nature','asset_id':'photo'};keys=[];original=visuals.key_for
            def capture(data):
                value=original(data);keys.append(value);return value
            with patch.object(visuals,'key_for',side_effect=capture),patch.object(visuals.Image,'new',side_effect=StopAfterKey):
                with self.assertRaises(StopAfterKey):visuals.make_slide(scene,'16:9',cache,build.STYLE,build.ROOT,assets,None,None)
                (cache/f'slide-{keys[-1]}.png').write_bytes(b'cached fixture, never decoded')
                source.write_bytes(b'BBBB');os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                with self.assertRaises(StopAfterKey):visuals.make_slide(scene,'16:9',cache,build.STYLE,build.ROOT,assets,None,None)
            self.assertNotEqual(keys[0],keys[-1])

    def test_slide_key_contains_renderer_and_font_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            captured=[];original=visuals.key_for
            def capture(data):captured.append(data);return original(data)
            with patch.object(visuals,'key_for',side_effect=capture),patch.object(visuals.Image,'new',side_effect=StopAfterKey):
                with self.assertRaises(StopAfterKey):visuals.make_slide({'kind':'intro'},'16:9',Path(tmp),build.STYLE,build.ROOT,{},None,None)
            self.assertEqual(captured[0].get('renderer'),hashlib.sha256(Path(visuals.__file__).read_bytes()).hexdigest())
            self.assertEqual(captured[0].get('font_sha256'),hashlib.sha256((build.ROOT/build.STYLE['font']).read_bytes()).hexdigest())

if __name__=='__main__':unittest.main(verbosity=2)

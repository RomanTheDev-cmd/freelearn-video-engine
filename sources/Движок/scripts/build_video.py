#!/usr/bin/env python3
"""Render a structured Freelearn JSON script to an MP4 using local tools."""
import argparse
from contextlib import nullcontext
import time
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import wave
from array import array
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

# Keep generated Python bytecode out of the shared iCloud source.
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

from visuals import geometry, make_slide as component_slide, make_media_overlay
from scenario import validate_scenario, number,scenario_warnings
from export_files import commit_bundle,validate_output_paths
from pcm_cache import validate_pcm
from music_source import select_music,validate_duration as validate_music_duration,prepare_music,metadata as music_metadata

ROOT = Path(__file__).resolve().parents[1]
# The skill source is shared through iCloud; Python environments stay local to this Mac.
RUNTIME = Path(os.environ.get("FREELEARN_VIDEO_RUNTIME", Path.home() / ".local/share/freelearn-video")).expanduser()
STYLE = json.loads((ROOT / "assets/style.json").read_text())
DEFAULT_THEME = STYLE.get("theme", "light")
REGISTRY = json.loads((ROOT / "assets/credits.json").read_text())
ASSET_MAP = {item["id"]: item for item in REGISTRY["assets"]}


def run(args):
    subprocess.run([str(x) for x in args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def require_binary(name):
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Не найдена программа {name}. См. references/workflow.md")
    return found


def source_duration(path):
    # A readable MP4 header does not prove that every advertised frame was downloaded.
    result=subprocess.run([require_binary('ffprobe'),'-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=duration,nb_frames,nb_read_frames,avg_frame_rate:format=duration','-of','json',str(path)],check=True,capture_output=True,text=True)
    info=json.loads(result.stdout);stream=info['streams'][0]
    duration=float(stream.get('duration',info['format']['duration']))
    actual=int(stream.get('nb_read_frames',0))
    declared=stream.get('nb_frames','')
    expected=int(declared) if str(declared).isdigit() else round(duration*float(Fraction(stream['avg_frame_rate'])))
    if result.stderr.strip() or actual<=0 or abs(actual-expected)>1:
        raise RuntimeError(f'Повреждённый или неполный исходник {path.name}: декодировано {actual} кадров, ожидалось {expected}. {result.stderr[-250:]}')
    return duration


def wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_slide(scene, fmt, cache):
    return component_slide(scene, fmt, cache, STYLE, ROOT, ASSET_MAP, run, require_binary)


@lru_cache(maxsize=4)
def model_fingerprint(model_path):
    folder=Path(model_path).expanduser()
    files=sorted(p for p in folder.rglob('*') if p.is_file() and '.cache' not in p.relative_to(folder).parts and p.suffix in ('.json','.safetensors','.txt')) if folder.is_dir() else [folder]
    if not files: raise RuntimeError('Нет локальных файлов модели')
    records={}
    for path in files:
        with path.open('rb') as stream: records[str(path.relative_to(folder) if folder.is_dir() else path.name)]=hashlib.file_digest(stream,'sha256').hexdigest()
    return records


def reference_fingerprint(voice):
    if not voice.get('reference_profile'):return None,None
    profile_path=ROOT/voice['reference_profile'];profile=json.loads(profile_path.read_text())
    reference=profile_path.parent/profile['audio_file']
    audio_hash=hashlib.sha256(reference.read_bytes()).hexdigest()
    if profile.get('synthetic') is not True or profile.get('recording_of_person') is not False or audio_hash!=profile.get('sha256'):
        raise RuntimeError('Не подтверждены происхождение или целостность синтетического голосового образца')
    return hashlib.sha256(profile_path.read_bytes()).hexdigest(),audio_hash


def speech_path(text,voice_key,cache):
    voice=STYLE['voice']
    model=voice.get('approved_model_path')
    adapter=ROOT/'scripts/build_video.py'
    profile_hash,reference_hash=reference_fingerprint(voice)
    key=digest({'text':text,'mode':voice_key,'voice':voice,'model_content':model_fingerprint(model) if model and voice_key!='espeak-ng' else None,'adapter_sha256':hashlib.sha256(adapter.read_bytes()).hexdigest(),'tts_filter_plan_sha256':hashlib.sha256((ROOT/'scripts/audio_plan.py').read_bytes()).hexdigest(),'profile_sha256':profile_hash,'reference_audio_sha256':reference_hash,'timeline_rate':24000})
    return cache/f'speech-{key}.wav'


def speech_command(output):
    voice=STYLE['voice']
    if not voice.get('approved_command'):raise RuntimeError('Локальный синтезатор отключён: прежняя модель удалена; используйте сохранённый WAV или отдельный выбранный Tera-процесс')
    command=[str(part).format(model=voice['approved_model_path'],voice=voice['approved_voice_id'],output=str(output),skill=str(ROOT),python312=str(RUNTIME/'.venv312/bin/python'),pythontts=str(RUNTIME/'.venv-tts-comparison/bin/python'),length=voice.get('length_scale',1.0),instruct=voice.get('instruct','')) for part in voice['approved_command']]
    if voice.get('reference_profile'):command+=['--reference-profile',str(ROOT/voice['reference_profile'])]
    return command


def validate_cached_speech(path):
    return validate_pcm(path,24000,1,2)


def synthesize(text,voice_key,work,cache):
    if voice_key=='approved' and STYLE['voice'].get('approved_for_publication') is not True:
        raise RuntimeError('Голос не одобрен')
    path=speech_path(text,voice_key,cache)
    if validate_cached_speech(path):return path
    voice=STYLE['voice']
    if voice_key=='espeak-ng':
        raw=cache/(path.stem+'-native.wav')
        run([require_binary('espeak-ng'),'-v',voice['fallback_voice'],'-s',voice['fallback_rate_wpm'],'-p',voice['fallback_pitch'],'-w',raw,text])
        run([require_binary('ffmpeg'),'-y','-i',raw,'-ar','24000','-ac','1','-c:a','pcm_s16le',path])
    else:
        if voice_key=='approved' and voice.get('approved_for_publication') is not True:raise RuntimeError('Голос не одобрен')
        subprocess.run(speech_command(path),input=text,text=True,check=True,capture_output=True)
    if not validate_cached_speech(path):raise RuntimeError('Синтезатор не создал WAV')
    return path


def prepare_speech(scenes,voice_key,cache,sentence_pause):
    if voice_key not in ('review','approved') or not any(s.get('narration','').strip() for s in scenes):return
    if voice_key=='approved' and STYLE['voice'].get('approved_for_publication') is not True:raise RuntimeError('Голос не одобрен')
    jobs={}
    for scene in scenes:
        text=scene.get('narration','').strip()
        pause=max(0,float(scene.get('narration_pause_seconds',sentence_pause)))
        pieces=[x.strip() for x in re.split(r'(?<=[.!?…])\s+',text) if x.strip()] if pause else ([text] if text else [])
        for piece in pieces:
            path=speech_path(piece,voice_key,cache)
            if not validate_cached_speech(path):jobs[str(path)]={'text':piece,'output':str(path)}
    if jobs:
        batch=cache/f'speech-batch-{digest(list(jobs.values()))}.json'
        batch.write_text(json.dumps(list(jobs.values()),ensure_ascii=False))
        command=speech_command(cache/'unused.wav')
        # No model-specific fallback: an absent backend fails explicitly in speech_command.
        for job in jobs.values():
            subprocess.run(speech_command(Path(job['output'])),input=job['text'],text=True,check=True,capture_output=True)


def check_cached_narration_fit(scenes,starts,durations,voice_key,cache,sentence_pause_seconds):
    """Reject already provable overflow before generating any missing utterance."""
    for i,scene in enumerate(scenes):
        text=scene.get('narration','').strip()
        if not text:continue
        pause=max(0,float(scene.get('narration_pause_seconds',sentence_pause_seconds)))
        pieces=[x.strip() for x in re.split(r'(?<=[.!?…])\s+',text) if x.strip()] if pause else [text]
        lead=float(scene.get('narration_lead_seconds',.2 if scene['kind']=='intro' else .4))
        known=lead+pause*max(0,len(pieces)-1)
        for piece in pieces:
            path=speech_path(piece,voice_key,cache)
            if validate_cached_speech(path):
                with wave.open(str(path),'rb') as stream:known+=stream.getnframes()/stream.getframerate()
        if known>durations[i]-.2:
            raise RuntimeError(f'Озвучка сцены {i+1} с паузами не помещается в её интервал. Сократите текст или увеличьте сцену.')


def make_narration(scenes, starts, durations, output, voice_key, cache, sentence_pause_seconds=0):
    rate, total = 24000, round(sum(durations) * 24000)
    check_cached_narration_fit(scenes,starts,durations,voice_key,cache,sentence_pause_seconds)
    prepare_speech(scenes,voice_key,cache,sentence_pause_seconds)
    result = array("h", [0]) * total
    subtitles=[]
    for i, scene in enumerate(scenes):
        text = scene.get("narration", "").strip()
        if not text:
            continue
        pause = max(0, float(scene.get("narration_pause_seconds", sentence_pause_seconds)))
        pieces = [x.strip() for x in re.split(r'(?<=[.!?…])\s+', text) if x.strip()] if pause else [text]
        lead = float(scene.get("narration_lead_seconds", 0.2 if scene["kind"] == "intro" else 0.4))
        cursor = starts[i] + lead
        for n, piece in enumerate(pieces):
            wavpath = synthesize(piece, voice_key, output.parent, cache)
            with wave.open(str(wavpath), "rb") as stream:
                if stream.getframerate() != rate or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                    raise RuntimeError("Неожиданный формат WAV от локального синтезатора")
                audio = array("h")
                audio.frombytes(stream.readframes(stream.getnframes()))
            if sys.byteorder != "little": audio.byteswap()
            spoken_length = len(audio) / rate
            if cursor + spoken_length > starts[i] + durations[i] - 0.2:
                raise RuntimeError(f"Озвучка сцены {i+1} с паузами не помещается в её интервал. Сократите текст или увеличьте сцену.")
            start = round(cursor * rate)
            result[start:start+len(audio)] = audio
            caption_pieces = [piece] if pause else [x.strip() for x in re.split(r'(?<=[.!?…])\s+', piece) if x.strip()]
            captions=[]
            for caption_piece in caption_pieces:
                lines=textwrap.wrap(caption_piece,width=54,break_long_words=False,break_on_hyphens=False) or [caption_piece]
                captions.extend("\n".join(lines[j:j+2]) for j in range(0,len(lines),2))
            weights=[max(1,len(re.findall(r"\w+",caption))) for caption in captions]
            total_words=sum(weights); elapsed=0.0
            for caption,weight in zip(captions,weights):
                duration=spoken_length*weight/total_words
                subtitles.append((cursor+elapsed,cursor+elapsed+duration,caption))
                elapsed+=duration
            cursor += spoken_length + (pause if n < len(pieces)-1 else 0)
    with wave.open(str(output), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(result.tobytes())
    return subtitles


def write_srt(entries,path):
    def stamp(ms):
        hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);secs,ms=divmod(ms,1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
    blocks=[];previous_end=0
    for i,(start,end,text) in enumerate(entries,1):
        if not all(math.isfinite(t) for t in (start,end)) or not 0<=start<end:
            raise RuntimeError('Некорректный интервал SRT')
        begin_ms,end_ms=round(start*1000),round(end*1000)
        if begin_ms<previous_end or end_ms<=begin_ms:
            raise RuntimeError('Интервалы SRT пересекаются или короче точности 1 мс')
        blocks.append(f"{i}\n{stamp(begin_ms)} --> {stamp(end_ms)}\n{text}\n");previous_end=end_ms
    path.write_text("\n".join(blocks),encoding='utf-8')


def split_caption_events(scenes, starts, durations, subtitles):
    """Preserve every interval; keep the last spoken instruction until the next cue."""
    by_start={i:[] for i in range(len(scenes))}
    for entry in subtitles:
        midpoint=(entry[0]+entry[1])/2
        idx=next((i for i,(start,dur) in enumerate(zip(starts,durations)) if start<=midpoint<start+dur),None)
        if idx is not None: by_start[idx].append(entry)
    out=[]
    for i,(scene,start,duration) in enumerate(zip(scenes,starts,durations)):
        entries=sorted(by_start[i])
        cursor=start
        previous_caption=None
        for begin,end,text in entries:
            begin=max(start,begin);end=min(start+duration,end)
            if begin>cursor:
                prompt=dict(scene);prompt.pop("narration",None)
                if previous_caption is not None: prompt['caption']=previous_caption
                prompt["_video_offset_seconds"]=float(scene.get("video_offset_seconds",0))+(cursor-start)*float(scene.get('_video_speed',1))
                out.append((prompt,begin-cursor))
            if end>begin:
                spoken=dict(scene);spoken["caption"]=text;spoken.pop("narration",None)
                spoken["_video_offset_seconds"]=float(scene.get("video_offset_seconds",0))+(begin-start)*float(scene.get('_video_speed',1))
                out.append((spoken,end-begin))
            cursor=max(cursor,end)
            previous_caption=text
        if cursor<start+duration:
            prompt=dict(scene);prompt.pop("narration",None)
            if previous_caption is not None:prompt['caption']=previous_caption
            prompt["_video_offset_seconds"]=float(scene.get("video_offset_seconds",0))+(cursor-start)*float(scene.get('_video_speed',1))
            out.append((prompt,start+duration-cursor))
    return out


def make_display_plan(scenes,starts,durations,subtitles,mode):
    if mode=='speech':return split_caption_events(scenes,starts,durations,subtitles)
    if mode!='stage':raise RuntimeError('Неизвестный caption_mode')
    result=[]
    for scene,duration in zip(scenes,durations):
        display=dict(scene);display.pop('narration',None)
        display['_video_offset_seconds']=float(scene.get('video_offset_seconds',0))
        result.append((display,duration))
    return result


def resolve_music(data):
    music=data.get('music',data.get('type')=='meditation')
    if not isinstance(music,bool):raise RuntimeError('music должен быть true или false')
    if data.get('type')=='meditation' and not music:raise RuntimeError('Для медитации ambient обязателен')
    return music


def validate_source_interval(start,end,length):
    if not all(math.isfinite(x) for x in (start,end,length)) or start<0 or end>length+.001 or end<=start:
        raise RuntimeError(f'Некорректный диапазон видео: {start}–{end} с')
    available=end-start-.25
    if available<=0:raise RuntimeError('Видео не имеет запаса в выбранном диапазоне')
    return available


def choose_theme(data,override=None):
    chosen=override if override is not None else data.get('theme',DEFAULT_THEME)
    if chosen not in STYLE.get('themes',{}):raise RuntimeError('theme должен быть light или dark')
    return chosen


def scene_shot_key(scene):
    if scene.get('kind')=='card':return ('card',scene.get('title'),tuple(scene.get('points',[])))
    media=scene.get('video_asset_id') or scene.get('asset_id') or scene.get('kind')
    if scene.get('kind')=='nature':return ('nature',media,scene.get('_scene_index'),tuple(scene.get('image_crop',[])))
    return media


def dissolve_duration(groups,fps,requested):
    """Fit a positive, frame-aligned dissolve inside every participating shot."""
    fps=number(fps,'fps',positive=True)
    if not fps.is_integer():raise RuntimeError('fps должен быть целым')
    requested=number(requested,'transition_seconds',positive=True)
    frames=[math.floor(number(group['duration'],'shot duration',positive=True)*fps+1e-6) for group in groups]
    if not frames or min(frames)<1:raise RuntimeError('Для перехода нужен хотя бы один кадр в каждой сцене')
    return min(max(1,round(min(.9,requested)*fps)),min(frames))/fps


def render(script_path, dest, preview=False, voice="review", theme=None):
    data=validate_scenario(json.loads(script_path.read_text()),voice,STYLE,preview)
    quality_warnings=scenario_warnings(data)
    for warning in quality_warnings:print("ПРЕДУПРЕЖДЕНИЕ: "+warning,file=sys.stderr)
    music_plan=select_music(data,STYLE,ASSET_MAP,ROOT)
    chosen_theme=choose_theme(data,theme)
    inputs=[script_path,ROOT/'assets/style.json',ROOT/'assets/credits.json']
    inputs.extend(ROOT/record['file'] for record in ASSET_MAP.values() if record.get('file'))
    validate_output_paths(dest,inputs)
    ffmpeg=require_binary('ffmpeg')
    model_fingerprint.cache_clear()
    STYLE['theme']=chosen_theme;STYLE['colors']=dict(STYLE['themes'][chosen_theme])
    scenes=data['scenes'];durations=[float(s['duration_seconds']) for s in scenes]
    target=float(data['target_duration_seconds'])
    if voice == "espeak-ng":
        print("ПРЕДУПРЕЖДЕНИЕ: это технический прогон формантного синтезатора, не утверждённая neural voice.", file=sys.stderr)
    total_dur = target
    if preview:
        total_dur = min(target, 24.0)
        if total_dur < 5:
            raise RuntimeError("Сценарий слишком короткий для предпросмотра")
    validate_music_duration(music_plan,total_dur,require_binary)
    selected, clipped, consumed = [], [], 0.0
    source_lengths={}
    for scene_index,(scene,dur) in enumerate(zip(scenes,durations)):
        if consumed >= total_dur: break
        use = min(dur, total_dur-consumed)
        planned=dict(scene);planned['_scene_index']=scene_index
        asset_id=scene.get('video_asset_id')
        if asset_id:
            record=ASSET_MAP.get(asset_id)
            if not record or record.get('media_type')!='video':
                raise RuntimeError(f'Некорректный video_asset_id: {asset_id}')
            source=ROOT/record['file']
            if not source.is_file(): raise RuntimeError(f'Не найден видеоисточник: {source}')
            if asset_id not in source_lengths: source_lengths[asset_id]=source_duration(source)
            source_start=float(scene.get('video_offset_seconds',0))
            source_end=float(scene.get('video_end_seconds',source_lengths[asset_id]))
            available=validate_source_interval(source_start,source_end,source_lengths[asset_id])
            # Stretch a single take to the practice interval instead of hard-looping it.
            planned['_video_speed']=min(1.0,available/dur)
        selected.append(planned); clipped.append(use); consumed += use
    starts=[]; acc=0.0
    for d in clipped: starts.append(acc); acc += d
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache = dest.parent / ".freelearn-cache"
    cache.mkdir(exist_ok=True)
    fmt=data.get("format","16:9")
    if fmt not in STYLE["canvas"]: raise RuntimeError("format должен быть 16:9 или 9:16")
    with tempfile.TemporaryDirectory(prefix='freelearn-rights-') as preflight:
        make_credits(selected,Path(preflight)/'credits.txt',data['music'],voice,music_plan['asset'] if music_plan else None)
    for scene in selected:make_slide(scene,fmt,cache)  # Fail on overflow/missing assets before expensive synthesis.
    fps=int(STYLE["fps"])
    width,height=STYLE["canvas"][fmt]
    # Preview scales dimensions and frame rate before encoding to save render time.
    if preview:
        width,height=(960,540) if fmt=="16:9" else (540,960); fps=15
    keep_work=cache/f'work-{time.time_ns()}' if os.environ.get('FREELEARN_VIDEO_KEEP_WORK') else None
    if keep_work:keep_work.mkdir()
    with (nullcontext(str(keep_work)) if keep_work else tempfile.TemporaryDirectory(prefix="freelearn-")) as tmpraw:
        tmp=Path(tmpraw); clips=[]; clip_records=[]
        audio=tmp/'narration.wav'
        sentence_pause=STYLE['voice'].get('meditation_sentence_pause_seconds',0) if data['type']=='meditation' else 0.6
        try:
            subtitle_entries=make_narration(selected,starts,clipped,audio,voice,cache,sentence_pause)
        except RuntimeError as error:
            # A partial preview scene may contain a complete cue; only drop it when actual speech cannot fit.
            partial=preview and clipped[-1]<float(selected[-1]['duration_seconds'])
            if partial and str(error).startswith(f'Озвучка сцены {len(selected)} ') and len(selected)>1:
                selected.pop();clipped.pop();starts.pop();total_dur=sum(clipped)
                if total_dur<5:raise RuntimeError('Первая полная реплика выходит за preview; используйте отдельный короткий сценарий') from error
                subtitle_entries=make_narration(selected,starts,clipped,audio,voice,cache,sentence_pause)
            else:raise
        srt=tmp/'captions.srt';write_srt(subtitle_entries,srt)
        display_scenes=make_display_plan(selected,starts,clipped,subtitle_entries,data['caption_mode'])
        display_durations=[item[1] for item in display_scenes]
        video_time=0.0; video_frames=0
        preset='ultrafast' if preview else 'veryfast'
        for i,(scene,raw_dur) in enumerate(display_scenes):
            video_time+=raw_dur
            end_frame=round(video_time*fps)
            frame_count=end_frame-video_frames
            if frame_count<=0: continue
            video_frames=end_frame
            dur=frame_count/fps
            frame=make_slide(scene,fmt,cache)
            clip=tmp/f"clip-{i:03d}.mp4"
            prior_changed=i==0 or scene_shot_key(display_scenes[i-1][0])!=scene_shot_key(scene)
            next_changed=i==len(display_scenes)-1 or scene_shot_key(display_scenes[i+1][0])!=scene_shot_key(scene)
            if prior_changed:
                print(f"Кадры: {scene.get('title') or scene['kind']}",flush=True)
            transition=float(STYLE["timing"].get("transition_seconds",1.3))
            # Start directly on the image instead of opening on a near-black frame.
            fade_in=min(transition,dur/2) if prior_changed and i>0 else 0
            fade_out=min(transition,dur/2) if next_changed else 0
            if STYLE['timing'].get('transition_mode')=='dissolve':fade_in=fade_out=0
            fade_color=STYLE['colors']['background'].replace('#','0x')
            fade_filters=[]
            if fade_in: fade_filters.append(f"fade=t=in:st=0:d={fade_in:.3f}:color={fade_color}")
            if fade_out: fade_filters.append(f"fade=t=out:st={max(0,dur-fade_out):.3f}:d={fade_out:.3f}:color={fade_color}")
            fade_chain=(","+",".join(fade_filters)) if fade_filters else ""
            video_asset_id=scene.get("video_asset_id")
            mx,my,mr,mb=geometry(width,height)['media']
            media_w,media_h=mr-mx,mb-my
            overlay=make_media_overlay(frame,fmt,cache,STYLE)
            overlay_filter=(f"[1:v]scale={width}:{height},format=rgba[front];"
                            f"[bottom][front]overlay=0:0:shortest=1:format=auto,"
                            f"fps={fps},setpts=N/({fps}*TB),format=rgb24,scale=out_color_matrix=bt709:out_range=tv,setsar=1,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[outv]")
            if video_asset_id:
                rec=ASSET_MAP.get(video_asset_id)
                if not rec or rec.get("media_type")!="video":
                    raise RuntimeError(f"Некорректный video_asset_id: {video_asset_id}")
                source_video=ROOT/rec["file"]
                if not source_video.is_file(): raise RuntimeError(f"Не найден видеоисточник: {source_video}")
                offset=float(scene.get("_video_offset_seconds",scene.get("video_offset_seconds",0)))
                speed=float(scene.get('_video_speed',1))
                brightness='0.0' if chosen_theme=='light' else '-0.02'
                filter_graph=(f"[0:v]setpts=(PTS-STARTPTS)/{speed:.8f},scale={media_w}:{media_h}:force_original_aspect_ratio=increase,"
                              f"crop={media_w}:{media_h},setsar=1,eq=saturation=0.78:brightness={brightness}:contrast=1.0,"
                              f"colorbalance=rs=-0.01:gs=0:bs=0.015,fps={fps},tpad=stop_mode=clone:stop_duration=2,"
                              f"format=yuv420p{fade_chain},pad={width}:{height}:{mx}:{my}:color={fade_color}[bottom];"
                              +overlay_filter)
                inputs=['-ss',f'{offset:.6f}','-i',source_video]
            else:
                sx,sy,sr,sb=geometry(*STYLE['canvas'][fmt])['media']
                motion=(f"zoompan=z=1+0.025*({float(scene.get('_video_offset_seconds',0))}*{fps}+on)/{max(1,round(float(scene['duration_seconds'])*fps))}:x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d=1:s={media_w}x{media_h}:fps={fps}," if scene.get('kind')=='nature' else '')
                # Supersampling reduces integer-crop stepping during very slow zooms.
                supersample=4 if scene.get('kind')=='nature' else 1
                filter_graph=(f"[0:v]crop={sr-sx}:{sb-sy}:{sx}:{sy},scale={media_w*supersample}:{media_h*supersample}:flags=lanczos,"
                              f"{motion}format=yuv420p{fade_chain},pad={width}:{height}:{mx}:{my}:color={fade_color}[bottom];"
                              +overlay_filter)
                inputs=['-loop','1','-framerate',fps,'-i',frame]
            run([ffmpeg,'-y',*inputs,'-loop','1','-framerate',fps,'-i',overlay,
                 '-frames:v',frame_count,'-filter_complex',filter_graph,'-map','[outv]',
                 '-an','-c:v','libx264','-preset',preset,'-crf','27' if preview else '20',
                 '-r',fps,'-pix_fmt','yuv420p',clip])
            probe=subprocess.run([require_binary('ffprobe'),'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,duration','-of','json',str(clip)],check=True,capture_output=True,text=True)
            stream=json.loads(probe.stdout)['streams'][0]
            actual_frames=int(stream.get('nb_frames',0))
            if actual_frames!=frame_count or abs(float(stream.get('duration',0))-dur)>1/fps+0.001:
                raise RuntimeError(f'Фрагмент {i+1}: получено {actual_frames} кадров/{stream.get("duration")} с, ожидалось {frame_count} кадров/{dur:.3f} с')
            clips.append(clip)
            clip_records.append((clip,dur,scene_shot_key(scene)))
        # Fades stay within each scene interval, so narration and captions retain exact timing.
        concat=tmp/'clips.txt'
        concat.write_text("".join(f"file '{clip.name}'\n" for clip in clips),encoding='utf-8')
        merged=tmp/'video.mp4'
        run([ffmpeg,"-y","-f","concat","-safe","0","-i",concat,"-t",f"{total_dur:.3f}","-c:v","copy","-an",merged])
        probe=subprocess.run([require_binary('ffprobe'),'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,duration','-of','json',str(merged)],check=True,capture_output=True,text=True)
        merged_stream=json.loads(probe.stdout)['streams'][0]
        if int(merged_stream.get('nb_frames',0))!=video_frames or abs(float(merged_stream.get('duration',0))-total_dur)>1/fps+0.001:
            raise RuntimeError(f'Конкатенация изменила таймлайн: {merged_stream.get("nb_frames")} кадров/{merged_stream.get("duration")} с вместо {video_frames} кадров/{total_dur:.3f} с')
        if STYLE['timing'].get('transition_mode')=='dissolve' and len(clip_records)>1:
            groups=[]
            for clip,duration,key in clip_records:
                if groups and groups[-1]['key']==key:
                    groups[-1]['clips'].append(clip);groups[-1]['duration']+=duration
                else:groups.append({'key':key,'clips':[clip],'duration':duration})
            if len(groups)>1:
                inputs=[];filters=[]
                transition=dissolve_duration(groups,fps,STYLE['timing'].get('transition_seconds',.9))
                for i,group in enumerate(groups):
                    listing=tmp/f'shot-{i}.txt';listing.write_text(''.join(f"file '{clip.name}'\n" for clip in group['clips']))
                    path=tmp/f'shot-{i}.mp4';run([ffmpeg,'-y','-f','concat','-safe','0','-i',listing,'-c','copy',path]);inputs+=['-i',path]
                    tail=transition if i<len(groups)-1 else 0
                    filters.append(f'[{i}:v]settb=1/{fps},setpts=N,tpad=stop_mode=clone:stop={round(tail*fps)}[shot{i}]')
                previous='shot0';offset=0
                for i in range(1,len(groups)):
                    offset+=groups[i-1]['duration'];label=f'blend{i}'
                    filters.append(f'[{previous}][shot{i}]xfade=transition=fade:duration={transition}:offset={offset:.8f}[{label}]');previous=label
                # Use original timed widget/footer over the dissolved picture: no doubled text.
                x,y,right,bottom=geometry(width,height)['media'];inputs+=['-i',merged]
                filters.append(f'[{previous}]fps={fps},tpad=stop_mode=clone:stop=2,crop={right-x}:{bottom-y}:{x}:{y}[picture]')
                filters.append(f'[{len(groups)}:v]settb=1/{fps},setpts=N[template]')
                filters.append(f'[template][picture]overlay={x}:{y}:shortest=1,format=yuv420p[out]')
                (cache/'last-dissolve.json').write_text(json.dumps({'inputs':[str(x) for x in inputs],'filters':filters,'groups':[{'duration':g['duration'],'key':g['key']} for g in groups]},ensure_ascii=False,indent=2))
                dissolved=tmp/'dissolved.mp4'
                run([ffmpeg,'-y','-filter_complex_threads','2',*inputs,'-filter_complex',';'.join(filters),'-map','[out]','-frames:v',video_frames,'-an','-c:v','libx264','-preset',preset,'-crf','27' if preview else '20','-r',fps,dissolved])
                stream=json.loads(subprocess.run([require_binary('ffprobe'),'-v','error','-show_streams','-of','json',str(dissolved)],capture_output=True,text=True,check=True).stdout)['streams'][0]
                if int(stream.get('nb_frames',0))!=video_frames:raise RuntimeError(f'Dissolve: {stream.get("nb_frames")} кадров, ожидалось {video_frames}')
                merged=dissolved
        ambient=prepare_music(music_plan,total_dur,cache,run,require_binary) if music_plan else None
        bundle=tmp/'export';bundle.mkdir()
        staged=bundle/dest.name
        final_audio=staged.with_suffix('.mix.wav')
        command=[RUNTIME/'.venv-audio/bin/python',ROOT/'scripts/process_audio.py','--speech',audio,'--output',final_audio,'--style',ROOT/'assets/style.json','--type',data['type']]
        if ambient:command+=['--music',ambient]
        timings=tmp/'speech-timings.json';timings.write_text(json.dumps(subtitle_entries,ensure_ascii=False));command+=['--timings',timings]
        run(command)
        credits=tmp/'credits.txt'
        make_credits(selected,credits,data.get("music",False),voice,music_plan["asset"] if music_plan else None)
        run([ffmpeg,"-y","-i",merged,"-i",final_audio,"-map","0:v:0","-map","1:a:0","-t",f"{total_dur:.3f}","-c:v","copy","-c:a","aac","-b:a","192k","-movflags","+faststart",staged])
        staged.with_suffix('.srt').write_text(srt.read_text(encoding='utf-8'),encoding='utf-8')
        staged.with_suffix('.credits.txt').write_text(credits.read_text())
        rights=tmp/'credits.rights.txt'
        if rights.exists(): staged.with_suffix('.rights.txt').write_text(rights.read_text(encoding='utf-8'),encoding='utf-8')
        meta={"caption_mode":data["caption_mode"],"id":data.get("id"),"duration_seconds":total_dur,"format":fmt,"preview":preview,"theme":chosen_theme,"skill_version":(ROOT/"VERSION").read_text().strip(),"voice_engine":voice,"voice_approved":bool(subtitle_entries) and voice=="approved" and data.get("approved_voice") is True and STYLE["voice"].get("approved_for_publication") is True,"scenes":len(selected),"frame_count":video_frames,"scene_video_speeds":[s.get('_video_speed') for s in selected]}
        if voice in ('approved','review') and any(s.get('narration') for s in selected):
            meta.update({"speaker":STYLE['voice'].get('speaker_name'),"speaker_id":STYLE['voice'].get('approved_voice_id'),"length_scale":STYLE['voice'].get('length_scale',1.0),"russian_stress_marks":STYLE['voice'].get('stress_method','RUAccent'),"review_candidate":voice=='review',"sentence_pause_seconds":sentence_pause,"speech_target_lufs":STYLE["audio"].get(data["type"]+"_speech_lufs"),"music_target_lufs":STYLE["audio"].get(data["type"]+"_music_lufs") if ambient else None})
        meta.update({'audio_settings':dict(STYLE['audio']),'voice_settings':{k:STYLE['voice'][k] for k in ('engine','approved_voice_id','length_scale','meditation_sentence_pause_seconds','checkpoint_repo','checkpoint_revision','adapter_revision','reference_profile','approved_for_publication') if k in STYLE['voice']},'processor_sha256':hashlib.sha256((ROOT/'scripts/process_audio.py').read_bytes()).hexdigest(),'fps':fps,'transition_mode':STYLE['timing'].get('transition_mode','fade'),'audio_sample_rate':48000,'voice_profile':STYLE['voice'].get('reference_profile'),'voice_profile_sha256':hashlib.sha256((ROOT/STYLE['voice']['reference_profile']).read_bytes()).hexdigest() if STYLE['voice'].get('reference_profile') else None,'voice_model_fingerprint':model_fingerprint(STYLE['voice']['approved_model_path']) if subtitle_entries and voice in ('review','approved') else None,'scene_boundaries':starts,'caption_events':[{'start':a,'end':b,'text':t} for a,b,t in subtitle_entries],'display_events':[{'start':sum(display_durations[:i]),'duration':d,'kind':s.get('kind'),'caption':s.get('caption',''),'title':s.get('title','')} for i,(s,d) in enumerate(display_scenes)]})
        meta['type']=data['type'];meta['warnings']=quality_warnings;meta['music_enabled']=music_plan is not None
        meta['music_source']=music_metadata(music_plan,total_dur)
        with staged.open('rb') as stream:meta['video_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
        staged.with_suffix('.render.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n")
        suffixes=['.srt','.credits.txt','.rights.txt','.render.json','.mix.wav','.mix.speech.wav','.mix.music.wav','.mix.audio.json']
        commit_bundle([(staged.with_suffix(ext),dest.with_suffix(ext)) for ext in suffixes]+[(staged,dest)])
    print(f"MP4: {dest}\nСцены: {len(selected)}; длительность: {total_dur:.2f} с; формат: {fmt}; голос: {voice}")


def make_credits(scenes,path,music,voice_key,music_asset=None):
    used=[]
    for scene in scenes:
        aid=scene.get('video_asset_id') or scene.get('asset_id')
        if aid and aid not in used: used.append(aid)
    items=[ASSET_MAP[a] for a in used if a in ASSET_MAP]
    items.append(ASSET_MAP['font-inter'])
    if music:
        if music_asset is None:raise RuntimeError('Не выбран музыкальный источник для credits')
        items.extend([music_asset,ASSET_MAP['pedalboard']])
    elif any(s.get('narration') for s in scenes): items.append(ASSET_MAP['pedalboard'])
    if voice_key=='espeak-ng' and any(s.get('narration') for s in scenes):
        items.append(ASSET_MAP['tts-espeak-ng'])
    elif voice_key in ('approved','review') and any(s.get('narration') for s in scenes):
        aid=STYLE['voice'].get('approved_credit_id')
        if not aid or aid not in ASSET_MAP:
            raise RuntimeError("Добавьте голос с проверенными автором, источником и лицензиями в assets/credits.json и укажите approved_credit_id")
        items.append(ASSET_MAP[aid])
        if aid=='tts-dialogs-ru-vits2' and 'ruaccent' in ASSET_MAP: items.append(ASSET_MAP['ruaccent'])
        for dependency in STYLE['voice'].get('credit_dependencies',[]):
            if dependency not in ASSET_MAP:
                raise RuntimeError(f"Нет лицензионной записи для голосового компонента {dependency}")
            items.append(ASSET_MAP[dependency])
    if any(s.get('kind')=='nature' for s in scenes): pass
    lines=["Источники и лицензии Freelearn Video",""]
    for a in items:
        lines += [f"{a['title']} — {a['author']}",f"Источник: {a['source']}",f"Лицензия: {a['license']} ({a['license_url']})",f"Указание: {a['attribution']}",""]
    if any(s.get('narration') for s in scenes):
        if voice_key=='espeak-ng': lines += ["Технический прогон eSpeak NG: формантный синтез, не утверждённый neural голос Freelearn.",""]
        else: lines += [f"Локальная озвучка: {STYLE['voice'].get('engine')} (см. приложенную лицензионную памятку).",""]
    path.write_text("\n".join(lines))
    if voice_key in ('approved','review') and any(s.get('narration') for s in scenes) and STYLE['voice'].get('approved_credit_id')=='tts-dialogs-ru-vits2':
        license_path=ROOT/'assets'/'licenses'/'dialogs-openrail-license.md'
        if not license_path.is_file():
            raise RuntimeError("Для Dialogs-RU требуется приложить полный текст OpenRAIL и ограничения использования")
        rights=path.with_name(path.stem+'.rights.txt')
        rights.write_text(
            "Ограничения использования голоса Dialogs-RU\n"
            "При распространении этой производной записи передайте получателям приложенную лицензию и потребуйте соблюдать её раздел 2.\n"
            "Полный текст условий приведён ниже. Передавайте эту памятку вместе с производной аудиозаписью.\n\n"
            + license_path.read_text(encoding='utf-8'), encoding='utf-8')
    elif voice_key in ('approved','review') and any(s.get('narration') for s in scenes):
        license_files=STYLE['voice'].get('rights_license_files',[])
        if license_files:
            records=["Происхождение синтетической речи Freelearn\n", f"Модель: {STYLE['voice'].get('engine')}; preset: {STYLE['voice'].get('speaker_name')}.\n"]
            for name in license_files:
                license_path=ROOT/name
                if not license_path.is_file():
                    raise RuntimeError(f"Не найден лицензионный файл: {name}")
                records.append(f"\n{name}\n\n"+license_path.read_text(encoding='utf-8'))
            path.with_name(path.stem+'.rights.txt').write_text("\n".join(records),encoding='utf-8')
    rights = path.with_name(path.stem + '.rights.txt')
    if not rights.is_file():
        rights.write_text('Источники и условия использования материалов Freelearn\n'
                          'Лицензии использованных материалов и ссылки на их условия:\n\n'
                          + '\n'.join(lines), encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('script',type=Path)
    ap.add_argument('-o','--output',type=Path)
    ap.add_argument('--preview',action='store_true')
    ap.add_argument('--theme',choices=['light','dark'],help='Палитра сайта; иначе theme из JSON или светлая по умолчанию')
    ap.add_argument('--voice',choices=['approved','review','espeak-ng'],default='review')
    args=ap.parse_args()
    output=args.output or args.script.with_suffix('.mp4')
    try: render(args.script.resolve(),output.expanduser().absolute(),args.preview,args.voice,args.theme)
    except (RuntimeError,ValueError,KeyError,TypeError,OSError,subprocess.CalledProcessError) as e:
        detail=(e.stderr.decode(errors='replace') if isinstance(e.stderr,bytes) else str(e.stderr))[-1200:] if isinstance(e,subprocess.CalledProcessError) and e.stderr else str(e)
        print(f"Ошибка сборки: {detail}",file=sys.stderr);sys.exit(2)


if __name__=='__main__': main()

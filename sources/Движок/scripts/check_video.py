#!/usr/bin/env python3
"""Check actual encoded video, picture/widget/footer regions and optional OCR."""
import argparse,hashlib,json,math,re,subprocess,sys,tempfile
from pathlib import Path
from io import BytesIO
from fractions import Fraction
from collections import Counter
sys.dont_write_bytecode=True
from PIL import Image,ImageStat,ImageChops
from visuals import geometry,brand
from export_files import validate_report_path,BUNDLE_SUFFIXES
ROOT=Path(__file__).resolve().parents[1]

def call(command):return subprocess.run([str(x) for x in command],capture_output=True,text=False)
def words(text):return re.findall(r'[a-zа-я0-9]+',text.lower().replace('ё','е'))


def caption_matches(expected,recognized):
    wanted,seen=words(expected),words(recognized)
    return bool(wanted) and seen==wanted


def caption_region(width,height):
    x,y,right,bottom=geometry(width,height)['widget']
    # The title occupies the upper third; it cannot substitute for missing caption words.
    return x,round(y+(bottom-y)*.35),right,bottom


def stream_errors(v,a,duration,meta,fmt,preview,expected_seconds=None):
    errors=[]
    dims={('16:9',False):(1920,1080),('9:16',False):(1080,1920),('16:9',True):(960,540),('9:16',True):(540,960)}[(fmt,preview)]
    if (v['width'],v['height'])!=dims:errors.append(f"Размер {v['width']}×{v['height']}, ожидалось {dims}")
    if v['codec_name']!='h264':errors.append('Ожидался H.264')
    fps=float(Fraction(v['avg_frame_rate']));expected_fps=15 if preview else 30
    if abs(fps-expected_fps)>.001:errors.append(f'Частота кадров {fps:g}, ожидалось {expected_fps}')
    expected=expected_seconds if expected_seconds is not None else float(meta.get('duration_seconds',duration))
    if not math.isfinite(expected) or expected<=0:errors.append('Некорректная ожидаемая длительность');return errors
    if 'duration_seconds' in meta:
        planned=float(meta['duration_seconds'])
        if not math.isfinite(planned) or planned<=0 or abs(planned-expected)>.1:errors.append('Ожидаемая длительность расходится с render.json')
    for name,actual in [('контейнер',duration),('видео',float(v.get('duration',duration))),('аудио',float(a.get('duration',duration)) if a else 0)]:
        if not math.isfinite(actual) or abs(actual-expected)>.1:errors.append(f'{name}: длительность {actual}, ожидалось {expected}')
    if v.get('nb_frames') and abs(int(v['nb_frames'])-round(expected*fps))>1:errors.append('Число кадров не соответствует времени')
    if meta.get('fps') is not None and meta['fps']!=fps:errors.append('Частота кадров расходится с render.json')
    if meta.get('frame_count') is not None and v.get('nb_frames') and meta['frame_count']!=int(v['nb_frames']):errors.append('Число кадров расходится с render.json')
    if not a:errors.append('Нет аудио')
    elif a.get('codec_name')!='aac' or int(a.get('sample_rate',0))!=48000 or a.get('channels')!=2:errors.append('Ожидался звук AAC 48000 Hz stereo')
    if meta.get('format',fmt)!=fmt or meta.get('preview',preview)!=preview:errors.append('Формат проверки расходится с render.json')
    return errors


REVIEW_FIELDS=('duration_seconds','fps','frame_count','format','preview','scene_boundaries','display_events','caption_events','video_sha256')


def review_metadata_errors(meta,duration,ocr=False,strict=False):
    if not isinstance(meta,dict):return ['render.json должен быть объектом']
    errors=[]
    def valid_time(value):
        if not isinstance(value,(int,float)) or isinstance(value,bool):return False
        try:return math.isfinite(value)
        except OverflowError:return False
    if strict:
        for field in REVIEW_FIELDS:
            if field not in meta:errors.append('Нет обязательного поля '+field)
        if not valid_time(meta.get('duration_seconds')) or meta.get('duration_seconds',0)<=0:errors.append('Некорректный duration_seconds')
        for field in ('fps','frame_count'):
            if type(meta.get(field)) is not int or meta[field]<=0:errors.append('Некорректный '+field)
        if meta.get('format') not in ('16:9','9:16'):errors.append('Некорректный format')
        if type(meta.get('preview')) is not bool:errors.append('Некорректный preview')
        if not isinstance(meta.get('video_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',meta['video_sha256']):errors.append('Некорректный video_sha256')
    bounds=meta.get('scene_boundaries',[])
    if not isinstance(bounds,list) or any(not valid_time(t) or not 0<=t<duration for t in bounds) or any(a>=b for a,b in zip(bounds,bounds[1:])):
        errors.append('Некорректные границы сцен')
    elif strict and (not bounds or bounds[0]!=0):errors.append('scene_boundaries должны начинаться с нуля')
    for field in ['display_events','caption_events']:
        events=meta.get(field,[])
        if not isinstance(events,list):errors.append('Некорректные '+field);continue
        previous=0;before=len(errors)
        for event in events:
            if not isinstance(event,dict):errors.append('Некорректный '+field);break
            start=event.get('start');end=event.get('end') if field=='caption_events' else (start+event['duration'] if valid_time(start) and valid_time(event.get('duration')) else None)
            if not valid_time(start) or not valid_time(end) or not 0<=start<duration or not start<end<=duration+.001 or start<previous-.000001:
                errors.append('Некорректный таймлайн '+field);break
            if field=='display_events' and abs(start-previous)>.001:errors.append('Пробел в таймлайне виджета');break
            previous=end
            text=event.get('text' if field=='caption_events' else 'caption','')
            if not isinstance(text,str):errors.append('Текст события должен быть строкой');break
            if strict and field=='caption_events' and not text.strip():errors.append('Пустой текст caption_events');break
        if field=='display_events' and len(errors)==before and events and abs(previous-duration)>.001:errors.append('Виджет не покрывает весь ролик')
        if strict and field=='display_events' and not events:errors.append('Нет display_events: покрытие виджета не проверено')
    if ocr and not meta.get('display_events'):errors.append('Нет display_events: запрошенная OCR-проверка невозможна')
    return errors


def sidecar_errors(video,meta):
    errors=[]
    for suffix in ('.credits.txt','.rights.txt'):
        path=video.with_suffix(suffix)
        if path.is_file() and not path.read_text(encoding='utf-8').strip():errors.append('Пустой файл '+suffix)
    srt=video.with_suffix('.srt')
    if isinstance(meta,dict) and meta.get('caption_events') and srt.is_file() and not srt.read_text(encoding='utf-8').strip():errors.append('Пустой SRT при ожидаемой речи')
    return errors


def file_sha256(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def finish_report(report,video,video_hash,checker_hash):
    report.update(video_sha256=video_hash,checker_sha256=checker_hash)
    try:after=file_sha256(video)
    except OSError:after=None
    report['video_sha256_after']=after
    unchanged=video_hash is not None and after==video_hash
    report['binding_status']='unchanged' if unchanged else ('unknown' if video_hash is None or after is None else 'changed')
    report['status']='complete' if unchanged else 'incomplete'
    if not unchanged:report['errors'].append('MP4 изменился во время проверки' if report['binding_status']=='changed' else 'Целостность проверенного MP4 не подтверждена')
    return report


def file_integrity_errors(video,meta):
    expected=meta.get('video_sha256')
    if expected is None:return []
    if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):return ['Некорректный video_sha256']
    with video.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    return [] if expected==actual else ['MP4 не соответствует render.json по SHA-256']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--expected-seconds',type=float);ap.add_argument('--format',choices=['16:9','9:16'],default='16:9');ap.add_argument('--preview',action='store_true');ap.add_argument('--full-decode',action='store_true');ap.add_argument('--ocr',action='store_true');ap.add_argument('--output',type=Path);ap.add_argument('--legacy',action='store_true',help='Разрешить неполные исторические metadata с явными предупреждениями')
    args=ap.parse_args();errors=[];warnings=[]
    validate_report_path(args.output,[args.video]+[args.video.with_suffix(ext) for ext in BUNDLE_SUFFIXES],ROOT)
    checker_hash=file_sha256(Path(__file__))
    try:video_hash=file_sha256(args.video)
    except OSError:video_hash=None
    if args.output:args.output.write_text(json.dumps({'status':'incomplete','binding_status':'unknown','video_sha256':video_hash,'checker_sha256':checker_hash,'errors':['Проверка ещё не завершена']},ensure_ascii=False)+'\n')
    probe=call(['ffprobe','-v','error','-show_streams','-show_format','-of','json',args.video])
    if probe.returncode:raise RuntimeError(probe.stderr.decode())
    info=json.loads(probe.stdout);v=next((s for s in info['streams'] if s['codec_type']=='video'),None);a=next((s for s in info['streams'] if s['codec_type']=='audio'),None);dur=float(info['format']['duration'])
    if not v:raise RuntimeError('Нет видео')
    w,h=v['width'],v['height']
    for suffix in ['.srt','.credits.txt','.rights.txt','.render.json']:
        if not args.video.with_suffix(suffix).is_file():errors.append('Нет '+suffix)
    meta_path=args.video.with_suffix('.render.json');meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if isinstance(meta,dict) and isinstance(meta.get('warnings'),list):warnings.extend(w for w in meta['warnings'] if isinstance(w,str))
    errors.extend(review_metadata_errors(meta,dur,args.ocr,strict=not args.legacy))
    errors.extend(sidecar_errors(args.video,meta))
    if args.legacy:
        warnings.append('LEGACY: неполные исторические metadata разрешены; это не строгая проверка нового экспорта')
        absent=[field for field in REVIEW_FIELDS if not isinstance(meta,dict) or field not in meta]
        if absent:warnings.append('Не проверены отсутствующие metadata: '+', '.join(absent))
    if isinstance(meta,dict):
        errors.extend(stream_errors(v,a,dur,meta,args.format,args.preview,args.expected_seconds))
        errors.extend(file_integrity_errors(args.video,meta))
    if errors:
        report=finish_report({'file':str(args.video.resolve()),'errors':errors,'warnings':warnings,'full_decode':None,'sample_frames':[],'limitations':['Early validation failed; frame/audio scans were not run.']},args.video,video_hash,checker_hash)
        rendered=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
        if args.output:args.output.write_text(rendered)
        print(rendered);return 1
    if not meta:warnings.append('Нет render.json: длительность по сценарию не проверена')
    if not meta.get('video_sha256'):warnings.append('Нет video_sha256: связь MP4 с render.json не подтверждена хешем')
    style=json.loads((ROOT/'assets/style.json').read_text());colors=style['themes'][meta.get('theme','light')]
    rw,rh=style['canvas'][args.format];ref=Image.new('RGB',(rw,rh),colors['background']);size=round(min(52,rh*.034));brand(ref,geometry(rw,rh)['media'][0],rh*.955-size/2,size,colors,ROOT/style['font'],round(rw*(.017 if rw>rh else .028)));ref=ref.resize((w,h),Image.Resampling.BICUBIC)
    footer=(round(.045*w),round(.925*h),round(.32*w),round(.991*h))
    times={.15,dur*.25,dur*.5,dur*.75,max(.15,dur-.3)}
    boundaries=meta.get('scene_boundaries',[])
    for t in boundaries:
        times.update(max(.01,min(dur-.05,t+d)) for d in [-.15,.15,.7,1.4])
    events=meta.get('display_events',[])
    if args.ocr and not events:warnings.append('Нет display_events: OCR по ожидаемому тексту не проверен')
    for e in events:
        if e['duration']>.12:times.add(min(dur-.05,e['start']+e['duration']/2))
    samples=[]
    with tempfile.TemporaryDirectory(prefix='freelearn-check-') as folder:
        for t in sorted(times):
            out=call(['ffmpeg','-v','error','-ss',f'{t:.6f}','-i',args.video,'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
            if out.returncode or not out.stdout:errors.append(f'Нет кадра {t:.2f}');continue
            im=Image.open(BytesIO(out.stdout)).convert('RGB');x,y,r,b=geometry(w,h)['media'];roi=im.crop((x+20,y+20,r-20,b-20));st=ImageStat.Stat(roi);mean=sum(st.mean)/3;variation=sum(st.stddev)/3
            transition=any(abs(t-start)<1.5 for start in boundaries+[dur])
            if not transition and (mean<2 or mean>253 or variation<.8):errors.append(f'Пустое окно пейзажа {t:.2f} с')
            diff=sum(ImageStat.Stat(ImageChops.difference(im.crop(footer),ref.crop(footer))).mean)/3
            if diff>5:errors.append(f'Нижний логотип отличается от шаблона {t:.2f} с (ошибка {diff:.1f})')
            record={'time':round(t,3),'picture_mean':round(mean,2),'picture_stddev':round(variation,2),'footer_mean_error':round(diff,2)}
            if args.ocr:
                event=next((e for e in events if e['start']<=t<e['start']+e['duration']),None)
                if event and event.get('caption'):
                    box=caption_region(w,h);crop=im.crop(box);crop=crop.resize((crop.width*2,crop.height*2));path=Path(folder)/'widget.png';crop.save(path)
                    result=call(['tesseract',path,'stdout','--tessdata-dir',Path.home()/'.cache/freelearn-video/tessdata','-l','rus','--psm','6'])
                    if result.returncode:errors.append('OCR не выполнен: '+result.stderr.decode(errors='replace')[-180:])
                    else:
                        recognized=result.stdout.decode();wanted=words(event['caption']);seen=words(recognized);missing=list((Counter(wanted)-Counter(seen)).elements())
                        record.update(ocr=recognized.strip(),ocr_missing=missing,ocr_match=caption_matches(event['caption'],recognized))
                        if not record['ocr_match']:errors.append(f'OCR виджета {t:.2f} с: ожидаемый текст не совпал по порядку и повторениям слов')
            samples.append(record)
    audio_scan=call(['ffmpeg','-hide_banner','-nostats','-i',args.video,'-vn','-af','ebur128=peak=true','-f','null','-'])
    log=audio_scan.stderr.decode(errors='replace');summary=log[log.rfind('Summary:'):]
    pattern=r'(-?(?:[\d.]+|inf))'
    peak_match=re.search(r'Peak:\s*'+pattern+r' dBFS',summary);lufs_match=re.search(r'I:\s*'+pattern+r' LUFS',summary)
    peak=float(peak_match[1]) if peak_match else None;lufs=float(lufs_match[1]) if lufs_match else None
    silence=peak==float('-inf') and lufs is not None and (math.isfinite(lufs) or lufs==float('-inf'))
    expected_silence=args.preview and meta.get('preview') is True and not meta.get('caption_events') and meta.get('music_enabled') is False and meta.get('music_source') is None
    measurements={'true_peak_dbfs':peak if peak is not None and math.isfinite(peak) else None,'integrated_lufs':lufs if lufs is not None and math.isfinite(lufs) else None,'silence_detected':silence,'measurement_status':'measured'}
    if audio_scan.returncode:errors.append('Аудио не декодируется')
    if silence and expected_silence:
        measurements['measurement_status']='intentional_silence';warnings.append('Подтверждённая тишина: этот preview не содержит речи и музыка явно отключена')
    elif peak is None or lufs is None or not math.isfinite(peak) or not math.isfinite(lufs):
        measurements['measurement_status']='unknown';errors.append('Не измерены уровни аудио: true peak/LUFS неизвестны или тишина не предусмотрена')
    if peak is not None and math.isfinite(peak) and peak>-.5:errors.append('Слишком высокий true peak, риск клиппинга AAC')
    decoded=None
    if args.full_decode:
        result=call(['ffmpeg','-v','error','-xerror','-i',args.video,'-f','null','-']);decoded=result.returncode==0 and not result.stderr.strip()
        if not decoded:errors.append('Ошибка полного декодирования: '+result.stderr.decode(errors='replace')[-300:])
    report={'file':str(args.video.resolve()),'duration_seconds':dur,'video':{k:v.get(k) for k in ['codec_name','width','height','avg_frame_rate','duration','nb_frames']},'audio':{k:a.get(k) for k in ['codec_name','sample_rate','channels','duration']} if a else None,'full_decode':decoded,'audio_scan':measurements,'sample_frames':samples,'errors':errors,'warnings':warnings,'limitations':['Logo and OCR checks sample frames; they do not inspect every frame.','No listening assessment; ASR/OCR and loudness do not prove naturalness or aesthetics.']}
    report=finish_report(report,args.video,video_hash,checker_hash)
    rendered=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(rendered)
    print(rendered);return 1 if errors else 0
if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,KeyError,ValueError,TypeError,ZeroDivisionError,OverflowError,OSError) as error:
        print(json.dumps({'status':'incomplete','binding_status':'unknown','video_sha256':None,'errors':[str(error)]},ensure_ascii=False));sys.exit(2)

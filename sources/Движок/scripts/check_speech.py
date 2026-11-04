#!/usr/bin/env python3
"""Local Russian ASR comparison of actual encoded prompt intervals, no text prompt."""
import argparse,hashlib,json,math,os,re,subprocess,tempfile
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from export_files import validate_report_path,BUNDLE_SUFFIXES
from scenario import number
os.environ.setdefault('HF_HUB_OFFLINE','1')

def words(text):return re.findall(r'[а-яa-z0-9]+',text.lower().replace('ё','е'))
def speech_events(meta):
    if not isinstance(meta,dict):raise ValueError('render.json должен быть объектом')
    duration=number(meta.get('duration_seconds'),'duration_seconds',positive=True);captions=meta.get('caption_events',[]);events=[]
    if not isinstance(captions,list):raise ValueError('caption_events должен быть списком')
    if not math.isfinite(duration) or duration<=0:raise ValueError('Некорректная длительность речи')
    if not captions:raise ValueError('Нет речевых интервалов: проверка слов не выполнена')
    for caption in captions:
        if not isinstance(caption,dict) or not isinstance(caption.get('text'),str):raise ValueError('Некорректная подпись речи')
        start,end=number(caption.get('start'),'start'),number(caption.get('end'),'end',positive=True)
        if not all(math.isfinite(t) for t in (start,end)) or not 0<=start<duration or not start<end<=duration+.001 or not words(caption['text']):
            raise ValueError('Некорректный речевой интервал')
        end=min(end,duration)
        if events and start<events[-1]['end']-.000001:raise ValueError('Речевые интервалы пересекаются или не упорядочены')
        if events and abs(start-events[-1]['end'])<.05:
            events[-1]['end']=end;events[-1]['text']+=' '+caption['text'];events[-1]['source_caption_count']+=1
        else:events.append({**caption,'start':start,'end':end,'source_caption_count':1})
    return events


def main():
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--model',default='mlx-community/whisper-small-mlx');args=ap.parse_args()
    validate_report_path(args.output,[args.video]+[args.video.with_suffix(ext) for ext in BUNDLE_SUFFIXES],Path(__file__).resolve().parents[1])
    args.output.write_text(json.dumps({'status':'incomplete','all_exact_words':False,'errors':['Проверка ещё не завершена'],'hearing_reviewed':False},ensure_ascii=False)+'\n')
    meta=json.loads(args.video.with_suffix('.render.json').read_text());rows=[]
    try:events=speech_events(meta)
    except (RuntimeError,ValueError,KeyError,TypeError) as error:
        args.output.write_text(json.dumps({'errors':[str(error)],'all_exact_words':False,'hearing_reviewed':False},ensure_ascii=False,indent=2)+'\n')
        return 1
    with args.video.open('rb') as stream:video_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    if meta.get('video_sha256') is not None and meta['video_sha256']!=video_hash:
        args.output.write_text(json.dumps({'errors':['MP4 не соответствует render.json по SHA-256'],'all_exact_words':False,'hearing_reviewed':False},ensure_ascii=False)+'\n');return 1
    # Load the recognizer only after input validation; no inference for an empty test.
    import mlx_whisper
    with tempfile.TemporaryDirectory(prefix='freelearn-asr-') as tmp:
        for i,e in enumerate(events):
            clip=Path(tmp)/f'{i}.wav';start=max(0,e['start']-.15);length=e['end']-start+.2
            subprocess.run(['ffmpeg','-y','-v','error','-ss',str(start),'-i',str(args.video),'-t',str(length),'-vn','-ar','16000','-ac','1',str(clip)],check=True)
            result=mlx_whisper.transcribe(str(clip),path_or_hf_repo=args.model,language='ru',condition_on_previous_text=False,fp16=True,verbose=False)
            expected=e['text'];recognized=result['text'].strip();same=words(expected)==words(recognized)
            rows.append({'start':e['start'],'end':e['end'],'source_caption_count':e['source_caption_count'],'expected':expected,'recognized':recognized,'exact_words':same,'words_per_minute':round(60*len(words(expected))/(e['end']-e['start']),1)})
            print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    duration=float(meta['duration_seconds']);spoken=sum(e['end']-e['start'] for e in events)
    report={'status':'complete','video':str(args.video.resolve()),'video_sha256':video_hash,'model':args.model,'initial_prompt_used':False,'group_contiguous_caption_chunks':True,'events':rows,'all_exact_words':all(r['exact_words'] for r in rows),'spoken_seconds':round(spoken,3),'without_speech_seconds':round(duration-spoken,3),'hearing_reviewed':False,'limitations':'ASR mismatch requires review; exact words do not prove pronunciation, timbre, accent or naturalness.'}
    with args.video.open('rb') as stream:unchanged=hashlib.file_digest(stream,'sha256').hexdigest()==video_hash
    if not unchanged:report.update(all_exact_words=False,errors=['MP4 изменился во время распознавания'])
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return 0 if report['all_exact_words'] else 1
if __name__=='__main__':
    try:raise SystemExit(main())
    except (RuntimeError,ValueError,KeyError,TypeError,OSError,subprocess.CalledProcessError) as error:
        print(json.dumps({'errors':[str(error)],'all_exact_words':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)

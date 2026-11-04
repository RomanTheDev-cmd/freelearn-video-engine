#!/usr/bin/env python3
"""Independent speech/music treatment, stems and measured local mix at 48 kHz."""
import argparse,json,math
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
import pyloudnorm as pyln
from pedalboard import Pedalboard,HighpassFilter,LowpassFilter,PeakFilter,Compressor,Reverb
import sys
sys.dont_write_bytecode=True
from audio_plan import validate_mix_settings,merge_prompt_intervals

def mix_settings(settings,kind):
    result=dict(settings)
    if kind=='meditation':result.setdefault('meditation_speech_lufs',-30.5)
    specific=kind+'_prompt_music_reduction_db'
    if specific in result:result['prompt_music_reduction_db']=result[specific]
    return validate_mix_settings(result,kind)

def read(path,rate,*,processed=False):
    data,sr=sf.read(path,dtype='float32',always_2d=True)
    if not len(data) or data.shape[1] not in (1,2) or not np.isfinite(data).all():raise RuntimeError('Пустой, многоканальный или некорректный входной звук: '+path.name)
    if processed and np.max(np.abs(data))>1:raise RuntimeError('Обработанная речь выходит за PCM full scale: '+path.name)
    if sr!=rate:
        divisor=math.gcd(sr,rate);data=resample_poly(data,rate//divisor,sr//divisor,axis=0).astype('float32')
    if processed and np.max(np.abs(data))>1:raise RuntimeError('Обработанная речь после ресемплинга выходит за PCM full scale: '+path.name)
    return np.repeat(data,2,axis=1) if data.shape[1]==1 else data[:,:2]

def metrics(data,rate):
    if not data.size or not np.isfinite(data).all():raise RuntimeError('Некорректные данные для измерения звука')
    peak=float(np.max(np.abs(data)))
    loudness=pyln.Meter(rate).integrated_loudness(data) if len(data)>.4*rate and peak>1e-8 else float('-inf')
    return {'sample_peak_dbfs':round(20*np.log10(max(peak,1e-12)),2),'integrated_lufs':round(float(loudness),2) if np.isfinite(loudness) else None,'rms_dbfs':round(20*np.log10(max(float(np.sqrt(np.mean(data**2))),1e-12)),2)}

def level(data,rate,target):
    measured=metrics(data,rate)['integrated_lufs']
    if measured is None:return data
    result=data*10**((target-measured)/20)
    peak=float(np.max(np.abs(result)))
    if peak>.85:result*=.85/peak
    return result.astype('float32')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--speech',type=Path,required=True);ap.add_argument('--music',type=Path);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--style',type=Path,required=True);ap.add_argument('--type',choices=['meditation','lesson'],required=True)
    ap.add_argument('--timings',type=Path)
    ap.add_argument('--speech-processed',action='store_true',help='Reuse an existing processed speech stem without applying FX twice')
    args=ap.parse_args();style=mix_settings(json.loads(args.style.read_text())['audio'],args.type);rate=48000
    inputs={p.resolve() for p in [args.speech,args.music,args.style,args.timings] if p is not None}
    stem=args.output.with_suffix('');targets=[args.output,Path(str(stem)+'.speech.wav'),Path(str(stem)+'.music.wav'),args.output.with_suffix('.audio.json')]
    if any(p.resolve() in inputs or p.is_symlink() for p in targets):raise RuntimeError('Выходные файлы звука пересекаются с исходниками')
    speech=read(args.speech,rate,processed=args.speech_processed)
    raw=read(args.music,rate) if args.music else None
    if raw is not None and abs(len(raw)-len(speech))>1:raise RuntimeError('Длительности музыки и речи не совпадают; автоматическое дополнение тишиной отключено')
    intervals=merge_prompt_intervals(json.loads(args.timings.read_text()),len(speech)/rate) if args.music and args.timings else []
    # Real stereo Freeverb; speech receives the same processing when music is off.
    if not args.speech_processed:
        chain=Pedalboard([HighpassFilter(cutoff_frequency_hz=70),PeakFilter(cutoff_frequency_hz=2800,gain_db=-2,q=1),LowpassFilter(cutoff_frequency_hz=8500),Compressor(threshold_db=-24,ratio=1.6,attack_ms=30,release_ms=180),Reverb(room_size=.5,damping=.68,wet_level=.065,dry_level=1,width=.65)])
        speech=chain(speech.T.copy(),rate).T
        speech=level(speech,rate,style.get(args.type+'_speech_lufs',-30.5 if args.type=='meditation' else -22))
    music=np.zeros_like(speech)
    if args.music:
        music[:min(len(raw),len(music))]=raw[:len(music)]
        music=level(music,rate,style.get(args.type+'_music_lufs',-29 if args.type=='meditation' else -35))
    # Planned slow fades around complete prompt groups, not a pumping amplitude follower.
    if intervals:
        curve=np.ones(len(music),dtype='float32')
        depth=10**(style.get('prompt_music_reduction_db',-6)/20)
        for start,end in intervals:
            lo=max(0,round((start-1.8)*rate));hi=min(len(curve),round((end+3.5)*rate));t=np.arange(lo,hi)/rate
            attack=np.clip((t-(start-1.8))/1.8,0,1);release=np.clip((end+3.5-t)/3.5,0,1)
            shape=.5-.5*np.cos(np.pi*np.minimum(attack,release))
            curve[lo:hi]=np.minimum(curve[lo:hi],1-(1-depth)*shape)
        music*=curve[:,None]
    # Leave headroom without automatic limiter makeup gain.
    mixed=speech+music
    peak=float(np.max(np.abs(mixed)));headroom=10**(-2/20)
    mix_gain=min(1.,headroom/max(peak,1e-12))
    mixed*=mix_gain
    if not np.isfinite(mixed).all():raise RuntimeError('Non-finite mix')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    stem=args.output.with_suffix('')
    paths={'speech':Path(str(stem)+'.speech.wav'),'music':Path(str(stem)+'.music.wav')}
    for name,data in [('speech',speech),('music',music)]:sf.write(paths[name],data,rate,subtype='PCM_24')
    sf.write(args.output,mixed,rate,subtype='PCM_24')
    report={'sample_rate':rate,'channels':2,'reused_processed_speech':args.speech_processed,'effects':'Pedalboard EQ/compressor/Freeverb; transparent peak guard -2 dBFS, no automatic makeup','mix_gain_db':round(20*np.log10(mix_gain),3),'music_enabled':bool(args.music),'prompt_music_reduction_db':style.get('prompt_music_reduction_db',-6) if intervals else 0,'prompt_groups':intervals,'speech':metrics(speech,rate),'music':metrics(music,rate),'mix':metrics(mixed,rate),'stems':{k:v.name for k,v in paths.items()},'hearing_reviewed':False}
    args.output.with_suffix('.audio.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()

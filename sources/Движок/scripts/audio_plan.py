"""Validate mix targets and prompt envelopes without loading an audio engine."""
import math


def finite(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise RuntimeError(label+': нужно конечное число')
    try:value=float(value)
    except OverflowError:raise RuntimeError(label+': число слишком велико') from None
    if not math.isfinite(value):raise RuntimeError(label+': нужно конечное число')
    return float(value)


def tts_filter_chain(length_scale):
    scale=finite(length_scale,'length_scale')
    if not .5<=scale<=2:raise RuntimeError('length_scale должен быть от 0.5 до 2')
    filters=[] if scale==1 else [f'atempo={1/scale:.8f}']
    return ','.join(filters+['loudnorm=I=-20:TP=-3:LRA=7'])


def validate_mix_settings(style,kind):
    defaults={'meditation':(-26,-29),'lesson':(-22,-35)}
    if kind not in defaults:raise RuntimeError('Неизвестный тип микса')
    speech,music=defaults[kind]
    result=dict(style)
    for field,default in [(kind+'_speech_lufs',speech),(kind+'_music_lufs',music),('prompt_music_reduction_db',-6)]:
        result[field]=finite(style.get(field,default),field)
        if result[field]>0:raise RuntimeError(field+' не должен усиливать выше 0 dB/LUFS')
    return result


def merge_prompt_intervals(cues,duration):
    duration=finite(duration,'duration')
    if duration<=0 or not isinstance(cues,list):raise RuntimeError('Некорректный таймлайн речи')
    ordered=[]
    for cue in cues:
        if not isinstance(cue,(list,tuple)) or len(cue)<2:raise RuntimeError('Некорректная подсказка')
        start,end=finite(cue[0],'start'),finite(cue[1],'end')
        if not 0<=start<duration or not start<end<=duration+.001:raise RuntimeError('Подсказка выходит за длительность звука')
        ordered.append([start,min(end,duration)])
    merged=[]
    for start,end in sorted(ordered):
        if merged and start-merged[-1][1]<6:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    return merged

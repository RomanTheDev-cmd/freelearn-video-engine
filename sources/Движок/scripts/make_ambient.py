#!/usr/bin/env python3
"""Continuous warm pad with no beat, melodic line or repeated chord attacks."""
import argparse,hashlib,json,os,re
from pathlib import Path
import numpy as np
import soundfile as sf
from mido import Message,MidiFile,MidiTrack,MetaMessage,bpm2tempo,second2tick
from pedalboard import load_plugin,Pedalboard,Reverb,Chorus,HighpassFilter,LowpassFilter

def envelope_value(plugin,name,seconds):
    choices=[]
    for value in plugin.parameters[name].valid_values:
        match=re.fullmatch(r'([\d.]+)\s*(ms|s)',str(value))
        if match:choices.append((abs(float(match[1])/(1000 if match[2]=='ms' else 1)-seconds),value))
    if not choices:raise RuntimeError('Unsupported envelope parameter '+name)
    return min(choices)[1]

def instrument(path):
    p=load_plugin(str(path),initialization_timeout=10)
    parameters={'global_volume':-18,'a_osc_1_type':'Classic','a_filter_1_type':'LP 24 dB','a_filter_1_cutoff':330,'a_filter_1_resonance':2,'a_amp_eg_sustain':65,'a_amp_eg_attack_shape':'Linear','a_osc_2_mute':True,'a_osc_3_mute':True,'a_noise_mute':True,'a_osc_1_shape':-60,'a_osc_1_unison_voices':'3 voices','a_osc_1_unison_detune':'5.00 cents'}
    for k,v in parameters.items():setattr(p,k,v)
    for name,seconds in [('a_amp_eg_attack',18),('a_amp_eg_decay',8),('a_amp_eg_release',18)]:
        value=envelope_value(p,name,seconds);setattr(p,name,value);parameters[name]=value
    return p,parameters

def composition(duration):
    if not np.isfinite(duration) or duration<=0:raise RuntimeError('Invalid ambient duration')
    # Open A2/D3/A3/E4 voicing: held once, no upper-note motif or chord cycle.
    off=max(duration*.5,duration-20)
    events=[]
    for note,velocity in [(45,23),(50,26),(57,20),(64,16)]:
        events.extend([Message('note_on',note=note,velocity=velocity,time=0),Message('note_off',note=note,velocity=0,time=off)])
    return sorted(events,key=lambda e:e.time)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);ap.add_argument('--duration',type=float,required=True);ap.add_argument('--sample-rate',type=int,default=48000);ap.add_argument('--seed',type=int,default=17)
    args=ap.parse_args()
    if not 1<=args.duration<=3600:ap.error('Duration must be 1–3600 seconds')
    if not 8000<=args.sample_rate<=192000:ap.error('Sample rate must be 8000–192000 Hz')
    if not 0<=args.seed<2**32:ap.error('Seed must be 0–4294967295')
    runtime=Path(os.environ.get('FREELEARN_VIDEO_RUNTIME',Path.home()/'.local/share/freelearn-video'))
    path=runtime/'surge-xt-1.3.4/Surge XT.vst3'
    if not path.exists():raise RuntimeError('Install official Surge XT 1.3.4 plugins ZIP in local runtime; see references/audio-quality.md')
    rate=args.sample_rate;n=round(args.duration*rate)
    plugin,parameters=instrument(path);events=composition(args.duration)
    mix=plugin(events,duration=args.duration,sample_rate=rate,num_channels=2,buffer_size=512)
    if mix.shape!=(2,n) or not np.isfinite(mix).all() or np.max(np.abs(mix))<1e-7:raise RuntimeError('Surge produced invalid or silent audio')
    # Tiny nonperiodic gain drift on a long timescale; no amplitude pulse.
    rng=np.random.default_rng(args.seed);knots=np.linspace(0,args.duration,max(3,int(args.duration/70)+2))
    t=np.arange(n,dtype='float32')/rate;swell=np.interp(t,knots,rng.uniform(.94,1.0,len(knots))).astype('float32')
    mix*=swell
    mix=Pedalboard([HighpassFilter(cutoff_frequency_hz=55),LowpassFilter(cutoff_frequency_hz=1400),Chorus(rate_hz=.025,depth=.10,centre_delay_ms=16,feedback=.02,mix=.08),Reverb(room_size=.86,damping=.78,wet_level=.40,dry_level=.72,width=.85)])(mix,rate)
    fade=np.minimum(1,t/15)*np.minimum(1,np.maximum(0,args.duration-t)/18);mix*=fade
    peak=float(np.max(np.abs(mix)))
    if peak>.7:mix*=.7/peak
    args.output.parent.mkdir(parents=True,exist_ok=True);sf.write(args.output,mix.T,rate,subtype='PCM_24')
    # Save authored notes and patch parameters beside the cached music for reuse.
    midi=MidiFile(ticks_per_beat=480);track=MidiTrack();midi.tracks.append(track);tempo=bpm2tempo(60);track.append(MetaMessage('set_tempo',tempo=tempo,time=0));previous=0
    for e in events:
        ticks=round(second2tick(e.time,480,tempo));track.append(e.copy(time=ticks-previous));previous=ticks
    midi.save(args.output.with_suffix('.mid'))
    binary=path/'Contents/MacOS/Surge XT'
    with binary.open('rb') as stream:fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()
    args.output.with_suffix('.music.json').write_text(json.dumps({'engine':'Surge XT 1.3.4/Pedalboard','plugin_sha256':fingerprint,'duration':args.duration,'sample_rate':rate,'seed':args.seed,'composition':'A2 D3 A3 E4 sustained once; no beat or melodic line','layers':[{'layer':'warm continuous pad','parameters':parameters}],'render_note':'MIDI and seeded slow gain drift reproducible; plugin free-running phase is not guaranteed bit-identical.','hearing_reviewed':False},indent=2)+'\n')
    print('Ambient rendered: '+str(args.output),flush=True)
if __name__=='__main__':main()

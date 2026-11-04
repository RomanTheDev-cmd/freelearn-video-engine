"""Check cached PCM structure and completeness without synthesis or decoding tools."""
import wave


def validate_pcm(path,rate,channels,width,duration=None):
    if not path.exists():return False
    try:
        with wave.open(str(path),'rb') as stream:
            frames=stream.getnframes()
            if (stream.getframerate(),stream.getnchannels(),stream.getsampwidth())!=(rate,channels,width) or frames<=0:raise ValueError('wrong PCM format or empty WAV')
            if duration is not None and abs(frames-round(duration*rate))>1:raise ValueError('wrong cached duration')
            expected=frames*channels*width;actual=0;nonzero=False
            while True:
                chunk=stream.readframes(65536)
                if not chunk:break
                actual+=len(chunk);nonzero=nonzero or any(chunk)
            if actual!=expected or not nonzero:raise ValueError('truncated or entirely silent PCM')
    except (OSError,EOFError,wave.Error,ValueError) as error:
        raise RuntimeError(f'Повреждён или пуст звуковой кэш {path.name}; автоматическая повторная генерация отключена') from error
    return True

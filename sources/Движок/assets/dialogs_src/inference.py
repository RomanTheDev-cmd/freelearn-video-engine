"""Minimal example: synthesize expressive Russian speech with Dialogs-RU VITS2.

    pip install -r requirements.txt
    python inference.py

If you cloned this repo (or used ``snapshot_download``), the weights next to
this file are used automatically. Otherwise they are fetched from the Hub.
You can also point to a local checkpoint folder with
``DIALOGS_LOCAL_CKPT=/path/to/folder``.
"""

from scipy.io.wavfile import write

from tts import DialogsTTS, SPEAKERS, EMOTIONS

tts = DialogsTTS()
print("Speakers:", {i: v[0] for i, v in SPEAKERS.items()})
print("Emotions:", {i: v[0] for i, v in EMOTIONS.items()})

# speaker_id: 0=Masha (F), 1=Sveta (F), 2=Dima (M)
# emotion_id: 0=neutral 1=happy 2=surprise 3=arrogance 4=yawn 5=fear
#             6=laughing 7=whisper 8=disgust 9=angry 10=sad
#             11=tongue-twister 12=poem
sr, audio, used = tts.synthesize(
    "В 2024 году мы выпустили 3 голоса и 13 эмоций!",
    speaker_id=0,
    emotion_id=1,
    normalize=True,    # rutextnorm: spell out numbers, dates, abbreviations
    auto_stress=True,  # ruaccent: auto-place '+' stress
)
write("output.wav", sr, audio)
print(f"Wrote output.wav  ({len(audio) / sr:.2f}s)  |  text sent: {used}")

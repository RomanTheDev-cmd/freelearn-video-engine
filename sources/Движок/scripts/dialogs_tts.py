#!/usr/bin/env python3
"""Safe local adapter for the pinned Dialogs-RU VITS2 implementation.

Reads one Russian utterance from stdin and writes a WAV file. The upstream
checkpoint loader in assets/dialogs_src/tts.py is patched to weights_only=True.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from scipy.io.wavfile import write

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
SKILL = Path(__file__).resolve().parent.parent
SOURCE = SKILL / "assets" / "dialogs_src"
sys.path.insert(0, str(SOURCE))

from tts import DialogsTTS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="directory with config.json and averaged_G_615000.pth")
    parser.add_argument("--output", required=True)
    parser.add_argument("--speaker", type=int, default=0, choices=(0, 1, 2))
    parser.add_argument("--emotion", type=int, default=0, choices=range(13))
    parser.add_argument("--length-scale", type=float, default=1.08, help="Above 1.0 slows and lengthens speech")
    parser.add_argument("--auto-stress", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    model = Path(args.model).expanduser().resolve()
    if not (model / "config.json").is_file() or not (model / "averaged_G_615000.pth").is_file():
        parser.error("--model must contain config.json and averaged_G_615000.pth")
    os.environ["DIALOGS_LOCAL_CKPT"] = str(model)
    utterance = sys.stdin.read().strip()
    engine = DialogsTTS()
    if args.auto_stress and engine.accentizer is None:
        raise RuntimeError("RUAccent did not load; refusing to synthesize without Russian stress marks")
    sample_rate, audio, normalized = engine.synthesize(
        utterance,
        speaker_id=args.speaker,
        emotion_id=args.emotion,
        normalize=True,
        auto_stress=args.auto_stress,
        length_scale=args.length_scale,
    )
    write(args.output, sample_rate, np.asarray(audio, dtype=np.int16))
    print(f"Saved {args.output}; normalized text: {normalized}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Download the pinned Dialogs-RU checkpoint into the local user cache."""
from __future__ import annotations

import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO = "frappuccino/dialogs-ru-vits2"
REVISION = "af7eabc15d087fce701de7261190ccb747c3bc7a"
DEST = Path.home() / ".cache" / "freelearn-video" / "dialogs-ru-vits2"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    config = hf_hub_download(REPO, "config.json", revision=REVISION)
    weights = hf_hub_download(REPO, "averaged_G_615000.pth", revision=REVISION)
    shutil.copy2(config, DEST / "config.json")
    shutil.copy2(weights, DEST / "averaged_G_615000.pth")
    print(f"Pinned model installed locally: {DEST}")
    print("The 529 MB checkpoint is cached; no hosted inference request was sent.")


if __name__ == "__main__":
    main()

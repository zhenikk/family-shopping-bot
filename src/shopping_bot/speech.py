from __future__ import annotations
from .i18n import tr, language

import subprocess
import tempfile
from pathlib import Path

from .telegram import Telegram


class SpeechError(RuntimeError):
    pass


def transcribe(
    telegram: Telegram,
    file_id: str,
    whisper_cli: Path,
    whisper_model: Path,
    timeout: int | None = None,
    *, language_code: str = "uk",
) -> str:
    if language_code not in ("uk", "en"):
        raise ValueError("Invalid language")
    if not whisper_cli.is_file() or not whisper_model.is_file():
        raise SpeechError(tr('ui_cec30466e9b4'))
    with tempfile.TemporaryDirectory(prefix="shopping-voice-") as directory:
        root = Path(directory)
        audio = root / "voice.ogg"
        wav = root / "voice.wav"
        output_prefix = root / "transcript"
        telegram.download(file_id, audio)
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                check=True, timeout=60, capture_output=True,
            )
            subprocess.run(
                [str(whisper_cli), "-m", str(whisper_model), "-f", str(wav), "-l", language_code, "-t", "2",
                 "-otxt", "-of", str(output_prefix)],
                check=True, timeout=timeout, capture_output=True,
            )
        except FileNotFoundError as exc:
            raise SpeechError(tr('ui_04357d3d9005')) from exc
        except subprocess.TimeoutExpired as exc:
            raise SpeechError(tr('ui_fcda912799ea')) from exc
        except subprocess.CalledProcessError as exc:
            raise SpeechError(tr('ui_0665b021bd91')) from exc
        output = output_prefix.with_suffix(".txt")
        if not output.is_file():
            raise SpeechError(tr('ui_75322ec76842'))
        return output.read_text(encoding="utf-8").strip()

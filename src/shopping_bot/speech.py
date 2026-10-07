from __future__ import annotations

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
) -> str:
    if not whisper_cli.is_file() or not whisper_model.is_file():
        raise SpeechError("Локальне розпізнавання голосу ще не налаштоване")
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
                [str(whisper_cli), "-m", str(whisper_model), "-f", str(wav), "-l", "uk", "-t", "2",
                 "-otxt", "-of", str(output_prefix)],
                check=True, timeout=timeout, capture_output=True,
            )
        except FileNotFoundError as exc:
            raise SpeechError("Потрібно встановити ffmpeg та whisper.cpp") from exc
        except subprocess.TimeoutExpired as exc:
            raise SpeechError("Розпізнавання тривало надто довго; спробуйте коротше повідомлення") from exc
        except subprocess.CalledProcessError as exc:
            raise SpeechError("Не вдалося розпізнати голосове повідомлення") from exc
        output = output_prefix.with_suffix(".txt")
        if not output.is_file():
            raise SpeechError("Розпізнавання не повернуло текст")
        return output.read_text(encoding="utf-8").strip()

from __future__ import annotations
from .i18n import tr, language

import time
import os
import logging
from .groq_speech import transcribe_audio
from .speech_race import race, run_local

import subprocess
import tempfile
from pathlib import Path

from .telegram import Telegram


class SpeechError(RuntimeError):
    pass


def shopping_prompt(language_code, catalog=()):
    """A short context hint, not a constrained output vocabulary."""
    base = ("Молоко, яйця, хліб, картопля, помідори, огірки, банани, сир, сметана, макарони, олія, кава, зубна паста, кондиціонер для білизни."
            if language_code == "uk" else
            "Milk, eggs, bread, potatoes, tomatoes, cucumbers, bananas, cheese, pasta, olive oil, coffee, toothpaste, laundry detergent.")
    names = []
    for value in catalog:
        value = " ".join(str(value).split())
        if 1 <= len(value) <= 60 and value not in names:
            names.append(value)
        if len(names) >= 12:
            break
    return (base + (" " + ", ".join(names) if names else ""))[:480]

def transcribe(
    telegram: Telegram,
    file_id: str,
    whisper_cli: Path,
    whisper_model: Path,
    timeout: int = 300,
    *, language_code: str = "uk", vocabulary=(), shopping_context=True, benchmark=None,
) -> str:
    if language_code not in ("uk", "en"):
        raise ValueError("Invalid language")
    request_started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix="shopping-voice-") as directory:
        root = Path(directory)
        audio = root / "voice.ogg"
        wav = root / "voice.wav"
        output_prefix = root / "transcript"
        telegram.download(file_id, audio)
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
                 "-t", "121", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                check=True, timeout=60, capture_output=True,
            )
            if wav.stat().st_size > 120 * 16000 * 2 + 4096:
                raise SpeechError('Voice messages must be at most 2 minutes.' if language.get() == 'en' else 'Голосове має бути не довшим за 2 хвилини.')
            prompt=shopping_prompt(language_code,vocabulary) if shopping_context else ''
            def local_recognize(path,prefix):
                if not whisper_cli.is_file() or not whisper_model.is_file():
                    raise SpeechError(tr('ui_cec30466e9b4'))
                subprocess.run([str(whisper_cli), '-m', str(whisper_model), '-f', str(path), '-l', language_code, '-t', '2', '--prompt', prompt, '-otxt', '-of', str(prefix)],check=True,timeout=timeout,capture_output=True)
                output=Path(str(prefix)+'.txt')
                if not output.is_file():raise SpeechError(tr('ui_75322ec76842'))
                return output.read_text(encoding='utf-8').strip()
            provider=os.getenv('SHOPPING_SPEECH_PROVIDER','local')
            if provider=='race':
                # Each candidate owns its files until it finishes, even after the winner returns.
                audio_bytes=wav.read_bytes()
                def candidate(kind):
                    with tempfile.TemporaryDirectory(prefix='speech-candidate-') as folder:
                        path=Path(folder)/'voice.wav';path.write_bytes(audio_bytes)
                        return transcribe_audio(path,language_code,prompt) if kind=='groq' else local_recognize(path,Path(folder)/'transcript')
                duration_ms=max(0,round((len(audio_bytes)-44)/32))
                preprocessing_ms=round((time.monotonic()-request_started)*1000)
                def record(state):
                    if benchmark:benchmark(dict(state,language=language_code,audio_ms=duration_ms,delivered_ms=(state['delivered_ms']+preprocessing_ms) if state['delivered_ms'] is not None else None))
                try:return race(lambda:candidate('local'),lambda:candidate('groq'),record)
                except Exception:
                    logging.getLogger(__name__).warning('Speech race unavailable; retrying local Whisper')
            elif provider=='groq':
                try:return transcribe_audio(wav,language_code,prompt)
                except Exception:
                    logging.getLogger(__name__).warning('Groq unavailable; using local Whisper')
            return run_local(lambda:local_recognize(wav,output_prefix))
        except FileNotFoundError as exc:
            raise SpeechError(tr('ui_04357d3d9005')) from exc
        except subprocess.TimeoutExpired as exc:
            raise SpeechError(tr('ui_fcda912799ea')) from exc
        except subprocess.CalledProcessError as exc:
            raise SpeechError(tr('ui_0665b021bd91')) from exc

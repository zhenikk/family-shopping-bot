from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.file_base = f"https://api.telegram.org/file/bot{token}/"

    def call(self, method: str, **params: Any) -> Any:
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
                description = payload.get("description", "Telegram HTTP error")
            except (ValueError, OSError):
                description = "Telegram HTTP error"
            raise TelegramError(str(description)) from exc
        except urllib.error.URLError as exc:
            raise TelegramError("Telegram network error") from exc
        if not payload.get("ok"):
            raise TelegramError(str(payload.get("description", "Telegram API error")))
        return payload["result"]

    def download(self, file_id: str, destination: Path, limit: int = 20_000_000) -> None:
        info = self.call("getFile", file_id=file_id)
        if info.get("file_size", 0) > limit:
            raise TelegramError("Файл завеликий для бота")
        file_path = info["file_path"]
        url = self.file_base + urllib.parse.quote(file_path, safe="/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:
                remaining = limit + 1
                while remaining > 0:
                    chunk = response.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    output.write(chunk)
                    remaining -= len(chunk)
                if remaining <= 0:
                    destination.unlink(missing_ok=True)
                    raise TelegramError("Файл завеликий для бота")
        except urllib.error.URLError as exc:
            destination.unlink(missing_ok=True)
            raise TelegramError("Не вдалося завантажити файл із Telegram") from exc

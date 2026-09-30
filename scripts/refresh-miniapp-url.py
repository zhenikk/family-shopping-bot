#!/usr/bin/env python3
"""Refresh the temporary tunnel URL without displaying any .env secrets."""
import os
import re
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
subprocess.run(["docker", "compose", "--profile", "miniapp", "up", "-d", "tunnel"], check=True)
for attempt in range(30):
    logs = subprocess.run(["docker", "compose", "logs", "--tail", "150", "tunnel"], capture_output=True, text=True, check=True)
    urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", logs.stdout + logs.stderr)
    if urls:
        break
    time.sleep(2)
else:
    raise SystemExit("Тунель ще не отримав URL. Спробуйте знову за хвилину.")
path = root / ".env"
lines = [line for line in path.read_text().splitlines() if not line.startswith("SHOPPING_WEB_URL=")]
path.write_text("\n".join(lines + ["SHOPPING_WEB_URL=" + urls[-1]]) + "\n")
path.chmod(0o600)
subprocess.run(["docker", "compose", "up", "-d", "bot"], check=True)
print("Mini App URL оновлено:", urls[-1])

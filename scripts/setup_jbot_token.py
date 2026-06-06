"""寫入 JBOT_TOKEN 至 .env 與 .streamlit/secrets.toml（兩者皆 gitignore，不會 commit）。

用法:
  python scripts/setup_jbot_token.py YOUR_JBOT_TOKEN
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _upsert_env_line(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")


def _upsert_secrets_toml(path: Path, token: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f'JBOT_TOKEN = "{token}"'
    if "JBOT_TOKEN" in text:
        text = re.sub(r'^JBOT_TOKEN\s*=.*$', line, text, flags=re.MULTILINE)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("用法: python scripts/setup_jbot_token.py YOUR_JBOT_TOKEN")
        print("申請: https://sportsbot.tech/trial")
        sys.exit(1)

    token = sys.argv[1].strip()
    env_path = ROOT / ".env"
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)

    _upsert_env_line(env_path, "JBOT_TOKEN", token)
    _upsert_secrets_toml(secrets_path, token)
    print(f"已寫入 {env_path.name} 與 {secrets_path}")
    print("Streamlit Cloud：Settings → Secrets 也需加入 JBOT_TOKEN")


if __name__ == "__main__":
    main()

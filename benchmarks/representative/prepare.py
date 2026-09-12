from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GENERATED = ROOT / ".generated"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _make_task(name: str, files: dict[str, str], oracle: str) -> None:
    task = GENERATED / name
    repo = task / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        _write(repo / relative, content)
    _write(task / "oracle.py", oracle)
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=AvoGym",
            "-c", "user.email=avogym@example.invalid", "commit", "-q", "-m", "fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    if GENERATED.exists():
        shutil.rmtree(GENERATED)
    GENERATED.mkdir(parents=True)

    _make_task(
        "bugfix-normalize",
        {
            "normalize.py": '''import re\n\ndef normalize_email(value: str) -> str:\n    value = value.strip().lower()\n    local, domain = value.split("@", 1)\n    local = local.replace(".", "")\n    return f"{local}@{domain}"\n''',
            "visible_test.py": '''from normalize import normalize_email\n\nassert normalize_email(" Test@Example.COM ") == "test@example.com"\nprint("ok")\n''',
        },
        '''import pathlib, sys\nroot = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root))\nfrom normalize import normalize_email\nassert normalize_email(" Test@Example.COM ") == "test@example.com"\nassert normalize_email("first.last@example.com") == "first.last@example.com"\nassert normalize_email("User+Tag@Example.com") == "user+tag@example.com"\ntry:\n    normalize_email("not-an-email")\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError("invalid email must raise ValueError")\nprint('{"score": 1.0, "summary": "normalization contract satisfied"}')\n''',
    )

    _make_task(
        "repo-analysis-settings",
        {
            "settings.py": '''DEFAULTS = {"host": "localhost", "port": 8080, "debug": False}\n\ndef resolve(config: dict, env: dict) -> dict:\n    result = dict(DEFAULTS)\n    result.update(env)\n    result.update(config)\n    if "port" in result:\n        result["port"] = int(result["port"])\n    return result\n''',
            "service.py": '''from settings import resolve\n\ndef endpoint(config: dict, env: dict) -> str:\n    s = resolve(config, env)\n    scheme = "http" if s.get("debug") else "https"\n    return f"{scheme}://{s['host']}:{s['port']}"\n''',
            "visible_test.py": '''from settings import resolve\nassert resolve({"port": 9000}, {})["port"] == 9000\nprint("ok")\n''',
        },
        '''import pathlib, sys\nroot = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root))\nfrom settings import resolve\nfrom service import endpoint\ns = resolve({"host": "config-host", "port": 9000}, {"host": "env-host", "port": "7000"})\nassert s["host"] == "env-host" and s["port"] == 7000, "environment must override config"\ns = resolve({}, {"debug": "false"})\nassert s["debug"] is False, "boolean environment values must be parsed"\nassert endpoint({}, {"host": "api", "port": "443", "debug": "false"}) == "https://api:443"\nprint('{"score": 1.0, "summary": "settings precedence and coercion correct"}')\n''',
    )

    _make_task(
        "migration-config-v2",
        {
            "config.py": '''def parse_config(data: dict) -> dict:\n    if data.get("version", 1) != 1:\n        raise ValueError("unsupported version")\n    return {"endpoint": data["endpoint"], "timeout": int(data.get("timeout", 30))}\n''',
            "visible_test.py": '''from config import parse_config\nassert parse_config({"endpoint": "https://a"}) == {"endpoint": "https://a", "timeout": 30}\nprint("ok")\n''',
            "README.md": '''# Config formats\n\nv1 uses `endpoint` and optional `timeout`. New v2 documents use `url` and `request_timeout_ms`. The public parse_config return shape must remain endpoint + timeout seconds for existing callers.\n''',
        },
        '''import pathlib, sys\nroot = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root))\nfrom config import parse_config\nassert parse_config({"endpoint": "https://a", "timeout": 7}) == {"endpoint": "https://a", "timeout": 7}\nassert parse_config({"version": 2, "url": "https://b", "request_timeout_ms": 2500}) == {"endpoint": "https://b", "timeout": 2.5}\nassert parse_config({"version": 2, "url": "https://b"}) == {"endpoint": "https://b", "timeout": 30}\ntry:\n    parse_config({"version": 3, "url": "https://c"})\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError("unknown versions must remain rejected")\nprint('{"score": 1.0, "summary": "v2 migration is backward compatible"}')\n''',
    )

    _make_task(
        "infra-compose-health",
        {
            "compose.yaml": '''services:\n  api:\n    image: python:3.12-slim\n    command: python -m http.server 8080\n    ports:\n      - "${API_PORT:-8080}:8080"\n    healthcheck:\n      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]\n      interval: 30s\n      timeout: 5s\n      retries: 3\n''',
            "visible_test.py": '''from pathlib import Path\ntext = Path("compose.yaml").read_text()\nassert "healthcheck:" in text\nassert "retries:" in text\nprint("ok")\n''',
        },
        '''import pathlib, sys\ntext = (pathlib.Path(sys.argv[1]) / "compose.yaml").read_text()\nassert "127.0.0.1:8080" in text, "healthcheck must target the container port"\nassert "8000/health" not in text\nassert "${API_PORT:-8080}:8080" in text, "host port configurability must be preserved"\nassert "start_period:" in text, "service startup needs a healthcheck grace period"\nprint('{"score": 1.0, "summary": "compose healthcheck targets runtime correctly"}')\n''',
    )

    _make_task(
        "feature-ttl-cache",
        {
            "cache.py": '''class TTLCache:\n    def __init__(self, ttl_seconds, clock):\n        self.ttl_seconds = ttl_seconds\n        self.clock = clock\n        self._items = {}\n\n    def set(self, key, value):\n        self._items[key] = value\n\n    def get(self, key, default=None):\n        return self._items.get(key, default)\n''',
            "visible_test.py": '''from cache import TTLCache\nnow = [0.0]\nc = TTLCache(10, lambda: now[0])\nc.set("a", 1)\nassert c.get("a") == 1\nprint("ok")\n''',
        },
        '''import pathlib, sys\nroot = pathlib.Path(sys.argv[1]); sys.path.insert(0, str(root))\nfrom cache import TTLCache\nnow = [0.0]\nc = TTLCache(10, lambda: now[0])\nc.set("a", 1)\nnow[0] = 9.999\nassert c.get("a") == 1\nnow[0] = 10.0\nassert c.get("a") is None, "entry expires at ttl boundary"\nc.set("b", 2); now[0] = 15.0; c.set("b", 3); now[0] = 24.9\nassert c.get("b") == 3, "resetting key resets expiry"\nnow[0] = 25.0\nassert c.get("b", "missing") == "missing"\nassert "b" not in c._items, "expired entries should be evicted"\nprint('{"score": 1.0, "summary": "TTL behavior and eviction correct"}')\n''',
    )

    print(f"Prepared representative AvoGym corpus at {GENERATED}")


if __name__ == "__main__":
    main()

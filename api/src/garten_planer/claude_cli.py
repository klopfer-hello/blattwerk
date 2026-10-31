"""Claude Code CLI: runtime install and one-shot JSON runs (M5).

The CLI is proprietary (Anthropic) and never part of an image (repo rule; CI
checks it). The worker downloads the pinned version into its /claude volume at
start, from Anthropic's own release server, and verifies the SHA-256 against a
checksum pinned in our configuration (not only the one in the downloaded
manifest), then swaps it in atomically. Without CLI or token the app keeps
working; plan requests then fail with a clear German message.

`run_json` runs `claude -p` with no tools, no MCP and no slash commands, a
budget and a timeout, and returns the structured answer validated against a
JSON schema by the CLI (--json-schema) and again by Pydantic in the caller."""

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DOWNLOAD_BASE = "https://downloads.claude.ai/claude-code-releases"
PLATFORM = "linux-x64"


class ClaudeError(Exception):
    """Message is German and safe to show (no token, no prompt content)."""


class NotReady(ClaudeError):
    """Claude was not reached at all (no token, CLI not installed): costs nothing, counts nothing."""


@dataclass(frozen=True)
class CliConfig:
    version: str
    sha256: str
    root: Path  # the volume: bin/, config/, home/
    token: str = field(repr=False)  # never in a log line or traceback


def binary_path(cfg: CliConfig) -> Path:
    return cfg.root / "bin" / f"claude-{cfg.version}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_cli(cfg: CliConfig) -> Path:
    """Download and verify the pinned CLI once per volume and version (blocking)."""
    target = binary_path(cfg)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".download")
    url = f"{DOWNLOAD_BASE}/{cfg.version}/{PLATFORM}/claude"
    with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:  # noqa: S310 - fixed https URL
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if _sha256(tmp) != cfg.sha256:
        tmp.unlink(missing_ok=True)
        raise ClaudeError("Claude-Download hatte eine falsche Prüfsumme und wurde verworfen.")
    tmp.chmod(0o755)
    tmp.replace(target)
    for old in target.parent.glob("claude-*"):  # keep only the pinned version
        if old != target:
            old.unlink(missing_ok=True)
    return target


def _env(cfg: CliConfig) -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(cfg.root / "home"),
        "CLAUDE_CONFIG_DIR": str(cfg.root / "config"),
        "CLAUDE_CODE_OAUTH_TOKEN": cfg.token,
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "LANG": "C.UTF-8",
    }


async def run_json(
    cfg: CliConfig,
    prompt: str,
    system: str,
    schema: dict[str, Any],
    model: str = "sonnet",
    budget_usd: float = 0.50,
    timeout_s: int = 300,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(structured answer, run info: model, cost, duration). Raises ClaudeError."""
    if not cfg.token:
        raise NotReady("Die KI ist noch nicht eingerichtet (CLAUDE_CODE_OAUTH_TOKEN fehlt auf dem Server).")
    binary = binary_path(cfg)
    if not binary.exists():
        raise NotReady("Claude ist noch nicht installiert. Der Worker lädt es beim nächsten Start.")
    for d in ("home", "config"):
        (cfg.root / d).mkdir(parents=True, exist_ok=True)
    args = [
        str(binary), "-p", "--output-format", "json", "--model", model,
        "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
        "--permission-mode", "dontAsk",
        "--max-budget-usd", f"{budget_usd:.2f}", "--append-system-prompt", system,
        "--json-schema", json.dumps(schema),
    ]  # fmt: skip
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_env(cfg),
        cwd=str(cfg.root / "home"),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ClaudeError(f"Die KI hat nach {timeout_s} s nicht geantwortet.") from None
    return parse_result(out.decode(errors="replace"), proc.returncode or 0, err.decode(errors="replace"))


async def run_stream(
    cfg: CliConfig,
    prompt: str,
    system: str,
    mcp_servers: dict[str, Any],
    allowed: str,
    model: str = "sonnet",
    budget_usd: float = 0.30,
    timeout_s: int = 300,
    max_turns: int = 8,
    images: list[bytes] | None = None,
) -> AsyncGenerator[dict[str, Any]]:
    """`claude -p --output-format stream-json`: one parsed JSON event per line. Only the given
    MCP servers (strict), only `allowed` tools, no built-in tools, no session files. The MCP
    config (may carry the database URL for the server) lives in a private temp file that is
    removed afterwards. With `images` (JPEG) the prompt goes in as one stream-json user message
    with image blocks."""
    if not cfg.token:
        raise NotReady("Die KI ist noch nicht eingerichtet (CLAUDE_CODE_OAUTH_TOKEN fehlt auf dem Server).")
    binary = binary_path(cfg)
    if not binary.exists():
        raise NotReady("Claude ist noch nicht installiert. Der Worker lädt es beim nächsten Start.")
    for d in ("home", "config"):
        (cfg.root / d).mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="mcp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:  # mode 0600 from mkstemp
            json.dump({"mcpServers": mcp_servers}, f)
        args = [
            str(binary), "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--model", model, "--tools", "", "--strict-mcp-config", "--mcp-config", path,
            "--allowedTools", allowed, "--permission-mode", "dontAsk", "--disable-slash-commands",
            "--no-session-persistence", "--max-turns", str(max_turns), "--max-budget-usd", f"{budget_usd:.2f}",
            "--append-system-prompt", system,
        ]  # fmt: skip
        stdin = prompt.encode()
        if images:
            args += ["--input-format", "stream-json"]
            content: list[dict[str, Any]] = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(img).decode()}}
                for img in images
            ]  # fmt: skip
            content.append({"type": "text", "text": prompt})
            stdin = json.dumps({"type": "user", "message": {"role": "user", "content": content}}).encode() + b"\n"
        proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=_env(cfg), cwd=str(cfg.root / "home"), limit=4 * 1024 * 1024,
        )  # fmt: skip
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(stdin)
        await proc.stdin.drain()
        proc.stdin.close()
        deadline = asyncio.get_running_loop().time() + timeout_s
        try:
            while True:
                left = deadline - asyncio.get_running_loop().time()
                if left <= 0:
                    raise TimeoutError
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=left)
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    yield event
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            raise ClaudeError(f"Die KI hat nach {timeout_s} s nicht fertig geantwortet.") from None
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        if proc.returncode not in (0, None):
            raise ClaudeError("Die KI hat einen Fehler gemeldet. Bitte später nochmal versuchen.")
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


def parse_result(stdout: str, code: int, stderr: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The CLI's --output-format json envelope → (structured output, run info)."""
    try:
        env = json.loads(stdout)
    except json.JSONDecodeError:
        hint = "Anmeldung prüfen (Token)" if "auth" in (stdout + stderr).lower() else "unerwartete Ausgabe"
        raise ClaudeError(f"Die KI-Antwort war unlesbar ({hint}).") from None
    if env.get("is_error") or code != 0:
        sub = str(env.get("subtype", ""))
        if "budget" in sub:
            raise ClaudeError("Die KI hat das Kostenlimit für diese Anfrage erreicht.")
        if any(w in f"{env.get('result', '')} {stderr}".lower() for w in ("auth", "login", "token", "401")):
            raise ClaudeError("Die KI hat die Anmeldung abgelehnt (Token auf dem Server prüfen).")
        raise ClaudeError("Die KI hat einen Fehler gemeldet. Bitte später nochmal versuchen.")
    answer = env.get("structured_output")
    if not isinstance(answer, dict):
        try:
            answer = json.loads(env.get("result") or "")
        except (TypeError, json.JSONDecodeError):
            raise ClaudeError("Die KI hat kein gültiges JSON geliefert.") from None
    if not isinstance(answer, dict):
        raise ClaudeError("Die KI hat kein gültiges JSON geliefert.")
    info = {"cost_usd": env.get("total_cost_usd"), "duration_ms": env.get("duration_ms"),
            "model": next(iter(env.get("modelUsage") or {}), None)}  # fmt: skip
    return answer, info


def config_from_env() -> CliConfig:
    return CliConfig(
        version=os.environ.get("GP_CLAUDE_VERSION", ""),
        sha256=os.environ.get("GP_CLAUDE_SHA256", ""),
        root=Path(os.environ.get("GP_CLAUDE_HOME", "/claude")),
        token=os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""),
    )

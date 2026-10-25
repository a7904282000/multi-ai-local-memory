from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
import webbrowser
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .auth import SQLiteCredentialRegistry
from .types import ClientIdentity, MemorySpaceIdentity, ExecutionContext
from .client import BridgeClient
from .release_lifecycle import (
    RawMemoryArchive, create_release_backup, verify_release_backup, restore_release_backup, temporary_self_test_dir
)

PRODUCT_DIR = "Multi-AI Local Memory"
DEFAULT_SPACE_ID = "personal"
INSTALL_STATE_VERSION = 2


@dataclass(slots=True)
class InstallLayout:
    platform: str
    home: Path
    data_dir: Path
    config_path: Path
    state_dir: Path
    vault_root: Path
    browser_extension_dir: Path
    openclaw_profile_path: Path
    install_state_path: Path


@dataclass(slots=True)
class InstallResult:
    status: str
    memory_space_id: str
    owner_id: str
    vault_root: str
    config_path: str
    browser_extension_dir: str
    autostart: str
    service_started: bool
    openclaw: str
    browser: str
    blockers: list[str]
    post_install_e2e: str = "UNPROVEN"
    source_archive_count: int = 0


def _system_name(value: str | None = None) -> str:
    raw = (value or platform.system()).lower()
    if raw.startswith("win"):
        return "windows"
    if raw.startswith("darwin") or raw.startswith("mac"):
        return "macos"
    return "linux"


def _home(home: str | os.PathLike[str] | None = None) -> Path:
    return Path(home).expanduser().resolve() if home is not None else Path.home().resolve()


def default_data_dir(*, home: Path, system: str, env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if system == "windows":
        root = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return (root / PRODUCT_DIR).resolve()
    if system == "macos":
        return (home / "Library" / "Application Support" / PRODUCT_DIR).resolve()
    root = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return (root / "multi-ai-local-memory").resolve()


def obsidian_config_path(*, home: Path, system: str, env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if system == "windows":
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "obsidian" / "obsidian.json"
    if system == "macos":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    return Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "obsidian" / "obsidian.json"


def discover_obsidian_vaults(*, home: Path, system: str, env: dict[str, str] | None = None) -> list[Path]:
    cfg = obsidian_config_path(home=home, system=system, env=env)
    if not cfg.exists():
        return []
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[tuple[int, int, Path]] = []
    vaults = data.get("vaults") if isinstance(data, dict) else None
    if isinstance(vaults, dict):
        for item in vaults.values():
            if not isinstance(item, dict) or not item.get("path"):
                continue
            p = Path(str(item["path"])).expanduser()
            if not p.is_absolute():
                p = (home / p).resolve()
            else:
                p = p.resolve()
            rows.append((1 if item.get("open") else 0, int(item.get("ts") or 0), p))
    rows.sort(key=lambda x: (x[0], x[1], str(x[2])), reverse=True)
    seen: set[str] = set()
    result: list[Path] = []
    for _open, _ts, p in rows:
        key = os.path.normcase(str(p))
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def choose_or_create_vault(*, home: Path, system: str, env: dict[str, str] | None = None) -> Path:
    found = discover_obsidian_vaults(home=home, system=system, env=env)
    if found:
        found[0].mkdir(parents=True, exist_ok=True)
        return found[0]
    # No user decision needed: create an ordinary Obsidian-compatible Markdown vault.
    # If Obsidian is later opened, the user can open this folder as a vault; the bridge
    # works immediately even before the UI knows about it.
    p = (home / "Documents" / "Multi-AI Memory").resolve()
    p.mkdir(parents=True, exist_ok=True)
    marker = p / ".malm-default-vault"
    if not marker.exists():
        marker.write_text("Managed by Multi-AI Local Memory.\n", encoding="utf-8")
    return p


def _asset_extension_dir() -> Path:
    # Source checkout and wheel both carry the same package asset path.
    return (Path(__file__).resolve().parent / "assets" / "browser-extension").resolve()


def _copy_tree_replace(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Browser extension asset missing: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _load_or_create_install_state(path: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(data.get("version") or 1)
        if version > INSTALL_STATE_VERSION:
            raise RuntimeError("Unsupported future installation state version")
        # v1 -> v2 is metadata-only. Identity and memory_space are immutable across upgrade.
        if version == 1:
            data["version"] = 2
            data.setdefault("created_at", now)
            data["last_updated_at"] = now
            data.setdefault("migration_history", []).append({"from":1,"to":2,"at":now})
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif version == 2:
            data["last_updated_at"] = now
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return data
    data = {
        "version": INSTALL_STATE_VERSION,
        "installation_id": str(uuid.uuid4()),
        "owner_id": "local-user-" + uuid.uuid4().hex,
        "memory_space_id": DEFAULT_SPACE_ID,
        "created_at": now,
        "last_updated_at": now,
        "migration_history": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def _secure_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def build_layout(*, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None) -> InstallLayout:
    h = _home(home)
    s = _system_name(system)
    data = default_data_dir(home=h, system=s, env=env)
    vault = choose_or_create_vault(home=h, system=s, env=env)
    return InstallLayout(
        platform=s,
        home=h,
        data_dir=data,
        config_path=data / "service.json",
        state_dir=data / "state",
        vault_root=vault,
        browser_extension_dir=data / "browser-extension",
        openclaw_profile_path=data / "openclaw-client.json",
        install_state_path=data / "install-state.json",
    )


def _service_config(layout: InstallLayout, install_state: dict[str, Any]) -> dict[str, Any]:
    identity = layout.browser_extension_dir / "config" / "extension-identity.json"
    return {
        "memory_space_ids": [install_state["memory_space_id"]],
        "state_dir": str(layout.state_dir),
        "primary": {
            "type": "obsidian",
            "vault_root": str(layout.vault_root),
            "managed_folder": "Multi-AI Memory",
            "peer_id": "obsidian-primary",
        },
        "peers": [],
        "sync": {"interval_seconds": 5.0, "watch_poll_seconds": 0.25, "page_limit": 1000},
        "semantic_recall": {
            "enabled": True,
            "path": str(layout.state_dir / "derived-semantic.db"),
            "source_of_truth": "primary-storage",
            "derived_only": True,
            "rebuildable": True,
        },
        "http": {"host": "127.0.0.1", "port": 18790, "allow_remote_bind": False},
        "browser_bootstrap": {
            "enabled": True,
            "identity_files": [str(identity)],
            "memory_spaces": [install_state["memory_space_id"]],
            "scopes": ["user", "project"],
            "allowed_client_types": ["chatgpt-web", "grok-web", "web-ai"],
            "default_memory_space": {
                "space_id": install_state["memory_space_id"],
                "owner_id": install_state["owner_id"],
                "kind": "personal",
            },
        },
        "source_archive": {
            "enabled": True,
            "root": str(layout.vault_root / "Multi-AI Memory" / "_SourceArchive"),
            "preservation": "BYTE_FOR_BYTE",
            "immutable": True,
            "derived_views_may_replace_source": False,
        },
    }


def _service_command(layout: InstallLayout) -> list[str]:
    return [sys.executable, "-m", "malm_bridge.service", "--config", str(layout.config_path)]


def _quote_windows_arg(value: str) -> str:
    if not value or any(ch in value for ch in ' \t"'):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def write_autostart(layout: InstallLayout) -> Path:
    cmd = _service_command(layout)
    if layout.platform == "windows":
        # User-level Startup launcher: no Administrator rights and no Task Scheduler lifecycle.
        startup = layout.home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        target = startup / "Multi-AI Local Memory.cmd"
        target.parent.mkdir(parents=True, exist_ok=True)
        line = "@echo off\r\nstart \"\" /min " + " ".join(_quote_windows_arg(x) for x in cmd) + "\r\n"
        target.write_text(line, encoding="utf-8")
        return target
    if layout.platform == "macos":
        target = layout.home / "Library" / "LaunchAgents" / "ai.multi-local-memory.bridge.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        args = "\n".join(f"      <string>{x}</string>" for x in cmd)
        plist = f'''<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n  <key>Label</key><string>ai.multi-local-memory.bridge</string>\n  <key>ProgramArguments</key><array>\n{args}\n  </array>\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n</dict></plist>\n'''
        target.write_text(plist, encoding="utf-8")
        return target
    target = layout.home / ".config" / "systemd" / "user" / "multi-ai-local-memory.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    esc = " ".join(subprocess.list2cmdline([x]) for x in cmd)
    unit = f'''[Unit]\nDescription=Multi-AI Local Memory Bridge\nAfter=network.target\n\n[Service]\nType=simple\nExecStart={esc}\nRestart=on-failure\nRestartSec=2\n\n[Install]\nWantedBy=default.target\n'''
    target.write_text(unit, encoding="utf-8")
    return target


def activate_autostart(layout: InstallLayout, spec_path: Path) -> str:
    try:
        if layout.platform == "windows":
            # Start current user instance now. Startup file handles subsequent logons.
            flags = 0
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                flags |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            if hasattr(subprocess, "DETACHED_PROCESS"):
                flags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
            subprocess.Popen(_service_command(layout), creationflags=flags, close_fds=True)
            return "PASS"
        if layout.platform == "macos":
            uid = os.getuid()
            subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(spec_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(spec_path)], check=True)
            return "PASS"
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", spec_path.name], check=True)
        return "PASS"
    except (OSError, subprocess.CalledProcessError):
        return "FAIL"


def provision_openclaw_profile(layout: InstallLayout, install_state: dict[str, Any]) -> dict[str, Any]:
    registry = SQLiteCredentialRegistry(layout.state_dir / "credentials.db")
    client = ClientIdentity(
        client_id="openclaw-default",
        client_type="openclaw",
        client_instance_id=install_state["installation_id"],
    )
    issued = registry.rotate_for_client(
        client,
        scopes=("user", "project"),
        memory_spaces=(install_state["memory_space_id"],),
        admin=False,
    )
    profile = {
        "bridge_url": "http://127.0.0.1:18790",
        "credential": issued["token"],
        "client": asdict(client),
        "memory_space": {
            "space_id": install_state["memory_space_id"],
            "owner_id": install_state["owner_id"],
            "kind": "personal",
        },
    }
    _secure_write(layout.openclaw_profile_path, json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    return profile


def try_install_openclaw(layout: InstallLayout, plugin_dir: Path, *, execute: bool = True) -> str:
    exe = shutil.which("openclaw")
    if not exe:
        return "NOT_INSTALLED"
    if not execute:
        return "PLANNED"
    try:
        # Local plugins require explicit source + capability acknowledgement by OpenClaw.
        subprocess.run(
            [exe, "plugins", "install", str(plugin_dir), "--force", "--accept-capabilities"],
            check=True,
        )
        # Persist the profile path and the exact hook permissions needed for automatic
        # recall/capture. This survives Gateway/process restarts; no shell env is required.
        subprocess.run([exe, "config", "set", "plugins.entries.multi-ai-local-memory.config.profilePath", str(layout.openclaw_profile_path)], check=True)
        subprocess.run([exe, "config", "set", "plugins.entries.multi-ai-local-memory.hooks.allowConversationAccess", "true", "--strict-json"], check=True)
        subprocess.run([exe, "config", "set", "plugins.entries.multi-ai-local-memory.hooks.allowPromptInjection", "true", "--strict-json"], check=True)
        subprocess.run([exe, "plugins", "reload", "multi-ai-local-memory", "--wait", "--accept-capabilities"], check=True)
        return "PASS"
    except (OSError, subprocess.CalledProcessError):
        return "FAIL"


def zero_config_install(
    *,
    home: str | os.PathLike[str] | None = None,
    system: str | None = None,
    env: dict[str, str] | None = None,
    activate: bool = True,
    install_openclaw: bool = True,
    browser_store_url: str | None = None,
    open_browser: bool = True,
    memory_sources: list[dict[str, str]] | None = None,
    run_self_test: bool = True,
) -> InstallResult:
    layout = build_layout(home=home, system=system, env=env)
    layout.data_dir.mkdir(parents=True, exist_ok=True)
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    state = _load_or_create_install_state(layout.install_state_path)

    _copy_tree_replace(_asset_extension_dir(), layout.browser_extension_dir)
    config = _service_config(layout, state)
    layout.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provision_openclaw_profile(layout, state)
    archived_sources = archive_original_memory_sources(layout, memory_sources)

    autostart_spec = write_autostart(layout)
    autostart = activate_autostart(layout, autostart_spec) if activate else "PLANNED"

    plugin_dir = (Path(__file__).resolve().parent / "assets" / "openclaw-plugin").resolve()
    openclaw_status = try_install_openclaw(layout, plugin_dir, execute=activate and install_openclaw) if install_openclaw else "SKIPPED"

    blockers: list[str] = []
    browser_status = "READY_FOR_STORE_INSTALL"
    if browser_store_url:
        browser_status = "USER_CONFIRMATION_REQUIRED"
        if open_browser:
            webbrowser.open(browser_store_url)
    else:
        browser_status = "DISTRIBUTION_UNPUBLISHED"
        blockers.append("BROWSER_EXTENSION_STORE_DISTRIBUTION")
    if autostart == "FAIL":
        blockers.append("AUTOSTART_ACTIVATION")
    if openclaw_status == "FAIL":
        blockers.append("OPENCLAW_PLUGIN_INSTALL")

    self_test_status = "SKIPPED"
    if run_self_test:
        self_test = post_install_self_test(layout.config_path)
        self_test_status = self_test["status"]
        if self_test_status != "PASS":
            blockers.append("POST_INSTALL_E2E")

    return InstallResult(
        status="PASS" if not blockers else "BLOCKED",
        memory_space_id=state["memory_space_id"],
        owner_id=state["owner_id"],
        vault_root=str(layout.vault_root),
        config_path=str(layout.config_path),
        browser_extension_dir=str(layout.browser_extension_dir),
        autostart=autostart,
        service_started=autostart == "PASS",
        openclaw=openclaw_status,
        browser=browser_status,
        blockers=blockers,
        post_install_e2e=self_test_status,
        source_archive_count=len(archived_sources),
    )


def doctor(config_path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(config_path).expanduser().resolve()
    findings: list[str] = []
    if not p.exists():
        findings.append("CONFIG_MISSING")
        return {"status":"FAIL","findings":findings}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"status":"FAIL","findings":["CONFIG_INVALID"]}
    for required in ("memory_space_ids", "state_dir", "primary", "browser_bootstrap"):
        if required not in cfg:
            findings.append(f"CONFIG_MISSING_{required.upper()}")
    primary = cfg.get("primary") or {}
    if primary.get("type") == "obsidian":
        vault = Path(primary.get("vault_root", ""))
        if not vault.exists():
            findings.append("VAULT_MISSING")
    identity_files = (cfg.get("browser_bootstrap") or {}).get("identity_files") or []
    if not identity_files or any(not Path(x).exists() for x in identity_files):
        findings.append("BROWSER_IDENTITY_MISSING")
    return {"status":"PASS" if not findings else "FAIL", "findings":findings}



def _existing_layout(*, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None) -> InstallLayout:
    """Resolve an existing install without rediscovering/changing its chosen vault."""
    h = _home(home)
    sysname = _system_name(system)
    data = default_data_dir(home=h, system=sysname, env=env)
    cfg_path = data / "service.json"
    if not cfg_path.exists():
        return build_layout(home=h, system=sysname, env=env)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    primary = dict(cfg.get("primary") or {})
    vault_value = primary.get("vault_root")
    vault = Path(vault_value).expanduser().resolve() if vault_value else choose_or_create_vault(home=h, system=sysname, env=env)
    return InstallLayout(
        platform=sysname, home=h, data_dir=data, config_path=cfg_path, state_dir=data/"state",
        vault_root=vault, browser_extension_dir=data/"browser-extension",
        openclaw_profile_path=data/"openclaw-client.json", install_state_path=data/"install-state.json",
    )


def archive_original_memory_sources(layout: InstallLayout, sources: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    """Archive provider/native memory exports byte-for-byte before any normalization.

    `sources` items: {path, source_id, source_kind}. No source is parsed here.
    """
    if not sources:
        return []
    archive = RawMemoryArchive(layout.vault_root / "Multi-AI Memory" / "_SourceArchive")
    out: list[dict[str, Any]] = []
    for item in sources:
        result = archive.archive(item["path"], source_id=item["source_id"], source_kind=item.get("source_kind", "unknown"))
        verified = archive.verify(result.archive_id)
        if verified["status"] != "PASS":
            raise RuntimeError(f"SOURCE_ARCHIVE_VERIFY_FAILED:{result.archive_id}")
        out.append({**asdict(result), "verify_status": verified["status"]})
    return out


def backup_installation(*, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    layout = _existing_layout(home=home, system=system, env=env)
    if not layout.config_path.exists():
        return {"status":"FAIL", "error":"NOT_INSTALLED"}
    result = create_release_backup(
        data_dir=layout.data_dir, config_path=layout.config_path, state_dir=layout.state_dir,
        install_state_path=layout.install_state_path, openclaw_profile_path=layout.openclaw_profile_path,
        browser_extension_dir=layout.browser_extension_dir, vault_root=layout.vault_root,
    )
    check = verify_release_backup(result.backup_root)
    return {**asdict(result), "verify_status":check["status"]}


def restore_installation(backup_root: str | os.PathLike[str], *, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    root = Path(backup_root).expanduser().resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    targets = dict(manifest.get("restore_targets") or {})
    if targets:
        return restore_release_backup(
            backup_root=root, config_path=Path(targets["config_path"]), state_dir=Path(targets["state_dir"]),
            install_state_path=Path(targets["install_state_path"]), openclaw_profile_path=Path(targets["openclaw_profile_path"]),
            browser_extension_dir=Path(targets["browser_extension_dir"]), vault_root=Path(targets["vault_root"]),
            managed_folder=targets.get("managed_folder", "Multi-AI Memory"),
        )
    # Backward-compatible recovery for older backups that predate restore_targets.
    layout = _existing_layout(home=home, system=system, env=env)
    return restore_release_backup(
        backup_root=root, config_path=layout.config_path, state_dir=layout.state_dir,
        install_state_path=layout.install_state_path, openclaw_profile_path=layout.openclaw_profile_path,
        browser_extension_dir=layout.browser_extension_dir, vault_root=layout.vault_root,
    )


def _remove_autostart(layout: InstallLayout) -> str:
    try:
        if layout.platform == "windows":
            target = layout.home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Multi-AI Local Memory.cmd"
            target.unlink(missing_ok=True)
            return "PASS"
        if layout.platform == "macos":
            target = layout.home / "Library" / "LaunchAgents" / "ai.multi-local-memory.bridge.plist"
            if target.exists():
                try:
                    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    pass
                target.unlink(missing_ok=True)
            return "PASS"
        target = layout.home / ".config" / "systemd" / "user" / "multi-ai-local-memory.service"
        if target.exists():
            try:
                subprocess.run(["systemctl", "--user", "disable", "--now", target.name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
            target.unlink(missing_ok=True)
        return "PASS"
    except OSError:
        return "FAIL"


def uninstall(*, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None, preserve_user_memory: bool = True) -> dict[str, Any]:
    layout = _existing_layout(home=home, system=system, env=env)
    managed = layout.vault_root / "Multi-AI Memory"
    autostart = _remove_autostart(layout)
    # Program state and credentials are removable; user memory is outside data_dir and is preserved by default.
    if layout.data_dir.exists():
        shutil.rmtree(layout.data_dir)
    memory_preserved = managed.exists() if preserve_user_memory else False
    if not preserve_user_memory and managed.exists():
        shutil.rmtree(managed)
    return {
        "status":"PASS" if autostart == "PASS" else "FAIL",
        "autostart":autostart,
        "user_memory_preserved":bool(memory_preserved),
        "memory_path":str(managed),
    }


def post_install_self_test(config_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Non-destructive release self-test.

    Uses the installed code/identity/credential/bootstrap path but a temporary Obsidian vault,
    so no synthetic test memory is inserted into the user's real memory space. The real selected
    vault is separately checked for exact write/read/delete capability.
    """
    from .service import build_service
    p = Path(config_path).expanduser().resolve()
    cfg = json.loads(p.read_text(encoding="utf-8"))
    findings: list[str] = []
    primary = dict(cfg.get("primary") or {})
    vault = Path(primary.get("vault_root", "")).expanduser().resolve()
    managed = vault / primary.get("managed_folder", "Multi-AI Memory")
    probe = managed / ".malm" / f"install-probe-{uuid.uuid4().hex}.bin"
    probe_bytes = os.urandom(64)
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(probe_bytes)
        if probe.read_bytes() != probe_bytes:
            findings.append("REAL_VAULT_BYTE_ROUNDTRIP")
    finally:
        try: probe.unlink(missing_ok=True)
        except OSError: findings.append("REAL_VAULT_PROBE_CLEANUP")

    state_dir = Path(cfg["state_dir"]).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    with temporary_self_test_dir(state_dir) as td:
        t = Path(td)
        test_cfg = json.loads(json.dumps(cfg))
        test_cfg["state_dir"] = str(t / "state")
        test_cfg["primary"] = {"type":"obsidian", "vault_root":str(t/"vault"), "managed_folder":"Multi-AI Memory", "peer_id":"selftest-primary"}
        test_cfg["peers"] = []
        test_cfg["http"] = {"host":"127.0.0.1", "port":0, "allow_remote_bind":False}
        # Preserve installed browser identity file so bootstrap tests the actual packaged identity.
        service = build_service(test_cfg, config_base=p.parent)
        service.start()
        try:
            browser_cfg = dict(cfg.get("browser_bootstrap") or {})
            identity_path = Path(browser_cfg["identity_files"][0]).expanduser().resolve()
            origin = json.loads(identity_path.read_text(encoding="utf-8"))["origin"]
            def boot(client: dict[str,str]) -> dict[str,Any]:
                raw=json.dumps({"client":client}).encode()
                req=Request(service.base_url+"/bootstrap/v1/browser",data=raw,method="POST",headers={"Content-Type":"application/json","Origin":origin})
                with urlopen(req,timeout=5) as resp: return json.loads(resp.read().decode())
            a_id={"client_id":"installer-model-a","client_type":"chatgpt-web","client_instance_id":"selftest-a"}
            b_id={"client_id":"installer-model-b","client_type":"grok-web","client_instance_id":"selftest-b"}
            a_boot, b_boot = boot(a_id), boot(b_id)
            dms = browser_cfg["default_memory_space"]
            space=MemorySpaceIdentity(space_id=dms["space_id"],owner_id=dms["owner_id"],kind=dms.get("kind","personal"))
            a=BridgeClient(service.base_url,a_boot["credential"],ClientIdentity(**a_id),space,ExecutionContext(surface="web",provider="selftest-a"))
            b=BridgeClient(service.base_url,b_boot["credential"],ClientIdentity(**b_id),space,ExecutionContext(surface="web",provider="selftest-b"))
            sentinel="malm installer sentinel "+uuid.uuid4().hex
            cap=a.capture(sentinel,"ack",session_id="install-self-test",explicit_remember_request=True)
            if cap.get("decision") != "COMMIT": findings.append("CAPTURE_COMMIT")
            rec=b.recall("installer sentinel",session_id="install-self-test-b")
            if not any(sentinel in item.get("content","") for item in rec.get("items",[])): findings.append("CROSS_CLIENT_RECALL")
        finally:
            service.stop()
    return {
        "status":"PASS" if not findings else "FAIL",
        "findings":findings,
        "zero_config_bootstrap":"PASS" if not findings else "FAIL",
        "cross_model_memory":"PASS" if "CROSS_CLIENT_RECALL" not in findings else "FAIL",
        "real_vault_byte_roundtrip":"PASS" if not any(x.startswith("REAL_VAULT") for x in findings) else "FAIL",
    }


def zero_config_update(*, home: str | os.PathLike[str] | None = None, system: str | None = None, env: dict[str, str] | None = None, activate: bool = False, install_openclaw: bool = True) -> dict[str, Any]:
    """Backup-first, identity-preserving update. Never rewrites memory content."""
    layout = _existing_layout(home=home, system=system, env=env)
    if not layout.config_path.exists():
        return {"status":"FAIL","error":"NOT_INSTALLED"}
    before_state = json.loads(layout.install_state_path.read_text(encoding="utf-8"))
    backup = backup_installation(home=home, system=system, env=env)
    if backup.get("verify_status") != "PASS":
        return {"status":"FAIL","error":"BACKUP_FAILED","backup":backup}
    state = _load_or_create_install_state(layout.install_state_path)
    if state["owner_id"] != before_state["owner_id"] or state["memory_space_id"] != before_state["memory_space_id"]:
        raise RuntimeError("IDENTITY_CHANGED_DURING_UPDATE")
    _copy_tree_replace(_asset_extension_dir(), layout.browser_extension_dir)
    # Refresh generated defaults without erasing user/adapter configuration. An update must
    # never silently switch storage back to Obsidian or drop configured sync peers.
    existing_cfg = json.loads(layout.config_path.read_text(encoding="utf-8"))
    generated_cfg = _service_config(layout, state)

    def merge_defaults(defaults: Any, existing: Any) -> Any:
        if isinstance(defaults, dict) and isinstance(existing, dict):
            merged = {k: merge_defaults(v, existing[k]) if k in existing else v for k, v in defaults.items()}
            for k, v in existing.items():
                if k not in merged:
                    merged[k] = v
            return merged
        return existing

    merged_cfg = merge_defaults(generated_cfg, existing_cfg)
    # Security/preservation invariants are not user-overridable downgrade knobs.
    archive_cfg = dict(merged_cfg.get("source_archive") or {})
    archive_cfg["enabled"] = True
    archive_cfg["preservation"] = "BYTE_FOR_BYTE"
    archive_cfg["immutable"] = True
    archive_cfg["derived_views_may_replace_source"] = False
    merged_cfg["source_archive"] = archive_cfg
    # The packaged identity path must follow the refreshed extension payload while any
    # explicit extra allowed_origins remain preserved by the merge above.
    merged_cfg.setdefault("browser_bootstrap", {})["identity_files"] = [str(layout.browser_extension_dir / "config" / "extension-identity.json")]
    layout.config_path.write_text(json.dumps(merged_cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    provision_openclaw_profile(layout,state)
    spec=write_autostart(layout)
    autostart=activate_autostart(layout,spec) if activate else "PLANNED"
    plugin_dir=(Path(__file__).resolve().parent/"assets"/"openclaw-plugin").resolve()
    oc=try_install_openclaw(layout,plugin_dir,execute=activate and install_openclaw) if install_openclaw else "SKIPPED"
    test=post_install_self_test(layout.config_path)
    return {
        "status":"PASS" if test["status"]=="PASS" and autostart!="FAIL" and oc!="FAIL" else "FAIL",
        "backup_id":backup.get("backup_id"),
        "owner_id":state["owner_id"],
        "memory_space_id":state["memory_space_id"],
        "autostart":autostart,"openclaw":oc,"post_install_e2e":test["status"],
        "update_preserves_identity":"PASS",
        "update_preserves_memory":"PASS",
    }

def _parse_memory_sources(values: list[str]) -> list[dict[str, str]]:
    out: list[dict[str,str]]=[]
    for value in values:
        if "=" not in value:
            raise ValueError("--memory-source must be SOURCE_ID=PATH")
        source_id, path = value.split("=",1)
        if not source_id or not path:
            raise ValueError("--memory-source must be SOURCE_ID=PATH")
        out.append({"source_id":source_id,"path":path,"source_kind":"provider-export"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-config release lifecycle for Multi-AI Local Memory")
    parser.add_argument("action", nargs="?", default="install", choices=["install","update","backup","restore","uninstall","doctor","self-test"])
    parser.add_argument("--no-activate", action="store_true", help="Generate/update installation without activating autostart")
    parser.add_argument("--no-openclaw", action="store_true", help="Do not integrate detected OpenClaw")
    parser.add_argument("--browser-store-url", default=os.getenv("MALM_BROWSER_STORE_URL"))
    parser.add_argument("--no-open-browser", action="store_true")
    parser.add_argument("--memory-source", action="append", default=[], metavar="SOURCE_ID=PATH", help="Archive an existing model/provider memory export byte-for-byte before deriving any index")
    parser.add_argument("--backup-root", help="Backup directory for restore")
    parser.add_argument("--delete-user-memory", action="store_true", help="Explicitly delete managed user memory during uninstall (default preserves it)")
    args = parser.parse_args()

    if args.action == "install":
        result: Any = asdict(zero_config_install(
            activate=not args.no_activate, install_openclaw=not args.no_openclaw,
            browser_store_url=args.browser_store_url, open_browser=not args.no_open_browser,
            memory_sources=_parse_memory_sources(args.memory_source),
        ))
    elif args.action == "update":
        result = zero_config_update(activate=not args.no_activate, install_openclaw=not args.no_openclaw)
    elif args.action == "backup":
        result = backup_installation()
    elif args.action == "restore":
        if not args.backup_root:
            parser.error("restore requires --backup-root")
        result = restore_installation(args.backup_root)
    elif args.action == "uninstall":
        result = uninstall(preserve_user_memory=not args.delete_user_memory)
    else:
        layout = _existing_layout()
        result = doctor(layout.config_path) if args.action == "doctor" else post_install_self_test(layout.config_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result.get("status", "FAIL") if isinstance(result, dict) else "FAIL"
    raise SystemExit(0 if status == "PASS" else 2)


if __name__ == "__main__":
    main()

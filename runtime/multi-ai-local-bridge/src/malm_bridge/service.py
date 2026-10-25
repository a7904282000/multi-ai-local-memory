from __future__ import annotations

import argparse
import importlib
import json
import signal
import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .auth import SQLiteCredentialRegistry
from .browser_bootstrap import BrowserBootstrapController, BrowserBootstrapPolicy
from .core import BridgeCore
from .http_server import BridgeHandler
from .state import SQLiteBridgeStateStore
from .semantic import DerivedSemanticIndex
from .storage.obsidian import ObsidianStorageAdapter
from .storage.sqlite import SQLiteStorageAdapter
from .sync import MemorySyncCoordinator, SyncPeerAdapter
from .sync_runtime import ProductionSyncRuntime, SyncRuntimeStateStore


def _resolve_path(value: str, base: Path) -> Path:
    p = Path(value).expanduser()
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def _browser_origins(browser_cfg: dict[str, Any], base: Path) -> list[str]:
    origins = list(browser_cfg.get("allowed_origins") or [])
    for value in browser_cfg.get("identity_files") or []:
        path = _resolve_path(str(value), base)
        data = json.loads(path.read_text(encoding="utf-8"))
        origin = data.get("origin")
        if not isinstance(origin, str) or not origin.startswith(("chrome-extension://", "moz-extension://")):
            raise ValueError(f"Invalid browser extension identity file: {path}")
        origins.append(origin.rstrip("/"))
    # deterministic deduplication, no manual ID maintenance required.
    return sorted(set(origins))


def _load_factory(ref: str) -> Callable[[dict[str, Any]], Any]:
    if ":" not in ref:
        raise ValueError("Custom adapter factory must be module.path:callable")
    module_name, attr = ref.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    if not callable(factory):
        raise TypeError(f"Adapter factory is not callable: {ref}")
    return factory


def build_storage(spec: dict[str, Any], base: Path):
    kind = spec.get("type")
    if kind == "sqlite":
        return SQLiteStorageAdapter(_resolve_path(spec["path"], base))
    if kind == "obsidian":
        return ObsidianStorageAdapter(
            _resolve_path(spec["vault_root"], base),
            managed_folder=spec.get("managed_folder", "Multi-AI Memory"),
            peer_id=spec.get("peer_id", "obsidian-primary"),
        )
    if kind == "python":
        return _load_factory(spec["factory"])(dict(spec.get("config") or {}))
    raise ValueError(f"Unsupported primary storage type: {kind!r}")


def build_peer(spec: dict[str, Any], base: Path) -> SyncPeerAdapter:
    kind = spec.get("type")
    if kind == "obsidian":
        return ObsidianStorageAdapter(
            _resolve_path(spec["vault_root"], base),
            managed_folder=spec.get("managed_folder", "Multi-AI Memory"),
            peer_id=spec.get("peer_id", "obsidian"),
        )
    if kind == "python":
        return _load_factory(spec["factory"])(dict(spec.get("config") or {}))
    raise ValueError(f"Unsupported sync peer type: {kind!r}")


@dataclass(slots=True)
class BridgeService:
    core: BridgeCore
    auth: SQLiteCredentialRegistry
    runtime: ProductionSyncRuntime
    server: ThreadingHTTPServer
    http_thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        if self.http_thread and self.http_thread.is_alive():
            return
        self.runtime.start()
        self.http_thread = threading.Thread(target=self.server.serve_forever, name="malm-http", daemon=True)
        self.http_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.http_thread:
            self.http_thread.join(timeout)
            if self.http_thread.is_alive():
                raise RuntimeError("HTTP server did not stop within timeout")
        self.runtime.stop(timeout)

    def health(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.runtime.health()["status"] in {"PASS", "STOPPED"} else "DEGRADED",
            "bridge": self.core.health(),
            "sync_runtime": self.runtime.health(),
            "auth": self.auth.health(),
            "http": {"host": self.server.server_address[0], "port": self.server.server_address[1]},
        }


def build_service(config: dict[str, Any], *, config_base: Path | None = None) -> BridgeService:
    base = (config_base or Path.cwd()).resolve()
    spaces = config.get("memory_space_ids")
    if not isinstance(spaces, list) or not spaces or not all(isinstance(x, str) and x for x in spaces):
        raise ValueError("memory_space_ids must be a non-empty string array")

    state_dir = _resolve_path(config.get("state_dir", ".malm-state"), base)
    state_dir.mkdir(parents=True, exist_ok=True)
    primary = build_storage(dict(config.get("primary") or {}), base)
    peers = [build_peer(dict(x), base) for x in (config.get("peers") or [])]
    auth = SQLiteCredentialRegistry(state_dir / "credentials.db")
    bridge_state = SQLiteBridgeStateStore(state_dir / "bridge-state.db")
    sync_state = SyncRuntimeStateStore(state_dir / "sync-runtime.db")
    runtime_cfg = dict(config.get("sync") or {})
    runtime = ProductionSyncRuntime(
        MemorySyncCoordinator(primary),
        peers,
        spaces,
        sync_state,
        sync_interval_seconds=float(runtime_cfg.get("interval_seconds", 5.0)),
        watch_poll_seconds=float(runtime_cfg.get("watch_poll_seconds", 0.25)),
        page_limit=int(runtime_cfg.get("page_limit", 1000)),
    )
    semantic_cfg = dict(config.get("semantic_recall") or {})
    semantic_index = None
    if semantic_cfg.get("enabled", True):
        semantic_path = _resolve_path(semantic_cfg.get("path", str(state_dir / "derived-semantic.db")), base)
        semantic_index = DerivedSemanticIndex(semantic_path, primary)
    core = BridgeCore(primary, auth, state=bridge_state, change_notifier=runtime.notify, semantic_index=semantic_index)

    http_cfg = dict(config.get("http") or {})
    host = str(http_cfg.get("host", "127.0.0.1"))
    port = int(http_cfg.get("port", 18790))
    allow_remote = bool(http_cfg.get("allow_remote_bind", False))
    if host not in {"127.0.0.1", "::1", "localhost"} and not allow_remote:
        raise ValueError("Refusing non-loopback bind without http.allow_remote_bind=true")
    server = ThreadingHTTPServer((host, port), BridgeHandler)
    server.core = core  # type: ignore[attr-defined]

    browser_cfg = dict(config.get("browser_bootstrap") or {})
    if browser_cfg.get("enabled", False):
        origins = _browser_origins(browser_cfg, base)
        if not origins:
            raise ValueError("browser_bootstrap requires allowed_origins or identity_files when enabled")
        server.browser_bootstrap = BrowserBootstrapController(  # type: ignore[attr-defined]
            auth,
            BrowserBootstrapPolicy.build(
                allowed_origins=origins,
                memory_spaces=browser_cfg.get("memory_spaces") or spaces,
                scopes=browser_cfg.get("scopes") or ["user", "project"],
                allowed_client_types=browser_cfg.get("allowed_client_types") or ["chatgpt-web", "grok-web", "web-ai"],
                default_memory_space=browser_cfg.get("default_memory_space"),
            ),
        )
    return BridgeService(core=core, auth=auth, runtime=runtime, server=server)


def load_service(config_path: str | Path) -> BridgeService:
    path = Path(config_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Service config root must be an object")
    return build_service(data, config_base=path.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-AI Local Bridge production service")
    parser.add_argument("--config", required=True, help="Path to service JSON config")
    args = parser.parse_args()
    service = load_service(args.config)
    stop_event = threading.Event()

    def _stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    service.start()
    try:
        while not stop_event.wait(1.0):
            pass
    finally:
        service.stop()


if __name__ == "__main__":
    main()

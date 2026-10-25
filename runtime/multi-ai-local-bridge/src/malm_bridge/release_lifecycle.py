from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RAW_ARCHIVE_FORMAT_VERSION = 1
BACKUP_FORMAT_VERSION = 1


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(value: str) -> str:
    out = "".join(c if c.isalnum() or c in "._-" else "_" for c in value).strip("._")
    return (out or "source")[:120]


def _iter_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            yield p


@dataclass(slots=True)
class RawArchiveResult:
    archive_id: str
    source_id: str
    source_kind: str
    archive_root: str
    source_file_count: int
    archived_file_count: int
    source_bytes: int
    archived_bytes: int
    hash_match_count: int
    preservation: str = "BYTE_FOR_BYTE"
    source_mutated: bool = False


class RawMemoryArchive:
    """Immutable source-preservation layer for imported/native model memories.

    This class deliberately does not parse, summarize, normalize, deduplicate, merge or
    rewrite source memories. It first stores exact source bytes under a content-addressed
    archive entry and records a SHA-256 manifest. Any MemoryAtom/semantic index is a
    *derived* view and can never replace this archive.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def archive(self, source: str | os.PathLike[str], *, source_id: str, source_kind: str = "unknown") -> RawArchiveResult:
        src = Path(source).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(src)
        if src.is_symlink():
            raise ValueError("Source root symlinks are not accepted for immutable migration")

        archive_id = f"src-{_safe_name(source_id)}-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        dst_root = self.root / archive_id
        payload_root = dst_root / "payload"
        payload_root.mkdir(parents=True, exist_ok=False)

        rows: list[dict[str, Any]] = []
        source_bytes = archived_bytes = 0
        hash_match_count = 0

        if src.is_file():
            inputs = [(Path(src.name), src)]
            source_type = "file"
        elif src.is_dir():
            inputs = [(p.relative_to(src), p) for p in _iter_files(src)]
            source_type = "directory"
        else:
            raise ValueError(f"Unsupported memory source type: {src}")

        # Snapshot source fingerprints before copying so we can prove we never changed it.
        source_fingerprints = {str(rel): (_sha256_file(p), p.stat().st_size) for rel, p in inputs}

        for rel, source_file in inputs:
            target = payload_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # copyfile is byte-for-byte. Do not newline-normalize, decode or reserialize.
            shutil.copyfile(source_file, target)
            src_hash, src_size = source_fingerprints[str(rel)]
            dst_hash = _sha256_file(target)
            dst_size = target.stat().st_size
            source_bytes += src_size
            archived_bytes += dst_size
            if src_hash != dst_hash or src_size != dst_size:
                raise RuntimeError(f"RAW_ARCHIVE_HASH_MISMATCH: {rel}")
            hash_match_count += 1
            rows.append({
                "relative_path": rel.as_posix(),
                "size_bytes": src_size,
                "sha256": src_hash,
            })

        # Verify the source itself did not change during migration.
        for rel, source_file in inputs:
            before_hash, before_size = source_fingerprints[str(rel)]
            if source_file.stat().st_size != before_size or _sha256_file(source_file) != before_hash:
                raise RuntimeError(f"SOURCE_MUTATED_DURING_ARCHIVE: {rel}")

        manifest = {
            "format_version": RAW_ARCHIVE_FORMAT_VERSION,
            "archive_id": archive_id,
            "source_id": source_id,
            "source_kind": source_kind,
            "source_type": source_type,
            "source_name": src.name,
            # Intentionally do not persist the original absolute path: it can contain private
            # machine/user names and is not needed to prove byte preservation.
            "created_at": datetime.now(timezone.utc).isoformat(),
            "preservation": "BYTE_FOR_BYTE",
            "immutable_source": True,
            "derived_views_may_replace_source": False,
            "file_count": len(rows),
            "total_bytes": source_bytes,
            "files": rows,
        }
        (dst_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Make archive payload read-only on a best-effort basis. Integrity is always
        # enforced by the manifest hashes even on platforms that ignore POSIX modes.
        for p in payload_root.rglob("*"):
            try:
                p.chmod(0o555 if p.is_dir() else 0o444)
            except OSError:
                pass

        return RawArchiveResult(
            archive_id=archive_id,
            source_id=source_id,
            source_kind=source_kind,
            archive_root=str(dst_root),
            source_file_count=len(rows),
            archived_file_count=len(rows),
            source_bytes=source_bytes,
            archived_bytes=archived_bytes,
            hash_match_count=hash_match_count,
        )

    def verify(self, archive_id: str) -> dict[str, Any]:
        root = (self.root / archive_id).resolve()
        if self.root not in root.parents:
            raise ValueError("archive_id escaped archive root")
        manifest_path = root / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        failures: list[str] = []
        for item in data.get("files", []):
            rel = Path(item["relative_path"])
            p = (root / "payload" / rel).resolve()
            if (root / "payload").resolve() not in p.parents and p != (root / "payload").resolve():
                failures.append(f"PATH_ESCAPE:{rel}")
                continue
            if not p.is_file():
                failures.append(f"MISSING:{rel}")
                continue
            if p.stat().st_size != int(item["size_bytes"]):
                failures.append(f"SIZE:{rel}")
            if _sha256_file(p) != item["sha256"]:
                failures.append(f"HASH:{rel}")
        return {
            "status": "PASS" if not failures else "FAIL",
            "archive_id": archive_id,
            "preservation": data.get("preservation"),
            "file_count": data.get("file_count", 0),
            "failures": failures,
        }


@dataclass(slots=True)
class BackupResult:
    backup_id: str
    backup_root: str
    file_count: int
    total_bytes: int
    status: str = "PASS"


def _copy_with_manifest(src: Path, dst: Path, logical_root: str, rows: list[dict[str, Any]]) -> None:
    if not src.exists():
        return
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        rows.append({
            "logical_root": logical_root,
            "relative_path": src.name,
            "size_bytes": src.stat().st_size,
            "sha256": _sha256_file(src),
        })
        return
    for p in _iter_files(src):
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        rows.append({
            "logical_root": logical_root,
            "relative_path": rel.as_posix(),
            "size_bytes": p.stat().st_size,
            "sha256": _sha256_file(p),
        })


def create_release_backup(*, data_dir: Path, config_path: Path, state_dir: Path, install_state_path: Path,
                          openclaw_profile_path: Path, browser_extension_dir: Path, vault_root: Path,
                          managed_folder: str = "Multi-AI Memory") -> BackupResult:
    backup_id = f"backup-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    backup_root = data_dir / "backups" / backup_id
    payload = backup_root / "payload"
    rows: list[dict[str, Any]] = []
    mapping = [
        (config_path, payload / "config" / config_path.name, "config"),
        (install_state_path, payload / "install" / install_state_path.name, "install_state"),
        (state_dir, payload / "state", "state"),
        (openclaw_profile_path, payload / "openclaw" / openclaw_profile_path.name, "openclaw_profile"),
        (browser_extension_dir, payload / "browser-extension", "browser_extension"),
        (vault_root / managed_folder, payload / "managed-memory", "managed_memory"),
    ]
    for src, dst, logical in mapping:
        _copy_with_manifest(src, dst, logical, rows)
    manifest = {
        "format_version": BACKUP_FORMAT_VERSION,
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(rows),
        "total_bytes": sum(int(x["size_bytes"]) for x in rows),
        "files": rows,
        # Local recovery metadata. Restore must not depend on the *current* config being readable.
        "restore_targets": {
            "config_path": str(config_path.resolve()),
            "state_dir": str(state_dir.resolve()),
            "install_state_path": str(install_state_path.resolve()),
            "openclaw_profile_path": str(openclaw_profile_path.resolve()),
            "browser_extension_dir": str(browser_extension_dir.resolve()),
            "vault_root": str(vault_root.resolve()),
            "managed_folder": managed_folder,
        },
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return BackupResult(backup_id, str(backup_root), len(rows), manifest["total_bytes"])


def verify_release_backup(backup_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = Path(backup_root).expanduser().resolve()
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    logical_dirs = {
        "config": root / "payload" / "config",
        "install_state": root / "payload" / "install",
        "state": root / "payload" / "state",
        "openclaw_profile": root / "payload" / "openclaw",
        "browser_extension": root / "payload" / "browser-extension",
        "managed_memory": root / "payload" / "managed-memory",
    }
    failures: list[str] = []
    for item in data.get("files", []):
        base = logical_dirs[item["logical_root"]]
        p = base / item["relative_path"]
        if not p.exists():
            failures.append(f"MISSING:{item['logical_root']}:{item['relative_path']}")
        elif p.stat().st_size != int(item["size_bytes"]) or _sha256_file(p) != item["sha256"]:
            failures.append(f"HASH:{item['logical_root']}:{item['relative_path']}")
    return {"status":"PASS" if not failures else "FAIL", "backup_id":data.get("backup_id"), "failures":failures}


def restore_release_backup(*, backup_root: str | os.PathLike[str], config_path: Path, state_dir: Path,
                           install_state_path: Path, openclaw_profile_path: Path,
                           browser_extension_dir: Path, vault_root: Path,
                           managed_folder: str = "Multi-AI Memory") -> dict[str, Any]:
    root = Path(backup_root).expanduser().resolve()
    check = verify_release_backup(root)
    if check["status"] != "PASS":
        raise RuntimeError(f"BACKUP_VERIFY_FAILED: {check['failures']}")
    payload = root / "payload"

    def replace_path(src: Path, dst: Path) -> None:
        if not src.exists():
            return
        if dst.exists():
            if dst.is_dir(): shutil.rmtree(dst)
            else: dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir(): shutil.copytree(src, dst)
        else: shutil.copyfile(src, dst)

    # Exact bytes are restored; no parsing/reserialization of memory or config data.
    config_candidates = list((payload / "config").glob("*"))
    install_candidates = list((payload / "install").glob("*"))
    openclaw_candidates = list((payload / "openclaw").glob("*"))
    if config_candidates: replace_path(config_candidates[0], config_path)
    if install_candidates: replace_path(install_candidates[0], install_state_path)
    replace_path(payload / "state", state_dir)
    if openclaw_candidates: replace_path(openclaw_candidates[0], openclaw_profile_path)
    replace_path(payload / "browser-extension", browser_extension_dir)
    replace_path(payload / "managed-memory", vault_root / managed_folder)
    return {"status":"PASS", "backup_id":check["backup_id"]}


def temporary_self_test_dir(state_dir: Path):
    return tempfile.TemporaryDirectory(prefix="post-install-e2e-", dir=str(state_dir))

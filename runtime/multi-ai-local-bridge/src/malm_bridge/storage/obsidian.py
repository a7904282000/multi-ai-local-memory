from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ..errors import IdempotencyConflict
from ..sync import ChangeBatch, ExternalMemoryChange, PushResult, SyncPeerCapabilities
from ..types import AuditEvent, MemoryAtom, utc_now
from .base import StorageCapabilities


_FORMAT_VERSION = 1
_FRONTMATTER_KEYS = (
    "malm_format_version",
    "memory_id",
    "kind",
    "namespace",
    "memory_space_id",
    "subject",
    "key",
    "verification_status",
    "lifecycle_status",
    "sensitivity",
    "confidence",
    "provenance",
    "created_at",
    "updated_at",
    "revision",
    "structured_value",
    "tags",
    "supersedes",
    "conflict_group_id",
    "expiry",
    "project_id",
)


class ObsidianStorageAdapter:
    """Obsidian/Markdown implementation of both StorageAdapter and SyncPeerAdapter.

    Managed notes are ordinary Markdown files with JSON-valued YAML-compatible frontmatter.
    The adapter never depends on Obsidian APIs: Obsidian is the default editor/UI over a
    user-owned local vault. External edits to managed notes are reconciled into canonical
    revisions before reads/writes and are exposed through the sync change feed.
    """

    def __init__(
        self,
        vault_root: str | os.PathLike[str],
        *,
        managed_folder: str = "Multi-AI Memory",
        peer_id: str = "obsidian",
    ):
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.managed_root = (self.vault_root / managed_folder).resolve()
        if self.vault_root != self.managed_root and self.vault_root not in self.managed_root.parents:
            raise ValueError("managed_folder must stay inside vault_root")
        self.memory_root = self.managed_root / "Memory"
        self.meta_root = self.managed_root / ".malm"
        self.state_path = self.meta_root / "state.json"
        self.idem_path = self.meta_root / "idempotency.json"
        self.push_idem_path = self.meta_root / "push-idempotency.json"
        self.audit_path = self.meta_root / "audit.jsonl"
        self.changes_path = self.meta_root / "changes.jsonl"
        self.peer_id = peer_id
        self._lock = threading.RLock()
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.meta_root.mkdir(parents=True, exist_ok=True)
        self._state = self._load_json(self.state_path, {"atoms": {}})
        self._idem = self._load_json(self.idem_path, {})
        self._push_idem = self._load_json(self.push_idem_path, {})
        # Reconcile immediately so a reopened process sees edits made while it was down.
        with self._lock:
            self._reconcile_all()

    # ---------- durable helpers ----------

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return copy.deepcopy(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"CORRUPT_RECORD: {path}") from exc

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _save_json(self, path: Path, value: Any) -> None:
        self._atomic_write_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _safe_component(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value) and value not in {".", ".."}:
            return value
        return "id_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]

    def _path_for_atom(self, atom: MemoryAtom) -> Path:
        space = self._safe_component(atom.memory_space_id)
        name = self._safe_component(atom.memory_id) + ".md"
        path = (self.memory_root / space / name).resolve()
        if self.memory_root.resolve() not in path.parents:
            raise ValueError("Resolved note path escaped managed memory root")
        return path

    @staticmethod
    def _atom_payload(atom: MemoryAtom) -> dict[str, Any]:
        return atom.to_dict()

    @classmethod
    def _serialize_atom(cls, atom: MemoryAtom) -> str:
        data = atom.to_dict()
        fm = {
            "malm_format_version": _FORMAT_VERSION,
            "memory_id": data["memory_id"],
            "kind": data["kind"],
            "namespace": data["namespace"],
            "memory_space_id": data["memory_space_id"],
            "subject": data["subject"],
            "key": data["key"],
            "verification_status": data["verification_status"],
            "lifecycle_status": data["lifecycle_status"],
            "sensitivity": data["sensitivity"],
            "confidence": data["confidence"],
            "provenance": data["provenance"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "revision": data["revision"],
            "structured_value": data["structured_value"],
            "tags": data["tags"],
            "supersedes": data["supersedes"],
            "conflict_group_id": data["conflict_group_id"],
            "expiry": data["expiry"],
            "project_id": data["project_id"],
        }
        lines = ["---"]
        for key in _FRONTMATTER_KEYS:
            lines.append(f"{key}: {json.dumps(fm[key], ensure_ascii=False, sort_keys=True)}")
        lines.extend(["---", "", atom.content, ""])
        return "\n".join(lines)

    @classmethod
    def _parse_note(cls, text: str, path: Path) -> MemoryAtom:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError(f"Not a managed MALM note: {path}")
        try:
            end = lines.index("---", 1)
        except ValueError as exc:
            raise ValueError(f"Missing closing frontmatter delimiter: {path}") from exc
        fm: dict[str, Any] = {}
        for line in lines[1:end]:
            if not line.strip():
                continue
            if ":" not in line:
                raise ValueError(f"Invalid managed frontmatter line in {path}: {line!r}")
            key, raw = line.split(":", 1)
            key = key.strip()
            if key not in _FRONTMATTER_KEYS:
                continue
            try:
                fm[key] = json.loads(raw.strip())
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON-valued frontmatter for {key} in {path}") from exc
        if fm.get("malm_format_version") != _FORMAT_VERSION:
            raise ValueError(f"Unsupported MALM note format in {path}")
        required = {
            "memory_id", "kind", "namespace", "memory_space_id", "subject", "key",
            "verification_status", "lifecycle_status", "sensitivity", "confidence",
            "provenance", "created_at", "updated_at", "revision",
        }
        missing = sorted(required - fm.keys())
        if missing:
            raise ValueError(f"Missing managed note fields {missing} in {path}")
        body_lines = lines[end + 1:]
        if body_lines and body_lines[0] == "":
            body_lines = body_lines[1:]
        content = "\n".join(body_lines).rstrip("\n")
        return MemoryAtom(
            memory_id=str(fm["memory_id"]),
            kind=str(fm["kind"]),
            namespace=str(fm["namespace"]),
            memory_space_id=str(fm["memory_space_id"]),
            subject=str(fm["subject"]),
            key=str(fm["key"]),
            content=content,
            verification_status=str(fm["verification_status"]),
            lifecycle_status=str(fm["lifecycle_status"]),
            sensitivity=str(fm["sensitivity"]),
            confidence=float(fm["confidence"]),
            provenance=dict(fm.get("provenance") or {}),
            created_at=str(fm["created_at"]),
            updated_at=str(fm["updated_at"]),
            revision=int(fm["revision"]),
            structured_value=fm.get("structured_value"),
            tags=list(fm.get("tags") or []),
            supersedes=fm.get("supersedes"),
            conflict_group_id=fm.get("conflict_group_id"),
            expiry=fm.get("expiry"),
            project_id=fm.get("project_id"),
        )

    def _read_atom_path(self, path: Path) -> MemoryAtom:
        return self._parse_note(path.read_text(encoding="utf-8"), path)

    def _state_entry(self, atom: MemoryAtom, path: Path) -> dict[str, Any]:
        serialized = self._serialize_atom(atom)
        return {
            "path": str(path.relative_to(self.managed_root)),
            "file_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "revision": atom.revision,
            "atom": atom.to_dict(),
        }

    def _write_atom(self, atom: MemoryAtom, *, record_external_change: bool = False, base_revision: int | None = None) -> MemoryAtom:
        path = self._path_for_atom(atom)
        text = self._serialize_atom(atom)
        self._atomic_write_text(path, text)
        self._state.setdefault("atoms", {})[atom.memory_id] = self._state_entry(atom, path)
        self._save_json(self.state_path, self._state)
        if record_external_change:
            self._append_change(atom, base_revision if base_revision is not None else max(atom.revision - 1, 0))
        return copy.deepcopy(atom)

    def _append_change(self, atom: MemoryAtom, base_revision: int) -> None:
        record = {
            "change_id": f"chg-{self.peer_id}-{uuid.uuid4().hex}",
            "memory_space_id": atom.memory_space_id,
            "operation": "UPSERT",
            "atom": atom.to_dict(),
            "base_revision": base_revision,
            "origin_peer_id": self.peer_id,
        }
        with open(self.changes_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _atom_from_dict(d: dict[str, Any]) -> MemoryAtom:
        return MemoryAtom(**d)

    def _change_records(self) -> list[dict[str, Any]]:
        if not self.changes_path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.changes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def _reconcile_all(self) -> None:
        """Detect edits made directly in Obsidian/another editor.

        Managed notes are the canonical user-visible representation. If a file changes
        without an adapter write, the adapter advances its revision and records a change
        feed event. This makes human edits first-class bidirectional updates.
        """
        self.memory_root.mkdir(parents=True, exist_ok=True)
        known = self._state.setdefault("atoms", {})
        state_dirty = False
        for path in sorted(self.memory_root.rglob("*.md")):
            atom = self._read_atom_path(path)
            canonical_text = self._serialize_atom(atom)
            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            entry = known.get(atom.memory_id)
            if entry is None:
                # A valid managed note created outside the adapter becomes a new external memory.
                normalized = replace(
                    atom,
                    revision=max(1, atom.revision),
                    updated_at=utc_now(),
                    provenance={**atom.provenance, "source_type": "obsidian-external-create", "origin_peer_id": self.peer_id},
                )
                self._atomic_write_text(path, self._serialize_atom(normalized))
                known[normalized.memory_id] = self._state_entry(normalized, path)
                self._append_change(normalized, 0)
                state_dirty = True
                continue

            expected_hash = entry.get("file_hash")
            # Use bytes hash so even a human edit to body/frontmatter is detected.
            if current_hash == expected_hash:
                continue

            previous = self._atom_from_dict(entry["atom"])
            # If file carries a higher canonical revision, treat it as recovery from a
            # crash between note write and state update; do not invent another revision.
            if atom.revision > previous.revision:
                normalized = atom
                known[atom.memory_id] = self._state_entry(normalized, path)
                state_dirty = True
                continue

            normalized = replace(
                atom,
                memory_id=previous.memory_id,
                memory_space_id=previous.memory_space_id,
                subject=previous.subject,
                created_at=previous.created_at,
                revision=previous.revision + 1,
                updated_at=utc_now(),
                provenance={
                    **atom.provenance,
                    "source_type": "obsidian-external-edit",
                    "origin_peer_id": self.peer_id,
                    "base_revision": previous.revision,
                },
            )
            self._atomic_write_text(path, self._serialize_atom(normalized))
            known[normalized.memory_id] = self._state_entry(normalized, path)
            self._append_change(normalized, previous.revision)
            state_dirty = True

        if state_dirty:
            self._save_json(self.state_path, self._state)

    def _all_atoms(self) -> list[MemoryAtom]:
        self._reconcile_all()
        atoms: list[MemoryAtom] = []
        for entry in self._state.get("atoms", {}).values():
            path = self.managed_root / entry["path"]
            if path.exists():
                atoms.append(self._read_atom_path(path))
        return atoms

    # ---------- StorageAdapter ----------

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(
            adapter_name="obsidian-markdown",
            adapter_version="1.0",
            transactional_writes=False,
            compare_and_swap=True,
            full_text_search=True,
            semantic_search=False,
            raw_archive=False,
            audit_log=True,
            encryption_at_rest=False,
        )

    def health(self) -> dict[str, Any]:
        with self._lock:
            try:
                atoms = self._all_atoms()
                return {
                    "status": "PASS",
                    "adapter": "obsidian-markdown",
                    "vault_root": str(self.vault_root),
                    "managed_root": str(self.managed_root),
                    "atom_count": len(atoms),
                    "audit_count": len(self.audit_events()),
                }
            except Exception as exc:
                return {"status": "FAIL", "adapter": "obsidian-markdown", "error": str(exc)}

    def search(self, query: str, filters: dict[str, Any], limit: int) -> list[MemoryAtom]:
        q = query.casefold().strip()
        namespaces = filters.get("namespaces") or []
        memory_space_ids = filters.get("memory_space_ids") or []
        include_lifecycle = set(filters.get("include_lifecycle") or ["ACTIVE", "CONFLICT"])
        if not isinstance(namespaces, list) or not all(isinstance(x, str) for x in namespaces):
            raise ValueError("filters.namespaces must be a string array")
        if not isinstance(memory_space_ids, list) or not all(isinstance(x, str) for x in memory_space_ids):
            raise ValueError("filters.memory_space_ids must be a string array")
        with self._lock:
            atoms = [
                a for a in self._all_atoms()
                if a.lifecycle_status in include_lifecycle
                and (not memory_space_ids or a.memory_space_id in memory_space_ids)
                and (not namespaces or a.namespace in namespaces)
                and (not q or q in f"{a.subject} {a.key} {a.content}".casefold())
            ]
            atoms.sort(key=lambda a: (a.updated_at, a.memory_id), reverse=True)
            return copy.deepcopy(atoms[:limit])

    def get(self, memory_id: str) -> MemoryAtom | None:
        with self._lock:
            self._reconcile_all()
            entry = self._state.get("atoms", {}).get(memory_id)
            if not entry:
                return None
            path = self.managed_root / entry["path"]
            if not path.exists():
                return None
            return self._read_atom_path(path)

    def _idem_get(self, key: str, payload: Any) -> tuple[MemoryAtom | str | bool | None, str]:
        fp = self._fingerprint(payload)
        row = self._idem.get(key)
        if row is None:
            return None, fp
        if row["fingerprint"] != fp:
            raise IdempotencyConflict()
        result = row.get("result")
        if isinstance(result, dict) and "memory_id" in result:
            return self._atom_from_dict(result), fp
        return result, fp

    def _idem_put(self, key: str, fp: str, result: MemoryAtom | str | bool) -> None:
        value = result.to_dict() if isinstance(result, MemoryAtom) else result
        self._idem[key] = {"fingerprint": fp, "result": value}
        self._save_json(self.idem_path, self._idem)

    def commit(self, atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op": "commit", "atom": atom.to_dict(), "expected_revision": expected_revision}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if isinstance(prior, MemoryAtom):
                return prior
            self._reconcile_all()
            current = self.get(atom.memory_id)
            if expected_revision is not None and (current is None or current.revision != expected_revision):
                raise RuntimeError("REVISION_CONFLICT")
            if current:
                atom = replace(atom, revision=current.revision + 1, created_at=current.created_at, updated_at=utc_now())
            else:
                atom = replace(atom, revision=max(1, atom.revision))
            stored = self._write_atom(atom)
            self._idem_put(idempotency_key, fp, stored)
            return stored

    def supersede(self, old_memory_id: str, new_atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op": "supersede", "old": old_memory_id, "new": new_atom.to_dict(), "expected_revision": expected_revision}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if isinstance(prior, MemoryAtom):
                return prior
            self._reconcile_all()
            old = self.get(old_memory_id)
            if old is None:
                raise KeyError("NOT_FOUND")
            if expected_revision is not None and old.revision != expected_revision:
                raise RuntimeError("REVISION_CONFLICT")
            old2 = replace(old, lifecycle_status="SUPERSEDED", updated_at=utc_now(), revision=old.revision + 1)
            self._write_atom(old2)
            new_atom = replace(new_atom, supersedes=old_memory_id, revision=max(1, new_atom.revision))
            self._write_atom(new_atom)
            self._idem_put(idempotency_key, fp, new_atom)
            return copy.deepcopy(new_atom)

    def open_conflict(self, atom_ids: list[str], metadata: dict[str, Any], idempotency_key: str) -> str:
        payload = {"op": "conflict", "atom_ids": atom_ids, "metadata": metadata}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if isinstance(prior, str):
                return prior
            self._reconcile_all()
            gid = metadata.get("conflict_group_id") or f"conf_{uuid.uuid4().hex}"
            for atom_id in atom_ids:
                atom = self.get(atom_id)
                if atom:
                    self._write_atom(replace(
                        atom,
                        lifecycle_status="CONFLICT",
                        conflict_group_id=gid,
                        updated_at=utc_now(),
                        revision=atom.revision + 1,
                    ))
            self._idem_put(idempotency_key, fp, gid)
            return gid

    def append_audit(self, event: AuditEvent, idempotency_key: str | None = None) -> None:
        with self._lock:
            key = f"audit:{idempotency_key}" if idempotency_key else None
            if key:
                payload = {"op": "audit", "event": event.to_dict()}
                prior, fp = self._idem_get(key, payload)
                if prior is not None:
                    return
            with open(self.audit_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            if key:
                self._idem_put(key, fp, True)

    def audit_events(self) -> list[AuditEvent]:
        if not self.audit_path.exists():
            return []
        events: list[AuditEvent] = []
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(AuditEvent(**json.loads(line)))
        return events

    # ---------- SyncPeerAdapter ----------

    def sync_capabilities(self) -> SyncPeerCapabilities:
        return SyncPeerCapabilities(self.peer_id, "obsidian-markdown", "1.0", True, True)

    def sync_health(self) -> dict[str, Any]:
        h = self.health()
        h.update({"peer_id": self.peer_id, "change_count": len(self._change_records())})
        return h

    def pull_changes(self, memory_space_id: str, cursor: str | None, limit: int = 100) -> ChangeBatch:
        with self._lock:
            self._reconcile_all()
            records = self._change_records()
            start = int(cursor or 0)
            changes: list[ExternalMemoryChange] = []
            i = start
            # Cursor advances only across records actually scanned. A page limit must
            # never jump to EOF and silently discard unprocessed changes.
            while i < len(records) and len(changes) < limit:
                rec = records[i]
                i += 1
                if rec["memory_space_id"] != memory_space_id:
                    continue
                changes.append(ExternalMemoryChange(
                    change_id=rec["change_id"],
                    memory_space_id=rec["memory_space_id"],
                    operation=rec["operation"],
                    atom=self._atom_from_dict(rec["atom"]),
                    base_revision=int(rec["base_revision"]),
                    origin_peer_id=rec["origin_peer_id"],
                ))
            return ChangeBatch(changes, str(i))

    def push_atoms(self, memory_space_id: str, atoms: list[MemoryAtom], idempotency_key: str) -> PushResult:
        relevant = [a for a in atoms if a.memory_space_id == memory_space_id]
        fp = self._fingerprint([a.to_dict() for a in relevant])
        with self._lock:
            row = self._push_idem.get(idempotency_key)
            if row is not None:
                if row != fp:
                    raise RuntimeError("IDEMPOTENCY_CONFLICT")
                return PushResult(0, len(relevant))
            self._reconcile_all()
            applied = skipped = 0
            for atom in relevant:
                current = self.get(atom.memory_id)
                if current and current.to_dict() == atom.to_dict():
                    skipped += 1
                else:
                    # Mirror canonical atom exactly; do not create a peer-origin change event.
                    self._write_atom(copy.deepcopy(atom))
                    applied += 1
            self._push_idem[idempotency_key] = fp
            self._save_json(self.push_idem_path, self._push_idem)
            return PushResult(applied, skipped)

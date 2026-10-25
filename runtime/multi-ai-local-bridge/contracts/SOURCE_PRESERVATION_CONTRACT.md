# Source Memory Preservation Contract v1

**Status:** Stable interface
**Contract version:** `1.0`

## 1. Purpose

When existing memories are migrated from a model, provider export, agent, local memory application, legacy bridge, or other source, the original source memory MUST be preserved locally before any normalization, indexing, classification, deduplication, extraction, summarization, or transformation.

This contract applies to **source memories being migrated**. It does not mean every new conversation must be archived as long-term memory.

## 2. Immutable source layer

The migration pipeline MUST be:

```text
Source Memory
→ Immutable Local Source Archive
→ optional derived MemoryAtom / semantic index / search view
```

It MUST NOT be:

```text
Source Memory
→ summarize / merge / purify
→ discard original
```

## 3. Exact preservation requirements

For every accessible source file/object export represented as bytes, migration MUST preserve:

```text
SOURCE_BYTES_PRESERVED=100%
SOURCE_FILE_COUNT_PRESERVED=100%
SOURCE_SHA256_MATCH=100%
SOURCE_RELATIVE_PATH_PRESERVED=YES
SOURCE_ORIGINAL_MUTATED=NO
```

No newline normalization, character re-encoding, whitespace cleanup, field dropping, field renaming, content merging, or semantic rewriting is permitted in the immutable source archive.

## 4. Manifest

Every archive entry MUST have a manifest containing at least:

- source identity;
- source kind;
- archive identity;
- relative path/object identity;
- byte length;
- SHA-256 digest;
- archive creation time;
- preservation mode;
- immutable-source flag.

The archive MUST be independently verifiable from its manifest.

## 5. Derived views

Derived representations MAY exist for recall quality and interoperability, including:

- MemoryAtom normalization;
- semantic embeddings;
- keyword indexes;
- conflict projections;
- summaries;
- classifications.

All such representations are disposable/rebuildable **derived views**.

They MUST reference source provenance where available and MUST NOT replace, truncate, or mutate the immutable source memory.

## 6. Update / backup / restore

Release updates MUST back up local memory before modifying application state.

Backup and restore of user memory MUST preserve exact bytes. Restore MUST NOT parse and reserialize memory just to copy it back.

## 7. Uninstall

Uninstall MUST preserve user memory and immutable source archives by default.

Destructive deletion of user memory requires an explicit user action and MUST never be the default uninstall behavior.

## 8. Provider limitations

If a provider exposes only a partial memory export/API, the bridge can preserve only the bytes/objects the provider actually exposes. It MUST report the source as partial rather than claiming a 100% migration of inaccessible provider-private state.

Within the accessible export, preservation MUST still be 100% byte-exact.

## 9. Acceptance gate

A migration is not complete unless:

```text
SOURCE_ARCHIVE_CREATED=PASS
SOURCE_ARCHIVE_VERIFY=PASS
SOURCE_BYTES_PRESERVED=100%
SOURCE_SHA256_MATCH=100%
SOURCE_ORIGINAL_MUTATED=NO
DERIVED_VIEW_REPLACES_SOURCE=NO
```

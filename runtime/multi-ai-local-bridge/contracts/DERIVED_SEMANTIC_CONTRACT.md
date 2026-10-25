# Derived Semantic Memory Contract v1

**Status:** Stable invariant layer  
**Contract version:** `1.0`

## Purpose

Semantic recall is a disposable derived view over the authoritative local memory SSOT. It improves ranking and retrieval but never becomes a memory authority.

## Hard invariants

1. **Source is immutable by semantic processing.** Indexing, ranking, embeddings, clustering, summarization, aliases, or other derived processing MUST NOT rewrite, normalize, merge, delete, or replace source memory.
2. **Original imported/provider memory is byte-preserved.** `_SourceArchive` or equivalent source archive remains byte-for-byte authoritative for every source byte actually available to the system.
3. **Derived data is disposable.** Deleting all semantic-index data MUST NOT delete or change any memory. The index MUST be rebuildable from the authoritative SSOT/source archive.
4. **Recall returns authoritative source records.** A semantic hit is only a pointer/ranking decision. Before serving a result, the Bridge MUST fetch the current source `MemoryAtom` and validate its revision/source fingerprint.
5. **Stale derived data MUST NOT be served.** Revision/hash mismatch triggers refresh/rebuild rather than returning stale content.
6. **Memory-space and lifecycle boundaries remain authoritative.** Semantic ranking MUST NOT bypass namespace, memory-space, lifecycle, authorization, or conflict rules.
7. **Derived processing may enrich, never replace.** Embeddings, summaries, clusters, topics, aliases, and search features are optional derived artifacts and must point back to source identities.
8. **Provider black boxes are not invented.** Only source data actually exportable/readable through supported interfaces may be preserved; inaccessible provider-private memory MUST NOT be claimed as migrated.

## Minimum derived index record

A derived record SHOULD include only what is needed to verify and rank the source:

```text
memory_id
memory_space_id
namespace
lifecycle_status
revision
source_sha256
source_updated_at
derived_features / embedding / index metadata
```

It MUST NOT be treated as the canonical memory body.

## Rebuild acceptance

A compliant implementation MUST prove:

```text
SOURCE_ORIGINAL_MUTATED=NO
SOURCE_ARCHIVE_SHA256_MATCH=100%
DERIVED_INDEX_DELETE_SAFE=PASS
DERIVED_INDEX_REBUILD=PASS
DERIVED_INDEX_CORRUPTION_RECOVERY=PASS
STALE_DERIVED_RESULT_BLOCKED=PASS
RECALL_RETURNS_AUTHORITATIVE_SOURCE=PASS
MEMORY_SPACE_ISOLATION=PASS
LIFECYCLE_FILTER_ENFORCED=PASS
```

## Future embeddings / model-assisted semantics

A future local or provider embedding model may replace the baseline feature extractor without changing this contract. Embeddings MUST remain derived, removable, and rebuildable. Switching embedding models MUST NOT require rewriting source memory.

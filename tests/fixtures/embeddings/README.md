# Embedding fixture cache

`scripts/ai_provider.py` (`EMBEDDING_PROVIDER=st`) maps each `(model, text)` pair
to a stable SHA-256 and stores the L2-normalized sentence-transformers vector here
as `<sha256>.json`:

```json
{
  "model": "all-MiniLM-L6-v2",
  "text_sha256": "<sha256 of the embedded text>",
  "dim": 384,
  "embedding": [ /* the normalized vector */ ]
}
```

These fixtures let the real semantic embedding path replay **offline and
deterministically**: with every needed text committed here, `embed()` never
imports `sentence-transformers` and never touches the network. The heavy package
is imported lazily only to fill a *miss* (building anchors or recording new
fixtures locally), then the computed vector is written back here for replay.

- `EMBEDDING_PROVIDER=none` (default) / `local` (CI default): nothing reads or
  writes this directory; the local path is the dependency-free hashing embedding.
- `EMBEDDING_PROVIDER=st`: a cache hit replays the committed vector; a miss with
  the package available computes and persists it, and a miss without the package
  returns `None` so callers fall back to the keyword heuristic.

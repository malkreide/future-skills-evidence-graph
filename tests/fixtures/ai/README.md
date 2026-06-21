# AI fixture cache

`scripts/ai_provider.py` maps each request to a stable hash and stores the
response here as `<sha256>.json`:

```json
{
  "hash": "<sha256 of the canonical request>",
  "kind": "complete",
  "response": { "...": "the stored response" }
}
```

The hash is computed from the canonical request (`kind`, `model`, `prompt`,
`schema`), so it is stable across runs and Python versions.

- With `AI_PROVIDER=cache` the cache is **read-only**: a request that isn't here
  is a miss, which returns `None`. In CI that means the fixture is missing and the
  caller should treat it as a failure — never a silent network fall-through.
- With `AI_PROVIDER=anthropic` a live response is written here for later replay.
- With `AI_PROVIDER=none` (the default) nothing reads or writes this directory.

# Entity registry (`graph_builder.registry`)

**Status:** implemented as a file release built from a dataset bundle ([E13](../experiments/E13-entity-registry-bsee.md)). PostgreSQL storage, merge history and report-mention linking are planned (design §5.4, §5.7).

The registry is the shared list of entities that claims point at: one entity per real-world object, with an opaque ID, a type, scoped identifiers, former identifiers and language-tagged names. Records follow [`schemas/entity.schema.json`](../../schemas/entity.schema.json) and cite [evidence](../../schemas/evidence.schema.json) for their identifiers ([E12](../experiments/E12-shared-evidence-contract.md)).

## Commands

```powershell
python -m graph_builder.registry build   --config configs/registry/bsee_wells.registry.json
python -m graph_builder.registry resolve --config configs/registry/bsee_wells.registry.json "API 01-203-20165-00"
python -m graph_builder.registry resolve --config configs/registry/bsee_wells.registry.json "001 ST00BP00" --type Wellbore --scope G01234
```

## Configuration

A registry config names a dataset bundle, an output directory and, for each node label to register:

| Key | Meaning |
|---|---|
| `entity_type` | Profile-declared type (for example `Wellbore`) |
| `identifier` | Scheme, node property and match rule (`{"strip": "non_digits", "length": 12}` lets "01-203-20165-00" match) |
| `names` | A property, or several joined by spaces, optionally scoped by a linked node's property (for example the lease number across `SURFACE_ON_LEASE`) |
| `former_identifiers` | Edges whose target ID is an earlier identifier of the same entity (`RENUMBERED_FROM`) |

Nothing in the code knows about wells; BSEE is one config. The entity ID is a digest of its first identifier, so a renamed well keeps its ID.

## Resolution

`Registry.resolve(mention, entity_type=None, scope=None)` returns `resolved` (with `via`: `identifier`, `former_identifier` or `scoped_name`), `ambiguous`, `needs_review` (an unscoped name, with candidates) or `unknown`. It never resolves on similarity, and a name never resolves without a scope. Duplicate suggestions for an administrator are a separate tool (prototype `curate.py`, FR-21).

## Output

`<output>/CURRENT.json` points at `<output>/releases/<id>/`, which holds `entities.jsonl`, `evidence.jsonl` (one dataset-row evidence record per entity), `summary.json` (counts, identifier schemes and rules, the dataset release used) and `SHA256SUMS`.

## Limitations

- The first 50 records of each kind are schema-validated; the rest rely on the same deterministic builder.
- Former identifiers come only from edges the importer created, which requires both wellbores to be in the file (172 in the 18 October snapshot).
- Report mentions are not linked yet; the AK-3 reports name no BSEE well.

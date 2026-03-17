# MyCBR CBR Cycle

This subproject is isolated from the main generation and verification modules.

It implements a standalone case-based reasoning cycle around the existing SQL case base:

1. build a working case
2. check it with the current naming and normalization rules
3. retrieve similar cases using the current hybrid retrieval engine
4. reuse a selected case through the existing merge logic
5. revise the result through normalization and validation
6. retain the revised case in a local JSON store
7. export a ready-to-open myCBR Workbench project bundle

## Files

- `MyCBR/app.py`
  - standalone Streamlit UI for the full cycle
- `MyCBR/repository.py`
  - SQL case-base access, local retained-case store, myCBR executable discovery
- `MyCBR/cycle.py`
  - normalization, checking, reuse, and revision helpers
- `MyCBR/project_export.py`
  - myCBR Workbench project and CSV export generation
- `MyCBR/data/retained_cases.json`
  - local retained-case store

## Run

```bash
streamlit run MyCBR/app.py
```

## Exported myCBR assets

The export step generates:

- `.myCBR` concept and similarity model
- `.myCB` case instances
- `.myExp` explanation metadata
- `.config`
- `.prj` packaged project bundle
- `casebase.csv`
- a workspace zip containing all of the above

## Similarity modeling

The generated myCBR project uses structured attributes derived from each UCD case:

- primary domain
- system kind
- primary actor count
- secondary actor count
- use-case count
- relationship count
- presence of include relationships
- presence of extend relationships
- presence of generalization relationships
- case origin

It also creates multiple similarity profiles:

- `balanced_similarity`
- `structure_focused_similarity`
- `actor_focused_similarity`

Numeric attributes include strict and loose similarity functions so you can compare retrieval behavior directly inside myCBR Workbench.

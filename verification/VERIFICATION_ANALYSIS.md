# Verification Module Analysis

## Scope

This document summarizes the active `verification/` module used by `ucd_verification.py`, with emphasis on:

- Runtime flow
- Session-state ownership
- Parsed data shape
- Validation responsibilities
- Export/TTool integration
- Maintenance risks and likely edit points

It is intended as a working reference for follow-up implementation tasks.

## Active Entry Point

- Root entry file: `ucd_verification.py`
- Active app entry: `verification.step_manager.run_wizard()`
- The old `verification/ui_page.py` is legacy/reference code and is not the active path used by the thin orchestrator.

## High-Level Architecture

The active verification stack is split into these layers:

1. `verification/step_manager.py`
   Drives the wizard, stepper UI, navigation, and per-diagram iteration.
2. `verification/step1_upload.py`
   Uploads XML, parses it once, runs all expensive validators once, and stores the fully annotated dataset in session state.
3. `verification/step2_system.py`
   Displays system-boundary verification for the current diagram.
4. `verification/step3_actors.py`
   Displays actor verification for the current diagram.
5. `verification/step4_usecases.py`
   Displays use-case verification for the current diagram.
6. `verification/step5_semantics.py`
   Displays arrangement/connectivity findings for the current diagram.
7. `verification/step5_relationships.py`
   Displays and confirms relationship classification for the current diagram, then advances to the next diagram.
8. `verification/step6_results.py`
   Aggregates all findings, renders detailed tables, and exports a corrected XML with verification activity panels.
9. `verification/xml_parser.py`
   Parses TTool XML into the internal dataset structure.
10. `verification/element_verification.py`
    Central rule engine for batch checks, NLP-triggered validation integration, structural checks, issue collection, and activity-panel helpers.
11. `verification/text_tools.py`
    NLP-heavy phrase validation and semantic-similarity helpers.
12. `verification/activity_panel.py`
    Builds verification activity diagrams and appends rule/reference tabs to exported XML.
13. `verification/ttool_launcher.py`
    Resolves and launches TTool executables.
14. `verification/nlp_setup.py`
    Loads NLTK and the sentence-transformer similarity model.

## Runtime Flow

### 1. App startup

`ucd_verification.app()` calls `run_wizard()`.

`run_wizard()`:

- initializes wizard state
- renders the top stepper
- renders the reset flow
- lazy-imports each step renderer
- shows current diagram context for steps 2 to 6
- dispatches to the current step render function

### 2. Upload and pre-verification

`step1_upload.render()` is the real processing gate.

When a new XML file is uploaded:

- file hash is computed with `get_file_hash()`
- `UcdVerificationParser.extractData()` parses the XML
- raw uploaded XML is saved in session state
- `_run_all_validators()` mutates the parsed dataset in place
- the verified dataset and parser instance are cached in session state

This is the core design choice in the refactor:

- all expensive validation runs once at upload time
- later steps mostly read precomputed comments/actions
- tab switching is intended to be instant

### 3. Per-diagram loop

The wizard flattens all diagrams across modeling tabs via `get_diagram_list()`.

For each diagram:

- step 2 shows system checks
- step 3 shows actor checks
- step 4 shows use-case checks
- step 5 shows arrangement/connectivity semantics
- step 6 (implemented in `step5_relationships.py`) handles relation confirmation

After relationships are confirmed:

- `advance_diagram()` moves to the next diagram and resets completed-step highlighting for steps 2 to 6
- after the last diagram, the wizard moves to the results page

### 4. Results/export

`step6_results.render()`:

- re-runs only structural validators
- avoids `processData()` because `validateActors()` and `validateUsecases()` do full comment resets
- collects grouped issue steps
- renders summary metrics and detailed per-diagram tables
- appends grouped verification activity panels to the original XML
- appends requirement-rule panels from `ucd_rules.xml`
- offers XML download and optional TTool launch

## Session State Contract

The active wizard uses `ver_*` keys. Important ones:

- `ver_current_step`
- `ver_completed_steps`
- `ver_processing`
- `ver_current_diagram`
- `ver_ucd_instance`
- `ver_ucd_dataset`
- `ver_last_file_hash`
- `ver_uploaded_xml`
- `ver_validated_ucds`
- `ver_finalized`
- `ver_pre_verified`

Notes:

- `ver_ucd_dataset` is the central mutable source of truth.
- Most steps read and sometimes mutate metadata directly inside this nested structure.
- `ver_pre_verified` is a guard used by actor/use-case steps to avoid re-running validators after upload.

## Parsed Data Shape

`xml_parser.extractData()` returns a nested list/dict structure:

```python
[
  {
    "<modeling_tab_name>": {
      "Ucd Data": [
        {
          "<ucd_name>": {
            "Primary Actors": [
              ("Actor Name", meta_dict),
            ],
            "Secondary Actors": [
              ("Actor Name", meta_dict),
            ],
            "Use Cases": [
              ("Use Case Name", meta_dict),
            ],
            "System Boundary": [
              ("System Name", meta_dict),
            ],
            "Connectors": [
              ("connector_id", connector_meta_dict),
            ],
            "Comments": [],
            "Action": ""
          }
        }
      ]
    }
  }
]
```

Element `meta_dict` fields generally include:

- `Element Type`
- `X`
- `Y`
- `W`
- `H`
- `Comments`
- `Action`

Connector metadata includes:

- `Relation Code`
- `Relation Name`
- `Relation Value`
- `Source Type`
- `Target Type`
- `Source Name`
- `Target Name`
- `Extension`
- `Comments`
- `Action`

## Parser Behavior

`UcdVerificationParser.extractData()`:

- reads `<Modeling>` blocks of type `Avatar Analysis` or `Analysis`
- reads each `UseCaseDiagramPanel`
- extracts components by TTool type code:
  - `700`: primary actor
  - `701`: use case
  - `702`: system boundary
  - `703`: secondary actor
- extracts connectors and infers relation types
- skips type `118` connectors

Diagram-level parser gates:

- exactly one system boundary is required
- at least one actor is required
- at least one use case is required
- invalid diagrams are skipped with Streamlit errors

Parser implementation detail:

- source/target connector names are resolved by scanning component connecting points inside the panel
- connector relation value is normalized to `Include`, `Extend`, `Generalization`, or `Association` where applicable

## Validation Pipeline

### Upload-time pipeline

`step1_upload._run_all_validators()` runs in this order for every diagram:

1. `validateActors(all_actors)`
2. `validateUsecases(use_cases)`
3. `validateActor()` for each primary actor
4. `validateActor()` for each secondary actor
5. `validateUsecase()` for each use case
6. `validateSystem()` for the system boundary
7. `validateArrangement(...)`
8. `validateActorConnectivity(...)`
9. `validateUsecaseConnectivity(...)`
10. `validateRelations(...)`

This ordering matters because the two batch validators perform hard resets of `Comments` and `Action`.

### Validation categories

`element_verification.py` has four practical classes of logic:

1. Batch uniqueness/length checks
   - `validateActors()`
   - `validateUsecases()`
2. Per-element NLP/name checks
   - `validateActor()`
   - `validateUsecase()`
   - `validateSystem()`
3. Structural/geometry/connectivity checks
   - `validateArrangement()`
   - `validateActorConnectivity()`
   - `validateUsecaseConnectivity()`
4. Relationship checks and issue extraction
   - `validateRelations()`
   - `collect_issue_steps()`
   - `collect_grouped_steps()`

## Reset Semantics Inside Validators

This is the most important maintenance constraint in the module.

### Hard-reset validators

These clear comments/actions for the target elements:

- `validateActors()`
- `validateUsecases()`

They should only run before later comments are added, or they will wipe prior results.

### Selective-clear validators

These try to remove only the comments they own:

- `validateArrangement()`
- `validateActorConnectivity()`
- `validateUsecaseConnectivity()`
- `validateRelations()`

This selective-clear design is what makes the results page safe to refresh after manual relationship classification.

## NLP Layer

`text_tools.py` is the heaviest dependency area.

It uses:

- spaCy `en_core_web_trf`
- NLTK words corpus
- NLTK WordNet
- `cross-encoder/ms-marco-MiniLM-L12-v2`

Primary responsibilities:

- actor/system noun-phrase validation
- use-case verb-phrase validation
- title/pascal case normalization helpers
- actor primary-vs-secondary heuristic classification
- semantic similarity scoring for duplicate/near-duplicate names

Important behavior:

- actor/system names are validated as noun phrases
- use-case names are validated as imperative verb phrases
- semantic similarity is used to detect likely duplicate actors/use cases
- warnings/errors are produced as free-text comments, later interpreted by severity heuristics

## Relationship Step Behavior

`step5_relationships.py` is the only step that asks the user to confirm or override relation semantics.

It:

- re-runs structural checks for the current diagram
- filters connectors to `Include`, `Extend`, and `Generalization`
- presents radio options and optional direction reversal
- writes new comments directly onto connector metadata
- sets connector `Action`
- advances immediately to the next diagram after confirmation

Important implication:

- user decisions are stored as comments on connectors, not as a separate normalized review object
- later logic depends on preserving those connector comments

## Results/Export Behavior

`step6_results.py` is the final aggregation layer.

It intentionally does not call `ucd_instance.processData()` because that would rerun hard-reset validators and erase prior comments.

Instead it:

- re-runs only structural validators
- collects issues with severity tagging
- groups issues into five exported verification tabs:
  - `System`
  - `Primary Actors`
  - `Secondary Actors`
  - `Use Cases`
  - `Connectors`

`activity_panel.append_grouped_activity_panels()` then:

- creates a new `Verification` modeling tab with one activity panel per group
- creates a `Requirements` modeling tab
- injects rule panels from `verification/ucd_rules.xml`

## Active vs Legacy Code

Active:

- `ucd_verification.py`
- `verification/step_manager.py`
- `verification/step1_upload.py`
- `verification/step2_system.py`
- `verification/step3_actors.py`
- `verification/step4_usecases.py`
- `verification/step5_semantics.py`
- `verification/step5_relationships.py`
- `verification/step6_results.py`
- shared utilities under `verification/`

Legacy/reference:

- `verification/ui_page.py`
- root-level `ucd_validation.py`
- root-level `ucd_validation_operation.py`

The wizard flow is the modern path. The legacy page is useful only as a reference for previous behavior.

## Likely Maintenance Hotspots

### 1. Comment-driven state

The module uses free-text comments as both:

- user-facing explanation
- internal severity source
- structural-validator ownership markers

This is fragile because later logic infers behavior by substring matching.

Examples:

- step tables infer pass/warn/fail from comment text
- selective-clear validators delete comments by keyword matching
- issue collection infers severity from comment wording

### 2. In-place mutation of nested dataset

Nearly every validator mutates `ver_ucd_dataset` in place.

This makes the module simple to wire into Streamlit, but it also means:

- validator ordering is critical
- repeated calls can duplicate or clear findings if ownership boundaries are wrong
- future changes should be careful about re-running validators from later steps

### 3. Step numbering/naming drift

There is some naming drift:

- `step5_semantics.py` is wizard step 5
- `step5_relationships.py` is wizard step 6
- `step6_results.py` is wizard step 7

This is harmless at runtime but easy to trip over during maintenance.

### 4. Duplicate validation paths

There are two execution styles in the repo:

- active wizard pre-verification path in `step1_upload.py`
- older `processData()` path in `xml_parser.py`

The active results page explicitly avoids `processData()`.

If future work changes validator semantics, both paths should be reviewed unless the legacy path is removed.

### 5. NLP startup cost and deployment risk

The module depends on large NLP assets:

- `en_core_web_trf`
- NLTK downloads
- sentence-transformer cross-encoder

This can impact:

- startup latency
- memory consumption
- offline deployments
- first-run failures on machines without models

### 6. Connector type normalization depends on TTool codes and XML shape

Parser logic is coupled to:

- TTool component codes
- connecting-point traversal
- relation code assumptions

Any upstream XML format differences will likely break extraction first, not validation logic.

## Where To Edit For Common Future Tasks

If the task is about:

- XML extraction or relation mapping:
  - edit `verification/xml_parser.py`
- naming/grammar/NLP validation:
  - edit `verification/text_tools.py`
  - then adjust wrapper methods in `verification/element_verification.py` if needed
- severity, structural rules, or issue collection:
  - edit `verification/element_verification.py`
- wizard flow, step order, session reset, or per-diagram navigation:
  - edit `verification/step_manager.py`
- upload-time precomputation:
  - edit `verification/step1_upload.py`
- relationship review UI:
  - edit `verification/step5_relationships.py`
- final summary/export/download behavior:
  - edit `verification/step6_results.py`
- generated verification tabs in exported XML:
  - edit `verification/activity_panel.py`
- embedded rule reference tabs:
  - edit `verification/ucd_rules.xml`
  - or regenerate it via `verification/generate_ucd_rules.py`
- local TTool launching:
  - edit `verification/ttool_launcher.py`

## Practical Guidance For Future Changes

1. Treat `ver_ucd_dataset` as the canonical state object.
2. Avoid calling `processData()` from the active wizard path unless the hard-reset behavior is redesigned.
3. If you add a new validator, decide explicitly whether it is:
   - hard-reset
   - selective-clear
   - read-only
4. If you add new comments, make sure severity inference and selective-clear logic still behave correctly.
5. If you add a new exported issue group, update both:
   - `collect_grouped_steps()`
   - `activity_panel.VERIFICATION_GROUPS` and `TAB_LABELS`

## Suggested Cleanup Opportunities

These are not required immediately, but they would reduce future friction:

- replace comment-substring severity inference with structured rule codes
- separate user overrides from validator comments on connectors
- retire or isolate `ui_page.py` and old `processData()` usage
- normalize file naming so step numbers match wizard numbers
- formalize the dataset schema in one typed model/dataclass layer

## Bottom Line

The active verification module is a wizard-driven, precompute-first pipeline.

Its core strengths are:

- clear step separation
- fast tab switching after upload
- useful final XML export with verification activity diagrams

Its core fragility is:

- heavy reliance on in-place mutation and comment-text heuristics

Any future change should first ask:

- does this validator clear or preserve existing comments?
- does this step mutate connector/user-review state?
- does this change affect exported issue grouping or severity inference?

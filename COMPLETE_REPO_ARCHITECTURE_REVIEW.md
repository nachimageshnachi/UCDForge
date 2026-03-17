# Complete Repo Architecture Review

This is the staged deep-dive architecture walkthrough of the current workspace. It is a static code trace of the repo as it exists on March 2, 2026; I did not run DB writes, LLM calls, Java services, or modify any files other than adding this document.

## 1. Repo Map

The repo is not one app. It is a root Streamlit shell, two refactored wizard packages, shared ingestion/retrieval infrastructure, and two standalone CBR subprojects that live beside the main app.

| Bucket | Current code paths | Role |
|---|---|---|
| Active root runtime | `main.py`, `admin_login.py`, `resetpassword.py`, `fileupload.py`, `view.py`, `edit.py`, `logout.py`, `ucd_generation.py`, `ucd_verification.py` | User-facing shell and routed pages |
| Active packaged flows | `generation/step_manager.py`, `verification/step_manager.py` plus their step files | Current generator/verifier implementations |
| Shared support modules | `Parser.py`, `helpers.py`, `connection.py`, `embeddings.py`, `cbr_search.py`, `cbr_merge.py`, `cbr_excel_export.py`, `fetch_ucd_entities.py` | DB, parsing, NLP, embeddings, retrieval, export |
| Standalone subprojects | `MyCBR/app.py`, `MyCBR_Integration/python/app.py` | Separate CBR products, not routed from `main.py` |
| Legacy/reference | `ucd_generation_old.py`, `ucd_generation_old2.py`, `ucd_validation.py`, `ucd_validation_operation.py`, `helpers_old.py`, `verification/ui_page.py`, `fileupload_operations.py` | Older implementations still kept on disk |
| Support/test/docs | `mycbr_explorer.py`, `db_usecase_validation.py`, `usecase_db_verifier.py`, `test_custom_extraction.py`, `verification/VERIFICATION_ANALYSIS.md`, `MyCBR/README.md`, `MyCBR_Integration/README.md` | Standalone utilities, test scripts, design notes |
| Artifacts/binaries | `plantuml.jar`, `CBR_UCD/`, `MyCBR/output/`, `MyCBR_Integration/java/bin/`, `MyCBR_Integration/sdk/mycbr.jar`, `myVirtualEnvironment/`, `__pycache__/`, `result*.json`, `verify_*` | Generated or external assets |

Active-vs-legacy boundary:

- The current generation path is `ucd_generation.py` into `generation/`.
- The current verification path is `ucd_verification.py` into `verification/`.
- The standalone CBR apps are present in the workspace but are not linked from `main.py`.
- The legacy files are not fully dead. `helpers_old.py` is still imported by active generation code, and `ucd_validation_operation.py` is still imported indirectly by `cbr_merge.py`.

## 2. Root App And Shared Foundations

`main.py` is a thin Streamlit shell. It owns only top-level navigation and login state, then hands off to page modules. The routed pages are split into anonymous pages (`Home`, `UCD Verification`, `UCD Generation`, `Admin Login`) and logged-in pages (`Upload XML`, `View`, `Edit`, `Logout`).

Root shell state contract:

- `logged_in`, `logout_triggered`, `just_logged_out`, `menu_selection`
- The shell does not own generation or verification business state.
- `Reset Password` is not in the sidebar; `admin_login.py` routes to `resetpassword.py`.

Root page responsibilities:

- `admin_login.py` is UI only. `admin_login_operations.py` owns the `credentials` table, bcrypt hashing, login verification, OTP generation, and Gmail SMTP reset mail.
- `resetpassword.py` is a multi-step flow over DB lookup, OTP mail, and password update, all via session state.
- `fileupload.py` is the active XML ingestion page. It supports single XMLs or ZIP batches, optional table reset/clear, writes uploads to temp files, and calls `ParserOperations.addToDb()`.
- `view.py` and `view_operations.py` are DB browsers.
- `edit.py` and `edit_operations.py` are direct DB editors for a narrow set of columns, mainly `cases.description`, `cases.domain_json`, and `use_cases.description`.

Shared infrastructure:

- `connection.py` is the DB boundary. It opens a fresh PyMySQL connection per `get_cursor()` context using `st.secrets["mysql"]`. The old `commit()`, `rollback()`, and `close_connection()` APIs are now compatibility no-ops.
- `Parser.py` is the core XML-to-casebase ingestion engine. It mixes infrastructure and domain logic: table creation/destruction, TTool XML parsing, UCD normalization via `_validate_and_fix_ucd()`, PlantUML generation, LLM prompting for system/use-case descriptions, synonym generation, and final DB insertion into `cases`, `diagrams`, `actors`, `use_cases`, `relationships`, `case_domains`, and three synonym tables.
- `helpers.py` is a separate free-text extraction engine. Its `ask_llm_extract()` pipeline is the active entry for generation step 1. It uses three strategies by text size: direct extraction for short text, semantic RAG condensation for medium text, and chunk-and-merge for long text. It switches between Gemini and an OpenAI-compatible local endpoint using `st.secrets`.
- `embeddings.py` owns sentence-transformer loading and hybrid ranking weights. It is the shared semantic layer under retrieval.
- `cbr_search.py` is the SQL case retriever. It builds query embeddings, fetches case rows plus actors/use cases/synonyms, computes semantic and lexical features, then calls `rank_cases()`.
- `cbr_merge.py` is the reuse/revise/export bridge. It expands a stored case from SQL, merges a user payload with a retrieved case, normalizes via `ParserOperations._validate_and_fix_ucd()`, and can rebuild TTool XML.
- `cbr_excel_export.py` produces a styled Excel comparison of Python CBR results versus myCBR results.
- `fetch_ucd_entities.py` is a support validator over DB entities. It is not part of the main generation/verifier flows.

Notable architecture observations:

- There are two parallel LLM stacks: `helpers.py` for free-text extraction, and `Parser.py` for XML-ingestion enrichment.
- `fileupload_operations.py` is an older importer for a different schema (`systems`, `relations`, old `actors`/`use_cases`). The active upload page does not use it.
- The page modules still call `connection.close_connection()`, but that no longer does anything.

## 3. Active Generation Flow

The active generator is a thin orchestrator in `ucd_generation.py` that immediately calls `generation/step_manager.py`. The real architecture lives in the step package.

Generation runtime flow:

1. `generation/step_manager.py` owns the step registry, `ucd_*` state lifecycle, top stepper, save/reset flow, and lazy imports. `_STEP_KEYS` is the key contract for backtracking because it decides which later-step state gets cleared.
2. `generation/step1_input.py` is the real intake gate. It accepts typed text, PDF extraction, or saved-session XML from `generation/session_io.py`. On continue, it calls `helpers.ask_llm_extract()` and populates `ucd_system_name`, `ucd_primary_actors`, `ucd_secondary_actors`, `ucd_actors`, `ucd_use_cases`, `ucd_domains`, `ucd_relationships`, `ucd_paragraph`, and `ucd_ready`.
3. `generation/step2_hybrid_retrieval.py` fans out retrieval in parallel. It calls Python CBR via `cbr_search.py` and symbolic myCBR retrieval via `MyCBR/mycbr_rest.py`. It also auto-starts the older myCBR REST server through `start_mycbr_rest.bat`, stores `_py_matches` and `_my_matches`, and builds `cbr_suggested_*` additions by merging the top Python match with the current user payload through `cbr_merge.py`.
4. `generation/step2_elements.py` is logically step 3. It is the editor for actors and use cases. It loads DB suggestion catalogs from `generation/shared.py`, which still depends on `helpers_old.py` for synonym expansion and reverse lookup.
5. `generation/step3_review.py`, `generation/step4_associations.py`, `generation/step5_includes.py`, `generation/step6_extends.py`, `generation/step7_uc_generalization.py`, and `generation/step8_actor_generalization.py` all revolve around a single mutable source of truth: `ucd_relationships`. Each step derives its own pair structure from that list, edits it, then syncs changes back into the same list.
6. `generation/step9_cbr_export.py` is the output boundary. It builds TTool XML with `cbr_merge.py`, re-validates the generated XML through the active verification parser and rule engine, appends verification activity panels via `verification/activity_panel.py`, and persists the generated case to the SQL case base.

Generation state/data contracts:

- Navigation state: `ucd_current_step`, `ucd_completed_steps`, `ucd_processing`
- Core extracted model: `ucd_system_name`, `ucd_paragraph`, `ucd_primary_actors`, `ucd_secondary_actors`, `ucd_actors`, `ucd_use_cases`, `ucd_domains`, `ucd_relationships`
- Mid-flow retrieval state: `_py_matches`, `_my_matches`, `_hybrid_retrieval_done`, `cbr_top_case`, `cbr_kb_case`, `cbr_suggested_*`
- Diagram edit state: `ucd_match_pairs`, `ucd_include_pairs`, `ucd_extend_pairs`, `ucd_extend_meta`, `ucd_uc_gen_pairs`, `ucd_actor_gen_pairs`, color maps
- Output state: `ucd_ttool_xml_base`, `ucd_ttool_xml`, `ucd_generation_validation`

Generation-specific architecture observations:

- File numbering no longer matches logical step numbering because the hybrid retrieval step was inserted after the original refactor. `step2_elements.py` is logical step 3, `step3_review.py` is logical step 4, and so on.
- `generation/session_io.py` serializes not just the diagram but also retrieval suggestions and export results, so the saved XML is effectively a wizard snapshot.
- `generation/sysml_ucd.py` is both a rendering and export utility. It produces SysML v1 text, SysML v2 text, and SVG previews from session state.
- The active generator is coupled to both old and new CBR code: it uses `helpers_old` for suggestions, `MyCBR/mycbr_rest.py` for legacy symbolic retrieval on port 8080, and the active verification package for export-time validation.

## 4. Active Verification Flow

The active verifier is also a thin orchestrator. `ucd_verification.py` calls `verification/step_manager.py`, which manages a multi-diagram verification loop over one uploaded XML.

Verification runtime flow:

1. `verification/step1_upload.py` is the gate. It hashes the uploaded file, parses it via `verification/xml_parser.py`, saves the raw XML in session state, and immediately runs `_run_all_validators()` across the whole parsed dataset.
2. `verification/xml_parser.py` transforms TTool XML into a nested in-memory structure: modeling tab -> list of UCD dicts -> element groups. Every actor, use case, system boundary, and connector carries mutable `Comments` and `Action` metadata.
3. `verification/step_manager.py` flattens all parsed diagrams into a sequence with `get_diagram_list()`. It advances one diagram at a time with `advance_diagram()`, looping steps 2-6 until the last diagram, then enters results.
4. `verification/step2_system.py`, `verification/step3_actors.py`, and `verification/step4_usecases.py` are mainly presentation layers over the precomputed metadata from step 1. They only rerun validators if `ver_pre_verified` is absent.
5. `verification/step5_semantics.py` reruns only structural checks: boundary arrangement and connectivity.
6. `verification/step5_relationships.py` is logically step 6. It lets the user confirm or override Include/Extend/Generalization classification and direction. It writes comments/actions directly into connector metadata, then calls `advance_diagram()`.
7. `verification/step6_results.py` is the final aggregator. It deliberately does not call `UcdVerificationParser.processData()` because the batch validators clear comments. Instead it reruns only structural validators, collects issue groups from `verification/element_verification.py`, appends activity panels through `verification/activity_panel.py`, and offers download plus optional TTool launch via `verification/ttool_launcher.py`.

Verification state/data contracts:

- Wizard state: `ver_current_step`, `ver_completed_steps`, `ver_processing`
- Diagram loop state: `ver_current_diagram`
- Parsed model state: `ver_ucd_instance`, `ver_ucd_dataset`, `ver_uploaded_xml`, `ver_last_file_hash`
- Confirmation/finalization state: `ver_validated_ucds`, `ver_finalized`, `ver_pre_verified`

Verification NLP and rule architecture:

- `verification/element_verification.py` is the active rule engine. It contains batch uniqueness checks, per-element naming checks, geometry checks, connectivity checks, relationship checks, and issue collectors for exports.
- `verification/text_tools.py` is the active NLP layer. It uses spaCy `en_core_web_trf`, NLTK word lists/WordNet, and a CrossEncoder from `verification/nlp_setup.py`. Flair is no longer part of the active verification flow.
- `verification/activity_panel.py` is the export builder that writes verification notes back into TTool-friendly `AvatarADPanel` tabs and appends requirement rules from `ucd_rules.xml`.

Verification-specific architecture observations:

- Verification is front-loaded. The main design choice is to pay the validation cost once at upload, then treat the rest of the UI as a view/editor over cached metadata.
- The parser still has a `processData()` method, but the active flow avoids it in results because its batch validators would wipe previously accumulated comments.
- The included `verification/VERIFICATION_ANALYSIS.md` accurately reflects the active package structure.

## 5. Standalone `MyCBR` Architecture

`MyCBR/app.py` is a separate Streamlit app. It is not routed from `main.py`. Its internal architecture is a full CBR cycle built on top of the existing SQL case base plus a local retained-case JSON store.

Standalone `MyCBR` flow:

1. Build: the app collects or loads a working case into `mycbr_cycle_*` session keys.
2. Check: `MyCBR/cycle.py` normalizes the payload through `ParserOperations._validate_and_fix_ucd()` and validates it with the active verification rule engine.
3. Retrieve: `MyCBR/retrieval.py` combines SQL retrieval from `cbr_search.py` with a second path that scores locally retained JSON cases using the same feature model.
4. Reuse & Revise: `MyCBR/cycle.py` calls `cbr_merge.py` for merge logic, then re-normalizes and re-validates the result.
5. Retain: `MyCBR/repository.py` writes only to `MyCBR/data/retained_cases.json`.
6. Export: `MyCBR/project_export.py` generates `.myCBR`, `.myCB`, `.myExp`, `.config`, `.prj`, `casebase.csv`, and zipped workspace artifacts under `MyCBR/output/`.

Standalone `MyCBR` persistence and reuse:

- `MyCBR/repository.py` canonicalizes SQL cases by calling `fetch_case_data()` from `cbr_merge.py`.
- It also discovers a local myCBR Workbench executable but does not require it for export generation.
- `MyCBR/app.py` includes an additional "full MySQL export" path that flattens all nine SQL tables into canonical CSVs.

Important boundary:

- `MyCBR/mycbr_rest.py` exists in this subproject, but the standalone `MyCBR` app does not use it for its main flow. That client is instead consumed by generation step 2 for the older Workbench REST server on port 8080.

## 6. `MyCBR_Integration` Split Architecture

This is a separate distributed design that splits reuse/export logic in Python from retrieval/storage logic in Java.

Build and runtime boundary:

- `MyCBR_Integration/scripts/build_server.ps1` compiles Java sources against `MyCBR_Integration/sdk/mycbr.jar`. It assumes a local JDK 25 installation.
- `MyCBR_Integration/scripts/run_server.ps1` launches `mycbr.integration.MyCBRHttpServer` on port `8099` and passes a runtime directory.

Python side:

- `MyCBR_Integration/python/bridge.py` is the adapter. It converts a full UCD case into the service payload shape, then exposes `service_health`, `list_service_cases`, `reset_service`, `sync_service_cases`, `add_case_to_service`, `query_service`, and `retain_and_push`.
- The bridge deliberately reuses Python-side normalization, reuse, validation, and export from `MyCBR/cycle.py`, `MyCBR/project_export.py`, and `MyCBR/repository.py`.
- `MyCBR_Integration/python/app.py` mirrors the standalone MyCBR UI, but swaps local retrieval/storage for service calls. Its tabs are `Service`, `Build`, `Check`, `Retrieve`, `Reuse & Revise`, and `Retain & Export`.

Java side:

- `MyCBR_Integration/java/src/mycbr/integration/MyCBRHttpServer.java` exposes `GET /health`, `GET /cases`, `POST /cases/reset`, `POST /cases/import`, `POST /cases/add`, and `POST /query`.
- `ServiceState` persists cases to `MyCBR_Integration/runtime/service_case_store.json`, rebuilds a myCBR in-memory project on every reset/import/add, and creates three similarity profiles: `balanced`, `structure`, and `text`.
- The Java service owns storage, indexing, and myCBR similarity execution. Python still owns UCD normalization, reuse/revise, retained-case authoring, and export bundling.

Critical integration observation:

- The new `MyCBR_Integration` architecture is not wired into the main generator. `generation/step2_hybrid_retrieval.py` still talks to the older Workbench REST path on `localhost:8080`, not this new Java service on `8099`.

## 7. Legacy Crosswalk

| Legacy file | Original responsibility | Current replacement | Still active? |
|---|---|---|---|
| `ucd_generation_old.py` | Early simple CBR matcher UI over DB values and `match_case()` | Active generation wizard in `generation/` plus `cbr_search.py` | No |
| `ucd_generation_old2.py` | Monolithic multi-step generator with retrieval, editing, and export | `ucd_generation.py` + `generation/` package | No direct imports |
| `helpers_old.py` | Old DB suggestion expansion, reverse lookup, simple set-based matching | Partly replaced by `helpers.py` and `cbr_search.py` | Yes, still imported by active generation UI |
| `ucd_validation.py` | Monolithic verification UI | `ucd_verification.py` + `verification/` package | No |
| `ucd_validation_operation.py` | Old parser + validator + NLP resource bundle | `verification/xml_parser.py`, `verification/element_verification.py`, `verification/text_tools.py`, `verification/nlp_setup.py` | Yes, still imported by `cbr_merge.py` as `element_validation` |
| `verification/ui_page.py` | Intermediate extracted verification page | `verification/step_manager.py` + step files | No active entrypoint |
| `fileupload_operations.py` | Old XML-to-DB importer for the pre-casebase schema | `fileupload.py` + `Parser.py` | No |
| `SpacyandFlair.py` | Older NLP validation helpers | `verification/text_tools.py` for active verification | Still used by support validators via `fetch_ucd_entities.py` |
| `postag.py` | Standalone NLP analysis page | No direct replacement; mainly exploratory/support | Standalone only |

The practical outcome is that the repo has been refactored, but not fully severed from legacy code. The active product path is modular; the shared utility layer is still partially hybrid.

## 8. Final Synthesis

The current architecture has four real centers of gravity.

1. The root Streamlit shell in `main.py` is a router and auth gate. It serves two active product flows, generation and verification, plus admin/upload/view/edit utilities.
2. The active generation system is a wizard over `ucd_*` session state. It starts from free text or a saved session, performs hybrid retrieval, edits a single mutable relationship model, then exports validated XML and optionally saves a new SQL case.
3. The active verification system is a wizard over one uploaded XML, but its center of truth is a nested parsed dataset in `ver_ucd_dataset`. It front-loads expensive validation, iterates per diagram, and exports the original XML enriched with verification panels.
4. The repo also contains two separate CBR products. `MyCBR` is a standalone pure-Python cycle over SQL plus a retained JSON store; `MyCBR_Integration` is a split Python/Java architecture using the myCBR SDK directly. Neither is routed through the main shell.

Runtime entrypoints:

- Main app: `main.py`
- Standalone CBR cycle: `MyCBR/app.py`
- Standalone Python/Java bridge UI: `MyCBR_Integration/python/app.py`
- Standalone support UIs: `mycbr_explorer.py`, `usecase_db_verifier.py`, `db_usecase_validation.py`, `postag.py`
- Support scripts: `start_mycbr_rest.bat`, `MyCBR_Integration/scripts/build_server.ps1`, `MyCBR_Integration/scripts/run_server.ps1`, `fileUploadMain.py`

Persistence matrix:

- MySQL: `cases`, `diagrams`, `actors`, `use_cases`, `relationships`, `case_domains`, `actor_synonyms`, `use_case_synonyms`, `system_synonyms`, `credentials`
- Generation session snapshot XML: `generation/session_io.py`
- Local retained CBR store: `MyCBR/data/retained_cases.json`
- Java service store: `MyCBR_Integration/runtime/service_case_store.json`
- Generated myCBR bundles: `MyCBR/output/`
- Verification-enriched TTool XML exports: built in `verification/step6_results.py` and `generation/step9_cbr_export.py`

Session-state ownership:

- Shell: `logged_in`, `menu_selection`, logout flags
- Generation: `ucd_*`, retrieval caches, color/pair editors, export caches
- Verification: `ver_*`, diagram index, parsed dataset
- Standalone MyCBR: `mycbr_cycle_*`
- Integration UI: `mycbr_bridge_*`

External dependency map:

- MySQL through `connection.py`
- Gemini or OpenAI-compatible LLM endpoints through `helpers.py` and `Parser.py`
- Gmail SMTP through `admin_login_operations.py`
- Sentence-transformers, CrossEncoder, spaCy transformer models, NLTK downloads
- Old myCBR Workbench REST server on `localhost:8080` through `MyCBR/mycbr_rest.py` and `start_mycbr_rest.bat`
- New Java myCBR SDK service on `localhost:8099` through `MyCBR_Integration/python/bridge.py`
- Local TTool executable discovery through `verification/ttool_launcher.py`

What is active today:

- Inside the main app, the active product paths are the modular generation and verification packages plus the auth/upload/view/edit utilities.
- The standalone CBR subprojects exist in the current workspace and are functional as separate apps, but they are not integrated into the main navigation.
- The repo still carries meaningful technical debt from the migration: modern code still imports `helpers_old.py` and `ucd_validation_operation.py`.
- There are two different myCBR strategies in parallel. The old 8080 Workbench REST path is what generation currently uses; the new 8099 Java SDK service is a separate standalone architecture.

## Follow-up Options

If needed later, the natural next steps are:

1. Turn this walkthrough into a dependency graph and "what to edit where" maintainer guide.
2. Follow with a bug/risk audit of the active paths only.
3. Follow with a cleanup plan to remove or isolate the legacy dependencies that are still live.

# UCDForge — In-Depth Module Reference

UCDForge uses **Case-Based Reasoning (CBR)** and **LLMs** to generate and verify **UML Use Case Diagrams** from plain-text descriptions.

---

## Quick Start

```bash
git clone https://github.com/nachimageshnachi/UCDForge.git
cd UCDForge
python -m venv venv && venv\Scripts\activate      # Windows
pip install -r requirements.txt
python -m spacy download en_core_web_trf
python -m spacy download en_core_web_md
python -c "import nltk; nltk.download('wordnet'); nltk.download('words'); nltk.download('averaged_perceptron_tagger_eng')"
streamlit run main.py
```

Configure `.streamlit/secrets.toml` — see the **Secrets** section below.

---

## System Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.10 – 3.11 | 3.12 not yet tested |
| MySQL | 8.x | Must be running before `streamlit run` |
| Java JDK | 17+ | Only for MyCBR REST server |
| LM Studio | Latest | Optional — local offline LLM |

---

## LLM Integration

The app supports two interchangeable providers, switchable via the sidebar.

### Option A — Google Gemini / Gemma (Cloud)

No extra SDK needed. The app calls the Generative Language REST API directly via `requests`.

**Recommended models**

| Model ID | Notes |
|---|---|
| `gemma-3-27b-it` | Gemma 3 27B — free tier |
| `gemini-1.5-flash` | Fast, low-cost |
| `gemini-2.5-flash` | Latest default |

**Get a free key:** <https://aistudio.google.com/apikey>

```toml
[gemini]
api_key = "YOUR_GOOGLE_AI_STUDIO_API_KEY"
model   = "gemma-3-27b-it"
```

### Option B — LM Studio (Local / Offline)

LM Studio exposes an OpenAI-compatible REST endpoint. The `openai` Python package (already in `requirements.txt`) is used as the HTTP client.

**Install:** <https://lmstudio.ai>

**Recommended models** (download inside LM Studio → Discover tab):

| Model | Context | RAM needed |
|---|---|---|
| `mistralai/Mistral-7B-Instruct-v0.3` | 32k | ~8 GB |
| `google/gemma-3-4b-it` | 128k | ~4 GB |
| `google/gemma-3-12b-it` | 128k | ~12 GB |
| `google/gemma-3-27b-it` | 128k | ~24 GB |
| `Qwen/Qwen2.5-7B-Instruct` | 128k | ~8 GB |

**Start the server:** LM Studio → Developer tab → select model → Start Server (default `http://localhost:1234`).

```toml
[llm]
provider = "openai_compatible"
base_url = "http://localhost:1234/v1"
api_key  = "lm-studio"
model    = "mistralai/Mistral-7B-Instruct-v0.3"
```

---

## MySQL Setup

```sql
CREATE DATABASE CBR CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cbr_user'@'localhost' IDENTIFIED BY 'strong_password';
GRANT ALL PRIVILEGES ON CBR.* TO 'cbr_user'@'localhost';
FLUSH PRIVILEGES;
```

All tables are created automatically on first run.

---

## Secrets File

Create `.streamlit/secrets.toml` (never committed — it is in `.gitignore`):

```toml
[mysql]
host     = "localhost"
port     = 3306
user     = "cbr_user"
password = "strong_password"
database = "CBR"

[llm]
provider = "openai_compatible"
base_url = "http://localhost:1234/v1"
api_key  = "lm-studio"
model    = "mistralai/Mistral-7B-Instruct-v0.3"

[gemini]
api_key = "YOUR_GOOGLE_AI_STUDIO_API_KEY"
model   = "gemma-3-27b-it"

[email]
sender   = "your_gmail@gmail.com"
password = "your_gmail_app_password"
```

---

## Python Dependencies

```bash
pip install -r requirements.txt
```

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | 1.36.0 | Web UI |
| `streamlit-option-menu` | latest | Sidebar navigation |
| `openai` | latest | LM Studio client |
| `requests` | transitive | Gemini REST calls |
| `pymysql` | latest | MySQL connector |
| `cryptography` | latest | Password hashing support |
| `passlib[bcrypt]` | latest | Bcrypt password hashing |
| `transformers` | 4.41.2 | HuggingFace model utils |
| `sentence-transformers` | 2.7.0 | Semantic embeddings |
| `torch` | 2.2.2 | Deep learning backend |
| `spacy` | 3.7.5 | NLP pipeline |
| `flair` | 0.13.1 | Additional NER/tagging |
| `nltk` | 3.9.1 | WordNet, POS tagger |
| `scikit-learn` | 1.5.1 | Cosine similarity, ML utils |
| `pandas` | 2.2.2 | Data handling |
| `numpy` | 1.26.4 | Numerical operations |
| `scipy` | 1.13.1 | Scientific computing |
| `pdfplumber` | latest | PDF text extraction |
| `openpyxl` | latest | Excel export |
| `sysml2py` | latest | SysML parsing |

---

## Module Reference

---

### `main.py` — Application Entry Point

**Purpose:** Bootstraps the Streamlit multi-page application and controls routing.

**How it works:**
- Defines the `MultiApp` class which maintains a list of named page functions.
- Renders a `streamlit-option-menu` sidebar that switches between pages.
- Two sidebar states exist: unauthenticated (Home, UCD Verification, UCD Generation, Admin Login) and authenticated (Upload XML, View, Edit, Logout).
- Routes are protected with `login_required=True`; unauthenticated access shows an error.

**Key session state keys:** `logged_in`, `logout_triggered`, `menu_selection`.

```
streamlit run main.py   →   http://localhost:8501
```

---

### `connection.py` — MySQL Connection Manager

**Purpose:** Thread-safe, context-manager based MySQL connection wrapper.

**Design:**
- Opens a **new connection per request** — avoids shared-state threading bugs in Streamlit.
- `connection.get_cursor(dictionary=True)` is a `@contextmanager` that: opens the connection, yields the cursor, commits on success, rolls back on exception, closes everything on exit.
- Credentials are read exclusively from `st.secrets["mysql"]` — never hardcoded.

**Usage pattern:**
```python
from connection import connection
with connection.get_cursor(dictionary=True) as cursor:
    cursor.execute("SELECT * FROM cases")
    rows = cursor.fetchall()
```

---

### `embeddings.py` — Semantic Embedding Engine

**Purpose:** Provides sentence embeddings for semantic similarity and hybrid ranking.

**Two models are used:**

| Constant | Model | Used for |
|---|---|---|
| `MODEL_LONG` | `BAAI/bge-large-en-v1.5` | Paragraphs, system descriptions |
| `MODEL_SHORT` | `sentence-transformers/all-mpnet-base-v2` | Short labels (actors, use-case names) |

- `_load_model()` is `@lru_cache` — models are loaded once per process.
- Auto-detects CUDA; falls back to CPU.
- BGE uses a retrieval instruction prefix: `"Represent this sentence for retrieval: "`.
- All vectors are **L2-normalized** (`normalize_embeddings=True`), enabling dot-product as cosine similarity.

**Hybrid ranking weights:**

| Weight profile | Use case |
|---|---|
| `CBR_WEIGHTS` | Use-case-first retrieval: use_cases (0.35), actors (0.24), domains (0.18) |
| `IR_WEIGHTS` | Title-first retrieval: title (0.33), description (0.25), lexical (0.17) |

**Key functions:**
- `embed_paragraph(text)` → JSON string of the BGE vector.
- `embed_short(text)` → JSON string of the mpnet vector.
- `rank_cases(candidates, mode)` → sorted list with `relevance` score added.

---

### `helpers.py` — LLM Extraction Core

**Purpose:** Calls the LLM to extract UCD elements (actors, use cases, relationships) from free text. Also contains all text normalization utilities.

**LLM pipeline:**
1. `_get_llm_provider()` reads `llm_provider` from session state or `secrets.toml`.
2. `_call_google_llm_text()` — calls Gemini via REST (`requests.post`).
3. `_call_openai_llm_text()` — calls LM Studio via `openai.OpenAI(base_url=...)`.
4. Both paths send a combined system+user message (for local model compatibility).

**Extraction tiers (in `ask_llm_extract`):**

| Document length | Strategy |
|---|---|
| < 8 000 chars | Single direct LLM call |
| 8 000–30 000 chars | Sequential Recursive Refine across word chunks |
| > 30 000 chars | Semantic RAG: chunk → embed → rank → merge 3-4 calls |

**Semantic RAG (`_semantic_rag_condense`):** Embeds text chunks and query anchors via `embeddings._embed_local`, ranks chunks by cosine similarity to actor/use-case query terms, selects top chunks within a char budget.

**JSON repair (`_parse`):** Strips `<think>` blocks (Mistral), removes markdown fences, fixes bracket mismatches, repairs trailing commas — producing a valid dict even from malformed LLM output.

**Normalization helpers:** `_force_singular`, `_verb_objectify`, `_title_preserve_acronyms`, `_norm_rel_type`, `_norm_role_type`.

---

### `cbr_search.py` — Python CBR Retrieval Engine

**Purpose:** Retrieves the most similar past cases from MySQL using multi-field semantic and lexical similarity.

**Algorithm (`find_similar_cases`):**

1. **Query embedding** — encodes system_name (short model), description (long model), actor centroid, use-case centroid.
2. **Candidate fetch** — loads all cases from MySQL with their stored embeddings.
3. **Per-field similarity:**
   - `sim_title` — cosine similarity of title embeddings.
   - `sim_desc` — cosine similarity of description embeddings.
   - `sim_actors` / `sim_usecases` — **symmetric 1-to-1 greedy bipartite matching** (`_greedy_one_to_one`): each query term matches at most one case term and vice versa; prevents duplicate matching.
   - `sim_domains` — max(Jaccard overlap, semantic per-domain average).
   - `sim_lexical` — Jaccard over tokenized text + synonyms.
4. **Weighted ranking** — `embeddings.rank_cases()` applies `CBR_WEIGHTS` or `IR_WEIGHTS`.
5. **Synonym expansion (Python CBR only)** — `_fetch_global_synonyms()` and `_fetch_case_synonyms()` query the `actor_synonyms`, `use_case_synonyms`, and `system_synonyms` MySQL tables to expand the lexical token set before Jaccard scoring. **myCBR REST does not use these tables** — it receives the raw query dict and performs its own internal symbolic matching via the myCBR Workbench engine.

**Key function:** `find_similar_cases(query, mode, threshold, limit)` → sorted list of case dicts with `relevance` in [0,1].

---

### `cbr_merge.py` — Case Adaptation & TTool XML Builder

**Purpose:** Merges the user's partial diagram with a retrieved KB case, and generates TTool-compatible XML output.

**Merge logic (`merge_user_with_case`):**
- `_map_with_priority`: for each user element, finds the most similar KB element via cosine similarity. If similarity ≥ 0.86, the KB name is preferred (normalization). Otherwise the user's name is kept and added to the merged list.
- Actor lists (primary/secondary) and use-case lists are merged separately.
- Relationships are remapped through the name mapping, then validated via `ParserOperations._validate_and_fix_ucd`.

**TTool XML generation (`build_ttool_xml`):**
- Builds a `<TURTLEGMODELING>` XML document containing an Avatar Analysis modeling tab.
- `_build_ucd_panel`: auto-lays out actors (left = primary, right = secondary) and use cases (grid inside system boundary rectangle).
- Connector types: `110` association, `111` include, `112` generalization, `113` extend.
- Embeds SysML v1 (PlantUML) and SysML v2 textual notation as CDATA.
- Optionally appends the reference KB case panel alongside the generated panel.

**`build_parallel_ttool_xml`:** Produces two UCD panels + a guided Activity Diagram listing validation steps.

---

### `cbr_excel_export.py` — Similarity Report Exporter

**Purpose:** Builds a styled multi-sheet Excel workbook showing per-field similarity scores for both CBR engines.

**Sheets generated:**
- **Summary** — top cases from Python CBR and myCBR side by side with weighted scores.
- **Actor Detail** — per-query-actor best match and cosine score per case.
- **Use Case Detail** — per-query-use-case best match and cosine score per case.

Used in Step 2 (Hybrid Retrieval) via the "Download Similarity Report" button.

---

## Generation Wizard — `generation/`

The UCD generation flow is a **9-step wizard**. Each step is a separate module with a `render()` function called by `generation/step_manager.py`.

### `generation/step_manager.py`

Manages wizard navigation: `render_navigation(show_prev, show_next, next_label, on_next)` renders Prev/Next buttons and handles step transitions. `reset_from_step(n)` clears all session state for steps ≥ n when the user goes back.

### `generation/session_io.py`

Serializes/deserializes the wizard session state to/from JSON for the "Save Session" / "Load Session" feature (step 9).

### `generation/step1_input.py` — System Description Input

- Text area for the system description paragraph.
- File upload (PDF/TXT) using `pdfplumber`.
- Calls `helpers.ask_llm_extract()` to extract UCD elements.
- Populates `st.session_state`: `ucd_paragraph`, `ucd_system_name`, `ucd_primary_actors`, `ucd_secondary_actors`, `ucd_use_cases`, `ucd_domains`, `ucd_relationships`.
- LLM provider selector (Google / LM Studio) shown in the sidebar.

### `generation/step2_hybrid_retrieval.py` — Hybrid Retrieval

Runs Python CBR (`cbr_search.find_similar_cases`) and myCBR REST (`MyCBR.mycbr_rest.MyCBRRestClient.retrieve`) **in parallel** using `concurrent.futures.ThreadPoolExecutor`.

- Auto-detects if myCBR server is offline and launches `start_mycbr_rest.bat` automatically.
- Results shown side-by-side; cases appearing in **both** engines are highlighted as common matches.
- User selects one case → `_setup_kb_suggestions` calls `cbr_merge.fetch_case_data` and `cbr_merge.merge_user_with_case` to pre-populate suggestions for downstream steps.
- Excel similarity report available for download.

### `generation/step2_elements.py` — Element Review & Edit

Displays extracted elements (actors, use cases, relationships) as editable lists. User can add, remove, or rename items before proceeding.

### `generation/step3_review.py` — Diagram Preview

Shows an SVG preview of the current diagram state using `generation/sysml_ucd.render_sysml_panel`.

### `generation/step4_associations.py` — Association Relationships

Interactive actor ↔ use-case matrix. User draws association lines; KB suggestions (from step 2) are shown as checkboxes. Renders a color-coded SVG via `generation/shared.render_match_svg`.

### `generation/step5_includes.py` — Include Relationships

Use case ↔ use case `<<include>>` mapping. SVG shows base use case → included use case with dashed lines.

### `generation/step6_extends.py` — Extend Relationships

Use case ↔ use case `<<extend>>` mapping. User can set the extension condition text per relationship.

### `generation/step7_uc_generalization.py` — Use Case Generalization

Use case ↔ use case generalization (child specializes parent). Renders with `render_uc_uc_svg(key="ucg")`.

### `generation/step8_actor_generalization.py` — Actor Generalization

Actor ↔ actor generalization (child specializes parent). Renders with `render_uc_uc_svg(key="actg")`.

### `generation/step9_cbr_export.py` — Export & Save

Final step:
1. **TTool XML generation** — calls `cbr_merge.build_ttool_xml`, appends verification activity panels via `verification.activity_panel.append_grouped_activity_panels`.
2. **Automatic validation** — runs the verification pipeline on the generated XML (skipping relationship-type checks). Shows error/warning counts.
3. **Download** — `Download TTool UCD XML` button; auto-launches TTool if the `.bat` path is configured.
4. **Save to case base** — inserts the new case (with embeddings) into MySQL via `_save_to_case_base()`. Embeds all actors, use cases, domains, and relationships into their respective tables.
5. **SysML v2 panel** — renders SysML v1/v2 code and inline SVG.

Uses an MD5 signature (`_current_export_signature`) to detect staleness and rebuild the XML only when the diagram changes.

### `generation/shared.py` — Shared Utilities

- `dedupe(seq)` — case-insensitive, order-preserving deduplication.
- `ensure_actor_colors` / `ensure_uc_colors` — assigns consistent colors from a 15-color palette.
- `load_db_values()` / `build_suggestion_lists()` — loads actor/use-case vocabulary from DB, filters by POS validity (must start with VB, end with NN for use cases; must be singular NN for actors).
- `render_match_svg` — inline HTML+SVG actor ↔ use-case bipartite visualization.
- `render_uc_uc_svg` — inline HTML+SVG+JS use-case ↔ use-case visualization with JS-computed connector positions and fallback static lines.

### `generation/sysml_ucd.py` — SysML Diagram Generator

Generates three representations of the current diagram:

| Function | Output |
|---|---|
| `generate_sysml_v1_text(ss)` | PlantUML `@startuml` notation |
| `generate_sysml_v2_text(ss)` | Authentic SysML v2 textual (`use case def`, `part def`, `specializes`) |
| `render_ucd_svg(ss)` | Pure inline SVG (actors as stick figures, use cases as ellipses) |
| `render_sysml_panel(key)` | Streamlit panel: SVG preview + two collapsible code blocks + download buttons |

---

## Verification Pipeline — `verification/`

### `verification/step_manager.py`

Same wizard pattern as generation. Manages a 6-step verification flow.

### `verification/step1_upload.py` — File Upload

Accepts a TTool XML file. Validates it contains at least one `UseCaseDiagramPanel`. Hands off to `xml_parser.UcdVerificationParser`.

### `verification/xml_parser.py` — TTool XML Parser (`UcdVerificationParser`)

Parses TTool XML (`<TURTLEGMODELING>`) to extract:
- **Type 700** components → Primary Actors (stickman)
- **Type 701** components → Use Cases (ellipse)
- **Type 702** components → System Boundary (rectangle)
- **Type 703** components → Secondary Actors (box)
- **CONNECTOR** elements → Relationships with source/target resolved via `TGConnectingPoint` ID matching

Enforces: exactly one system boundary, ≥1 actor, ≥1 use case per panel.

`processData()` calls all element_verification checks.
`showUcdTables()` renders color-coded DataFrames (green = OK, yellow = Warning, red = Error).

### `verification/element_verification.py` — Rule Engine

The core rule engine. Each method validates a specific aspect:

| Method | Checks |
|---|---|
| `validateSystem(name)` | 2–6 words, ends with system noun (System, Platform, App…), no verbs |
| `validateActor(name, type)` | Singular noun, no pronouns, no verb-first, not a system-name echo |
| `validateUsecase(name, sys_name)` | Verb-Object format, 2–4 words, no system name repetition |
| `validateActors(actors)` | Duplicate detection across the full actor list |
| `validateUsecases(use_cases)` | Duplicate detection across the full use-case list |
| `validateArrangement(primary, secondary, ucs, sys)` | Actors outside boundary, use cases inside boundary (by X/Y coords) |
| `validateActorConnectivity(actors, ucs, connectors)` | Every actor connected to ≥1 use case |
| `validateUsecaseConnectivity(ucs, actors, connectors)` | Every use case connected to ≥1 actor |
| `validateRelations(connectors, actors, ucs)` | Correct source/target types per relationship type |
| `collect_issue_steps` | Flat list of `[ERR]`/`[WARN]` strings |
| `collect_grouped_steps` | Dict grouped by element category for Activity Panel generation |

### `verification/step2_system.py` — System Name Check

UI for the system boundary validation result.

### `verification/step3_actors.py` — Actor Verification

Displays per-actor validation results in a table with traffic-light styling.

### `verification/step4_usecases.py` — Use Case Verification

Displays per-use-case validation results.

### `verification/step5_relationships.py` — Relationship Verification

Validates connector types, source/target type correctness, self-loops, and duplicates.

### `verification/step5_semantics.py` — Semantic Similarity Check

Uses `embeddings.embed_short` to compute pairwise cosine similarity between actor names and use-case names inside the diagram — flags suspiciously similar names that might be duplicates.

### `verification/step6_results.py` — Summary Dashboard

Aggregates all verification results into a final dashboard with counts, per-element details, and an overall pass/fail verdict.

### `verification/text_tools.py`

Deep NLP utilities used by the verification rule engine:
- POS tagging via spaCy transformer model.
- Verb detection, noun phrase extraction, lemmatization.
- Checks for imperative verb form (use-case title requirement).
- Synonym lookup via NLTK WordNet.

### `verification/nlp_setup.py`

Lazy-loads the spaCy model (`en_core_web_trf` with `en_core_web_md` as fallback). Cached so the model loads only once per session.

### `verification/generate_ucd_rules.py`

Generates the `ucd_rules.xml` rule file consumed by TTool's built-in verification engine.

### `verification/activity_panel.py`

Builds Avatar Activity Diagram XML panels that embed verification findings as ordered action states inside the exported TTool file. `append_grouped_activity_panels(xml, groups)` injects one panel per issue group (Actors, Use Cases, System Boundary, etc.).

### `verification/ttool_launcher.py`

Utility to save the generated XML to the Downloads folder and launch TTool via a `.bat` file using `subprocess.Popen`.

### `verification/ui_page.py`

Top-level Streamlit page (`ucd_verification.app`). Wires together the upload, parsing, and step-by-step verification display.

---

## MyCBR Subsystem — `MyCBR/`

Standalone CBR cycle using the Java myCBR Workbench via its REST API.

### `MyCBR/mycbr_rest.py` — REST Client

`MyCBRRestClient` wraps the myCBR Workbench REST API:
- `retrieve(query, limit, threshold)` — submits a query and returns ranked cases.
- `mycbr_is_alive(url)` — health-check used by the generation wizard.
- Handles `ConnectionError` gracefully so the wizard can fall back to Python-only retrieval.

### `MyCBR/repository.py` — Case Repository

Manages JSON-based case storage for the standalone MyCBR app (separate from the MySQL case base).

### `MyCBR/retrieval.py` — Retrieval Logic

Applies CBR retrieval using the myCBR REST client and formats results for the standalone app.

### `MyCBR/cycle.py` — Full CBR Cycle

Implements the complete Retrieve → Reuse → Revise → Retain cycle as callable Python functions:
- `normalize_case_payload` — canonicalizes and validates a case dict.
- `validate_case_payload` — runs the element verification engine and returns findings + summary.
- `reuse_case_payload(query, candidate)` — merges query with the retrieved candidate via `cbr_merge.merge_user_with_case`.

### `MyCBR/project_export.py` — myCBR Project Exporter

Exports the MySQL case base into a `.prj` file loadable by myCBR Workbench, preserving actor/use-case similarity functions.

### `MyCBR/app.py` — Standalone CBR UI

A full self-contained Streamlit app for running the CBR cycle outside the main wizard. Useful for testing retrieval in isolation.

---

## MyCBR Java Integration — `MyCBR_Integration/`

Provides a Java microservice exposing a REST API for CBR retrieval, bridged to Python via HTTP.

### `MyCBR_Integration/python/app.py`

Streamlit UI that communicates with the Java CBR service.

### `MyCBR_Integration/scripts/`

- `build_server.ps1` — compiles the Java service via Maven.
- `run_server.ps1` — starts the compiled JAR.

### `MyCBR_Integration/java/`

Java source for the CBR microservice (Spring Boot + myCBR SDK).

---

## Admin & Auth Modules

### `admin_login.py` / `admin_login_operations.py`

Login form + bcrypt password verification. Supports "Forgot Password" flow via email OTP.

### `resetpassword.py`

Password reset via Gmail SMTP. Reads `[email]` credentials from `secrets.toml`. Sends a one-time code.

### `fileupload.py` / `fileupload_operations.py`

Admin-only XML import. Parses a TTool XML file and inserts actors, use cases, and relationships into the `systems`/`actors`/`use_cases`/`relations` legacy tables. Used to bulk-seed the legacy database schema.

### `view.py` / `view_operations.py`

Read-only display of case-base records for authenticated admins.

### `edit.py` / `edit_operations.py`

Edit case-base records (actor names, use-case descriptions) for authenticated admins.

### `logout.py`

Clears `st.session_state` and resets `logged_in` to `False`.

---

## Database Schema

Tables auto-created on first run:

| Table | Description |
|---|---|
| `cases` | Core case records: title, description, embeddings, domain JSON |
| `diagrams` | TTool XML and PlantUML per case |
| `actors` | Actor name, type (Primary/Secondary), embedding, per case |
| `use_cases` | Use-case name, description, embedding, per case |
| `relationships` | Typed relationships (association/include/extend/generalization), per case |
| `case_domains` | Domain tags with embedding, per case |
| `actor_synonyms` | Synonym vocabulary for actors (aids retrieval recall) |
| `use_case_synonyms` | Synonym vocabulary for use cases |
| `system_synonyms` | Synonym vocabulary for system names |

---

## Standalone Tools

| Command | Purpose |
|---|---|
| `streamlit run MyCBR/app.py` | Standalone CBR cycle UI |
| `streamlit run MyCBR_Integration/python/app.py` | Java bridge UI |
| `streamlit run mycbr_explorer.py` | Browse and inspect the case base |
| `pwsh MyCBR_Integration/scripts/build_server.ps1` | Build Java CBR service |
| `pwsh MyCBR_Integration/scripts/run_server.ps1` | Run Java CBR service |
| `start_mycbr_rest.bat` | Launch myCBR Workbench REST server |

---

## Documentation

| File | Description |
|---|---|
| [`COMPLETE_REPO_ARCHITECTURE_REVIEW.md`](COMPLETE_REPO_ARCHITECTURE_REVIEW.md) | Full architecture walkthrough |
| [`verification/VERIFICATION_ANALYSIS.md`](verification/VERIFICATION_ANALYSIS.md) | Verification pipeline design notes |
| [`MyCBR/README.md`](MyCBR/README.md) | Standalone CBR cycle guide |
| [`MyCBR_Integration/README.md`](MyCBR_Integration/README.md) | Java integration setup |

---

*Developed as a Final Year Project at University College Dublin (UCD).*

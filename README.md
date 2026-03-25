# UCDForge — AI-Assisted Use Case Diagram Generation & Verification

UCDForge is a methodological assistant that applies **Case-Based Reasoning (CBR)** and **Large Language Models (LLMs)** to help software engineers and students create, validate, and refine **UML Use Case Diagrams (UCDs)** following established UCD modeling standards.

The system is built on [Streamlit](https://streamlit.io) and connects to a MySQL case base, NLP models, and optionally the [myCBR Workbench](http://mycbr-project.net/).

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Standalone Components](#standalone-components)
- [Documentation](#documentation)

---

## Features

| Feature | Description |
|---|---|
| **UCD Generation Wizard** | Multi-step wizard that extracts UML entities from free text, PDFs, or saved sessions via LLM, retrieves similar past cases using hybrid CBR, and lets the user refine actors, use cases, associations, includes, extends, and generalizations. |
| **Hybrid Case Retrieval** | Combines semantic (sentence-transformer embeddings) and lexical (SQL) retrieval from a MySQL case base, plus optional symbolic retrieval from the myCBR REST server. |
| **UCD Verification Wizard** | Upload TTool XML files and receive automated verification of diagram structure, naming conventions, actor/use-case semantics, and relationship classification. |
| **TTool XML Export** | Generates fully structured TTool-compatible XML with embedded verification activity panels and UCD rule notes, ready to import into the TTool MBSE tool. |
| **SysML Export** | Exports the generated diagram as SysML v1 and SysML v2 text alongside an SVG preview. |
| **Admin Panel** | Secure admin login with bcrypt-hashed credentials, OTP email reset via Gmail SMTP, and direct case-base view/edit/upload utilities. |
| **MyCBR Standalone App** | A self-contained CBR cycle (build → check → retrieve → reuse & revise → retain → export) with local JSON case retention and full myCBR bundle export. |
| **MyCBR Integration App** | A Python/Java split architecture using the myCBR SDK directly through a local HTTP service, providing `balanced`, `structure`, and `text` similarity profiles. |

---

## Architecture Overview

```
main.py  (Streamlit shell & auth router)
├── UCD Generation   → generation/step_manager.py  → steps 1–9
│                         ↳ helpers.py (LLM extraction)
│                         ↳ cbr_search.py (semantic + lexical retrieval)
│                         ↳ cbr_merge.py (reuse & revise)
│                         ↳ MyCBR/mycbr_rest.py (myCBR Workbench on :8080)
│                         ↳ verification/ (export-time validation)
│
├── UCD Verification → verification/step_manager.py → steps 1–6
│                         ↳ verification/xml_parser.py
│                         ↳ verification/element_verification.py
│                         ↳ verification/text_tools.py  (spaCy + NLTK + CrossEncoder)
│                         ↳ verification/activity_panel.py (TTool XML enrichment)
│
├── Admin / Upload / View / Edit
│     ↳ Parser.py  (TTool XML → MySQL ingestion)
│     ↳ connection.py (PyMySQL context manager)
│
MyCBR/app.py              (standalone CBR cycle, not routed from main.py)
MyCBR_Integration/
  python/app.py           (Python/Java bridge UI, not routed from main.py)
  java/ MyCBRHttpServer   (Java myCBR SDK service on :8099)
```

For a fully detailed walkthrough of every module, see [`COMPLETE_REPO_ARCHITECTURE_REVIEW.md`](COMPLETE_REPO_ARCHITECTURE_REVIEW.md).

---

## Project Structure

```
CBR/
├── main.py                        # App entry point
├── requirements.txt               # Python dependencies
├── start_mycbr_rest.bat           # Auto-starts myCBR Workbench REST server
├── plantuml.jar                   # PlantUML renderer (used by Parser.py)
│
├── generation/                    # UCD generation wizard steps
│   ├── step_manager.py
│   ├── step1_input.py
│   ├── step2_hybrid_retrieval.py
│   ├── step2_elements.py
│   ├── step3_review.py … step9_cbr_export.py
│   ├── session_io.py
│   ├── sysml_ucd.py
│   └── shared.py
│
├── verification/                  # UCD verification wizard steps
│   ├── step_manager.py
│   ├── step1_upload.py … step6_results.py
│   ├── xml_parser.py
│   ├── element_verification.py
│   ├── text_tools.py
│   ├── nlp_setup.py
│   ├── activity_panel.py
│   ├── ttool_launcher.py
│   └── VERIFICATION_ANALYSIS.md
│
├── MyCBR/                         # Standalone CBR cycle app
│   ├── app.py
│   ├── cycle.py
│   ├── retrieval.py
│   ├── repository.py
│   ├── project_export.py
│   ├── mycbr_rest.py
│   └── README.md
│
├── MyCBR_Integration/             # Python/Java hybrid CBR app
│   ├── python/app.py
│   ├── python/bridge.py
│   ├── java/src/ …
│   ├── scripts/build_server.ps1
│   ├── scripts/run_server.ps1
│   └── README.md
│
├── Parser.py                      # TTool XML → MySQL ingestion engine
├── helpers.py                     # LLM-based free-text extraction pipeline
├── embeddings.py                  # Sentence-transformer + ranking weights
├── cbr_search.py                  # Hybrid case retrieval
├── cbr_merge.py                   # Case reuse, revise & TTool XML rebuild
├── cbr_excel_export.py            # Excel comparison report
├── connection.py                  # MySQL connection context manager
├── fetch_ucd_entities.py          # DB entity validator (support tool)
├── admin_login.py / _operations   # Admin auth (bcrypt + OTP email)
├── resetpassword.py               # Password reset flow
├── fileupload.py / _operations    # XML / ZIP ingestion pages
├── view.py / view_operations.py   # Case-base browser
├── edit.py / edit_operations.py   # Direct case-base editor
├── mycbr_explorer.py              # Standalone myCBR case explorer
├── usecase_db_verifier.py         # Standalone DB-level verifier
├── simulate_weights.py            # Retrieval weight simulation
├── simulate_ga_weights.py         # GA-optimised weight simulation
├── COMPLETE_REPO_ARCHITECTURE_REVIEW.md
└── .streamlit/config.toml         # Streamlit theme & layout settings
```

---

## Prerequisites

| Requirement | Version / Notes |
|---|---|
| Python | 3.10 or 3.11 recommended |
| MySQL | 8.x — must be running before starting the app |
| Java JDK | 17+ (only needed for `MyCBR_Integration` Java service) |
| TTool | Optional — needed to open exported XML files |
| myCBR Workbench | Optional — needed for the legacy `:8080` REST retrieval path |

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/nachimageshnachi/UCDForge.git
cd UCDForge

# 2. Create and activate a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Download required spaCy models
python -m spacy download en_core_web_trf
python -m spacy download en_core_web_md

# 5. Download NLTK data (first run will also prompt automatically)
python -c "import nltk; nltk.download('wordnet'); nltk.download('words'); nltk.download('averaged_perceptron_tagger_eng')"
```

---

## Configuration

Create a `.streamlit/secrets.toml` file (never commit this — it is in `.gitignore`):

```toml
[mysql]
host     = "localhost"
port     = 3306
user     = "your_db_user"
password = "your_db_password"
db       = "your_database_name"

[llm]
# Choose one: "gemini" or "openai_compatible"
provider    = "gemini"
api_key     = "YOUR_GEMINI_OR_OPENAI_API_KEY"
model       = "gemini-1.5-flash"
base_url    = ""  # Only needed for OpenAI-compatible local endpoints

[email]
sender   = "your_gmail@gmail.com"
password = "your_gmail_app_password"
```

Ensure your MySQL database is running and reachable with the credentials above. The app creates all required tables automatically on first use.

---

## Running the Application

### Main App (Generation + Verification + Admin)

```bash
streamlit run main.py
```

Navigates to `http://localhost:8501` by default.

### Start myCBR REST Server (optional, for hybrid retrieval)

```bat
start_mycbr_rest.bat
```

This launches the myCBR Workbench REST server on `localhost:8080`. The generation wizard will attempt this automatically during Step 2.

---

## Standalone Components

| Component | How to run | Port |
|---|---|---|
| Standalone CBR Cycle | `streamlit run MyCBR/app.py` | 8502 (suggested) |
| Python/Java Bridge UI | `streamlit run MyCBR_Integration/python/app.py` | 8503 (suggested) |
| Build Java service | `pwsh MyCBR_Integration/scripts/build_server.ps1` | — |
| Run Java service | `pwsh MyCBR_Integration/scripts/run_server.ps1` | 8099 |
| Case-base browser | `streamlit run mycbr_explorer.py` | 8504 (suggested) |
| DB verifier | `streamlit run usecase_db_verifier.py` | 8505 (suggested) |

---

## Documentation

| Document | Description |
|---|---|
| [`COMPLETE_REPO_ARCHITECTURE_REVIEW.md`](COMPLETE_REPO_ARCHITECTURE_REVIEW.md) | Deep-dive static architecture walkthrough of all modules, flows, and data contracts |
| [`verification/VERIFICATION_ANALYSIS.md`](verification/VERIFICATION_ANALYSIS.md) | Design analysis of the verification pipeline |
| [`MyCBR/README.md`](MyCBR/README.md) | Standalone CBR cycle usage guide |
| [`MyCBR_Integration/README.md`](MyCBR_Integration/README.md) | Python/Java integration setup and usage |

---

## License

This project was developed as a Final Year Project (FYP) at University College Dublin (UCD). All rights reserved by the author.

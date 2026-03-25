# UCDForge — AI-Assisted Use Case Diagram Generation & Verification

UCDForge is a methodological assistant that uses **Case-Based Reasoning (CBR)** and **LLMs** to help engineers and students generate and verify **UML Use Case Diagrams (UCDs)** from plain-text system descriptions.

---

## Requirements

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10 or 3.11 | Application runtime |
| MySQL | 8.x | User accounts, case-base storage |
| Java JDK | 17+ | MyCBR REST server *(optional, for hybrid retrieval)* |
| LM Studio | Latest | Local LLM inference *(optional, offline mode)* |

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/nachimageshnachi/UCDForge.git
cd UCDForge
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `torch` (~2 GB) will be downloaded on first install. Ensure you have a stable internet connection and at least 4 GB of free disk space.

### 4. Download NLP models

```bash
# spaCy transformer & medium models (used for POS-tagging and NER)
python -m spacy download en_core_web_trf
python -m spacy download en_core_web_md

# NLTK resources (WordNet, vocabulary, POS tagger)
python -c "import nltk; nltk.download('wordnet'); nltk.download('words'); nltk.download('averaged_perceptron_tagger_eng')"
```

---

## MySQL Setup

UCDForge uses **MySQL 8.x** to store user accounts and the case-base. The application creates all required tables automatically on first run.

### Install MySQL

- **Windows**: Download and run the [MySQL Community Installer](https://dev.mysql.com/downloads/installer/).  
  Select **MySQL Server 8.x** during setup. Note the root password you set.
- **macOS**: `brew install mysql && brew services start mysql`
- **Linux (Debian/Ubuntu)**: `sudo apt install mysql-server && sudo systemctl start mysql`

### Create a database and user

```sql
-- Log in as root
mysql -u root -p

-- Create a dedicated database
CREATE DATABASE CBR CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create an application user (replace the password)
CREATE USER 'cbr_user'@'localhost' IDENTIFIED BY 'your_strong_password';
GRANT ALL PRIVILEGES ON CBR.* TO 'cbr_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

> The app auto-creates all tables (`users`, `cases`, etc.) the first time it runs — no manual schema import needed.

---

## LLM Integration

UCDForge supports **two interchangeable LLM providers** for UCD extraction. Switch between them at any time via the sidebar in the app, or set a default in `secrets.toml`.

---

### Option A — Google Gemini / Gemma (Cloud, recommended)

The app calls the **Google Generative Language REST API** directly — no SDK required beyond `requests`.

**Supported models:**

| Model ID | Description |
|---|---|
| `gemma-3-27b-it` | Gemma 3 27B Instruct — free tier on Google AI Studio |
| `gemini-1.5-flash` | Fast, low-cost Gemini model |
| `gemini-2.5-flash` | Latest flash model (default fallback) |

**How to get a free API key:**

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with a Google account.
3. Click **Create API key** → copy the key.

**No additional Python package** is needed for Gemini/Gemma; the app uses the `requests` library (already in `requirements.txt`).

Configure in `.streamlit/secrets.toml`:

```toml
[gemini]
api_key = "YOUR_GOOGLE_AI_STUDIO_API_KEY"
model   = "gemma-3-27b-it"   # or "gemini-1.5-flash", "gemini-2.5-flash"
```

---

### Option B — LM Studio (Local / Offline)

**LM Studio** runs large language models entirely on your local machine. UCDForge talks to it through LM Studio's built-in **OpenAI-compatible server**, so no internet connection is needed during inference.

#### Install LM Studio

1. Download from [https://lmstudio.ai](https://lmstudio.ai) (Windows / macOS / Linux).
2. Install and launch the application.

#### Download a model inside LM Studio

In the **Discover** tab, search for and download one of these recommended models:

| Model | Context | Notes |
|---|---|---|
| `mistralai/Mistral-7B-Instruct-v0.3` | 32k | Default — fast, accurate |
| `google/gemma-3-4b-it` | 128k | Gemma 3 4B Instruct — lightweight |
| `google/gemma-3-12b-it` | 128k | Gemma 3 12B Instruct — more capable |
| `google/gemma-3-27b-it` | 128k | Gemma 3 27B Instruct — best quality (needs ≥24 GB VRAM) |
| `Qwen/Qwen2.5-7B-Instruct` | 128k | Good alternative |

> Choose a model that fits your GPU/CPU RAM. A 7B-parameter model requires roughly 8–16 GB RAM depending on quantisation.

#### Start the LM Studio local server

1. In LM Studio, open the **Developer** tab (rocket icon).
2. Select your downloaded model from the dropdown.
3. Click **Start Server** — it defaults to `http://localhost:1234`.

The server exposes an OpenAI-compatible REST API at `http://localhost:1234/v1`.

#### Configure in `secrets.toml`

```toml
[llm]
base_url = "http://localhost:1234/v1"
api_key  = "lm-studio"        # any non-empty string; LM Studio does not validate keys
model    = "mistralai/Mistral-7B-Instruct-v0.3"   # must match the model loaded in LM Studio
```

The `openai` Python package (in `requirements.txt`) is used as the HTTP client for LM Studio.

---

## Configure Secrets

Create **`.streamlit/secrets.toml`** (this file is listed in `.gitignore` and is **never committed**):

```toml
[mysql]
host     = "localhost"
port     = 3306
user     = "cbr_user"
password = "your_strong_password"
database = "CBR"

# ── LLM provider ─────────────────────────────────────────
# Set provider to "google" to use Gemini/Gemma (Option A)
# Set provider to "openai_compatible" to use LM Studio (Option B)

[llm]
provider = "openai_compatible"          # "google" | "openai_compatible"
base_url = "http://localhost:1234/v1"   # LM Studio server (ignored when provider = "google")
api_key  = "lm-studio"                  # any string for LM Studio; ignored for Google
model    = "mistralai/Mistral-7B-Instruct-v0.3"

[gemini]
api_key = "YOUR_GOOGLE_AI_STUDIO_API_KEY"
model   = "gemma-3-27b-it"

[email]
sender   = "your_gmail@gmail.com"
password = "your_gmail_app_password"    # Gmail App Password (not your main password)
```

> You can configure **both** `[llm]` and `[gemini]` sections simultaneously and switch between providers from the app sidebar without restarting.

---

## Python Dependencies

All Python packages are listed in `requirements.txt` and installed with `pip install -r requirements.txt`:

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | 1.36.0 | Web UI framework |
| `streamlit-option-menu` | latest | Sidebar navigation |
| `openai` | latest | LM Studio OpenAI-compatible client |
| `requests` | (transitive) | Google Gemini REST calls |
| `pymysql` | latest | MySQL database connector |
| `cryptography` | latest | Secure password hashing support |
| `passlib[bcrypt]` | latest | Password hashing |
| `transformers` | 4.41.2 | Hugging Face model utilities |
| `sentence-transformers` | 2.7.0 | Semantic embedding models |
| `torch` | 2.2.2 | Deep learning backend for embeddings |
| `spacy` | 3.7.5 | NLP pipeline (POS tagging, NER) |
| `flair` | 0.13.1 | Additional NLP tagging |
| `nltk` | 3.9.1 | Wordnet, vocabulary resources |
| `scikit-learn` | 1.5.1 | Cosine similarity, ML utilities |
| `pandas` | 2.2.2 | Case-base data handling |
| `numpy` | 1.26.4 | Numerical operations |
| `scipy` | 1.13.1 | Scientific computing |
| `pdfplumber` | latest | PDF text extraction |
| `openpyxl` | latest | Excel export |
| `sysml2py` | latest | SysML parsing utilities |

---

## Running the App

### Main application (Generation + Verification + Admin)

```bash
streamlit run main.py
```

Opens at **http://localhost:8501**

### Optional — Start the myCBR REST server (for hybrid retrieval in Step 2)

```bat
start_mycbr_rest.bat
```

Starts the myCBR Workbench on `localhost:8080`. The generation wizard attempts this automatically.

---

## Standalone Tools

| Tool | Command |
|---|---|
| Standalone CBR Cycle | `streamlit run MyCBR/app.py` |
| Python/Java Bridge UI | `streamlit run MyCBR_Integration/python/app.py` |
| Build Java CBR service | `pwsh MyCBR_Integration/scripts/build_server.ps1` |
| Run Java CBR service | `pwsh MyCBR_Integration/scripts/run_server.ps1` |
| Case-base browser | `streamlit run mycbr_explorer.py` |

---

## Documentation

| File | Description |
|---|---|
| [`COMPLETE_REPO_ARCHITECTURE_REVIEW.md`](COMPLETE_REPO_ARCHITECTURE_REVIEW.md) | Full module-by-module architecture walkthrough |
| [`verification/VERIFICATION_ANALYSIS.md`](verification/VERIFICATION_ANALYSIS.md) | Verification pipeline design |
| [`MyCBR/README.md`](MyCBR/README.md) | Standalone CBR cycle guide |
| [`MyCBR_Integration/README.md`](MyCBR_Integration/README.md) | Java integration setup |

---

*Developed as a Final Year Project at University College Dublin (UCD).*

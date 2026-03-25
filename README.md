# UCDForge — AI-Assisted Use Case Diagram Generation & Verification

UCDForge is a methodological assistant that uses **Case-Based Reasoning (CBR)** and **LLMs** to help engineers and students generate and verify **UML Use Case Diagrams (UCDs)**.

---

## Requirements

| Tool | Version |
|---|---|
| Python | 3.10 or 3.11 |
| MySQL | 8.x (must be running) |
| Java JDK | 17+ *(only for MyCBR_Integration)* |

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

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Download NLP models

```bash
python -m spacy download en_core_web_trf
python -m spacy download en_core_web_md
python -c "import nltk; nltk.download('wordnet'); nltk.download('words'); nltk.download('averaged_perceptron_tagger_eng')"
```

### 5. Configure secrets

Create the file `.streamlit/secrets.toml` (this is **never committed**):

```toml
[mysql]
host     = "localhost"
port     = 3306
user     = "your_db_user"
password = "your_db_password"
db       = "your_database_name"

[llm]
provider = "gemini"            # or "openai_compatible"
api_key  = "YOUR_API_KEY"
model    = "gemini-1.5-flash"
base_url = ""                  # leave empty for Gemini

[email]
sender   = "your_gmail@gmail.com"
password = "your_gmail_app_password"
```

> The app automatically creates all required MySQL tables on first run.

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

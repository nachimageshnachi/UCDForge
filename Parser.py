import re
import streamlit as st
import xml.etree.ElementTree as ET
from connection import connection
import json
import requests

from embeddings import embed_paragraph, embed_short
from helpers import _title_preserve_acronyms as _title_case_acronyms, _force_singular as _force_singular, _verb_objectify as _verb_objectify

class ParserOperations:
    def __init__(self, file_name):
        self._file_name = file_name

    @staticmethod
    def createTables():
        with connection.get_cursor() as cursor:
            schema_sql = """
            -- Main case table
            CREATE TABLE cases (
                case_id INT PRIMARY KEY AUTO_INCREMENT,
                title VARCHAR(255),
                description TEXT,
                title_embedding JSON,
                description_embedding JSON,
                domain_json JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Diagrams table (1-to-1 with cases)
            CREATE TABLE diagrams (
                case_id INT PRIMARY KEY,
                system_name VARCHAR(255),
                plantuml_code TEXT,
                xml_content LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                generated_by ENUM('system', 'manual') DEFAULT 'manual',
                generation_score INT DEFAULT '100',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            -- Actors table (linked directly to case_id)
            CREATE TABLE actors (
                actor_id INT PRIMARY KEY AUTO_INCREMENT,
                case_id INT,
                actor_name VARCHAR(255),
                actor_type VARCHAR(100),
                actor_reference_number INT DEFAULT 700 CHECK (actor_reference_number IN (700, 703)),
                name_embedding JSON,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            -- Use Cases table (linked directly to case_id)
            CREATE TABLE use_cases (
                use_case_id INT PRIMARY KEY AUTO_INCREMENT,
                case_id INT,
                name VARCHAR(255),
                description TEXT,
                name_embedding JSON,
                description_embedding JSON,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            -- Relationships table (linked directly to case_id)
            CREATE TABLE relationships (
                relationship_id INT AUTO_INCREMENT PRIMARY KEY,
                relationship_type VARCHAR(50),  -- Extend, Include, Association
                relation_code VARCHAR(10),
                source_name VARCHAR(255),
                target_name VARCHAR(255),
                source_type ENUM('actor', 'usecase'),
                target_type ENUM('actor', 'usecase'),
                extension VARCHAR(255),
                case_id INT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            -- Case domains table (normalized)
            CREATE TABLE case_domains (
                id INT AUTO_INCREMENT PRIMARY KEY,
                case_id INT,
                domain_name VARCHAR(255),
                domain_embedding JSON,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            -- Synonyms for canonical names (per case, normalized at write)
            CREATE TABLE actor_synonyms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                case_id INT NOT NULL,
                actor_name VARCHAR(255) NOT NULL,
                synonym VARCHAR(255) NOT NULL,
                UNIQUE KEY uq_actor_syn (case_id, actor_name, synonym),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            CREATE TABLE use_case_synonyms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                case_id INT NOT NULL,
                use_case_name VARCHAR(255) NOT NULL,
                synonym VARCHAR(255) NOT NULL,
                UNIQUE KEY uq_uc_syn (case_id, use_case_name, synonym),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );

            CREATE TABLE system_synonyms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                case_id INT NOT NULL,
                system_name VARCHAR(255) NOT NULL,
                synonym VARCHAR(255) NOT NULL,
                UNIQUE KEY uq_sys_syn (case_id, system_name, synonym),
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            );
            """

            for statement in schema_sql.strip().split(";"):
                if statement.strip():
                    cursor.execute(statement + ";")

        print("Created Tables")

    @staticmethod
    def destroyTables():
        with connection.get_cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in ['actor_synonyms','use_case_synonyms','system_synonyms','relationships', 'actors', 'use_cases', 'diagrams', 'case_domains', 'cases']:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        print("Destroyed Tables")

    @staticmethod
    def clearTables():
        with connection.get_cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in ['actor_synonyms','use_case_synonyms','system_synonyms','relationships', 'actors', 'use_cases', 'diagrams', 'case_domains', 'cases']:
                cursor.execute(f"DELETE FROM {table}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        print("Cleared Tables")

    @staticmethod
    def _safe_id(name: str) -> str:
        """Sanitize a name into a valid PlantUML alias."""
        return "".join(c if c.isalnum() else "_" for c in name).strip("_")

    @staticmethod
    def generate_plantuml(stickman_actors, box_actors, use_cases, system_name, relationships):
        """
        Generate SysML v1 (PlantUML) textual notation.
        Mirrors generation/sysml_ucd.py format.
        """
        print("Generating PlantUML Code")
        _sid = ParserOperations._safe_id
        lines = ["@startuml", ""]

        # Outer Use Case diagram frame
        lines.append(f"rectangle \"uc {system_name} Use Case\" {{")
        lines.append("")

        # Primary Actors (inside frame, outside the system boundary)
        if stickman_actors:
            lines.append("    ' Primary Actors")
            for a in stickman_actors:
                lines.append(f"    actor \"{a}\" as A_{_sid(a)}")
            lines.append("")

        # Inner system boundary (use cases go inside here)
        lines.append(f"    package \"{system_name}\" {{")
        lines.append("")

        # Collect extension text per *target* UC
        ext_map = {uc: [] for uc in use_cases}
        for r in relationships:
            if (r.get("Value") or "").lower() == "extend" and r.get("Target Name") in ext_map:
                ext = (r.get("Extension") or "").strip()
                if ext:
                    ext_map[r["Target Name"]].append(ext)

        if use_cases:
            lines.append("        ' Use Cases")
            for uc in use_cases:
                lines.append(f"        usecase \"{uc}\" as UC_{_sid(uc)}")
            lines.append("")

        lines.append("    }")      # close inner system boundary
        lines.append("")

        # Secondary Actors (inside frame, outside the system boundary)
        if box_actors:
            lines.append("    ' Secondary Actors")
            for a in box_actors:
                lines.append(f"    actor \"{a}\" as A_{_sid(a)}")
            lines.append("")

        lines.append("}")          # close outer UC frame
        lines.append("")

        # Build name → alias map
        all_actors = list(stickman_actors) + list(box_actors)

        def _alias(name):
            if name in all_actors:
                return f"A_{_sid(name)}"
            return f"UC_{_sid(name)}"

        # Relationships
        for r in relationships:
            s = _alias(r["Source Name"])
            t = _alias(r["Target Name"])
            code = int(r.get("Relation Code", 0) or 0)
            val  = (r.get("Value") or "").lower()
            ext  = (r.get("Extension") or "").strip()

            if code == 111 or "include" in val:
                lines.append(f"{s} ..> {t} : <<include>>")
            elif code == 113 or "extend" in val:
                cond = f"\\nCondition: {ext}" if ext else ""
                lines.append(f"{s} .up.> {t} : <<extend>>{cond}")
            elif code == 112 or "general" in val:
                lines.append(f"{s} --|> {t}")
            else:
                lines.append(f"{s} -- {t}")

        lines.append("")
        lines.append("@enduml")
        return "\n".join(lines)

    
    @staticmethod
    def validate_ai_json(data, use_cases=None):
        print("Validating Model Output")
        # Check top-level keys
        required_keys = ["system_description", "domains", "use_case_descriptions"]
        for key in required_keys:
            if key not in data:
                return False, f"Missing key: {key}"

        # Check system_description is a non-empty string
        system_desc = data["system_description"]
        if not isinstance(system_desc, str) or not system_desc.strip():
            return False, "system_description must be a non-empty string"

        # Check domains is a non-empty list of non-empty strings
        domains = data["domains"]
        if (
            not isinstance(domains, list) 
            or len(domains) == 0 
            or not all(isinstance(d, str) and d.strip() for d in domains)
        ):
            return False, "domains must be a non-empty list of non-empty strings"

        # Check use_case_descriptions is a dict of string->non-empty string
        ucd = data["use_case_descriptions"]
        if not isinstance(ucd, dict):
            return False, "use_case_descriptions must be a dictionary"
        for k, v in ucd.items():
            if not (isinstance(k, str) and k.strip()):
                return False, "use_case_descriptions keys must be non-empty strings"
            if not (isinstance(v, str) and v.strip()):
                return False, "use_case_descriptions values must be non-empty strings"

        # Check keys in use_case_descriptions match provided use_cases list
        if use_cases is not None:
            missing = [uc for uc in use_cases if uc not in ucd]
            if missing:
                return False, f"Missing use case descriptions for: {missing}"

        return True, ""

    # =================================================================
    #  LLM provider abstraction  (Google Gemini primary, LM Studio fallback)
    # =================================================================

    @staticmethod
    def _extract_json_from_response(content: str) -> dict:
        """Clean up raw LLM text and parse as JSON."""
        content = content.strip()

        # Extract JSON object from surrounding text
        first, last = content.find("{"), content.rfind("}")
        if first != -1 and last != -1:
            content = content[first:last + 1]

        # Remove code fences if present
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9]*\n", "", content)
            content = re.sub(r"\n```$", "", content)

        # Remove trailing commas before } or ]
        content = re.sub(r",(\s*[}\]])", r"\1", content)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Model output is not valid JSON: {e}\nRaw output:\n{content}")

    @staticmethod
    def _get_provider() -> str:
        """Return the active provider name: 'google' or 'openai'."""
        # UI choice takes priority
        choice = st.session_state.get("llm_provider")
        if choice:
            return choice.lower()
        # Fallback to secrets
        return (st.secrets.get("llm", {}).get("provider") or "google").lower()

    @staticmethod
    def _call_llm(messages: list[dict], *, temperature: float = 0.0,
                  max_tokens: int = 8000) -> str:
        """
        Send messages to the configured LLM and return the raw text reply.
        Supports:
          • 'google'  — Google AI Studio Gemini REST API (primary)
          • 'openai'  — Any OpenAI-compatible endpoint, e.g. LM Studio (fallback)
        """
        provider = ParserOperations._get_provider()

        if provider == "google":
            return ParserOperations._call_google(messages, temperature=temperature,
                                                  max_tokens=max_tokens)
        else:
            return ParserOperations._call_openai(messages, temperature=temperature,
                                                  max_tokens=max_tokens)

    # ---- Google Gemini --------------------------------------------------
    @staticmethod
    def _call_google(messages: list[dict], *, temperature: float = 0.0,
                     max_tokens: int = 8000) -> str:
        cfg = st.secrets.get("gemini", {})
        api_key = cfg.get("api_key") or ""
        model   = cfg.get("model") or "gemini-2.5-flash"

        if not api_key:
            raise RuntimeError(
                "Google Gemini API key not configured. "
                "Add [gemini] api_key = \"...\" to .streamlit/secrets.toml"
            )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent?key={api_key}"
        )

        # Translate OpenAI-style messages → Gemini contents
        # Gemini only supports "user" and "model" roles.
        # System messages get prepended to the first user message.
        system_text = ""
        contents = []
        for m in messages:
            role = m.get("role", "user")
            text = m.get("content", "")
            if role == "system":
                system_text += text + "\n\n"
            else:
                final_text = (system_text + text) if system_text else text
                system_text = ""  # consumed
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": final_text}]
                })

        # If only system messages remain (no user turn), wrap into user
        if system_text and not contents:
            contents.append({"role": "user", "parts": [{"text": system_text}]})

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        resp = requests.post(url, json=body)
        resp.raise_for_status()
        result = resp.json()

        # Extract text from Gemini response
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError(f"Unexpected Gemini response structure:\n{json.dumps(result, indent=2)}")

    # ---- OpenAI-compatible (LM Studio, etc.) ----------------------------
    @staticmethod
    def _call_openai(messages: list[dict], *, temperature: float = 0.0,
                     max_tokens: int = 8000) -> str:
        llm_config = st.secrets["llm"]
        url = f"{llm_config['base_url']}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config['api_key']}"
        }

        data = {
            "model": llm_config["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 1,
            "n": 1,
            "stream": False,
            "stop": ["```"]
        }

        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]

    @staticmethod
    def render_llm_selector():
        """Render a Streamlit radio widget to choose the LLM provider."""
        provider = st.radio(
            "🤖 LLM Provider",
            options=["Google Gemini (Free)", "LM Studio (Local)"],
            index=0,
            horizontal=True,
            key="llm_provider_radio",
        )
        # Map display label → internal key
        st.session_state["llm_provider"] = (
            "google" if "Google" in provider else "openai"
        )

    @staticmethod
    def dataFromGPT(stickman_actors, box_actors, use_cases, system_name, relationships, plantuml_code):

        print(f"Sending prompt to LLM for the {system_name}")

        prompt = f"""
    You are a senior system analyst AI with expertise in interpreting SysML / UML use case diagrams and structured metadata.

    You will be provided with:
    1. System boundary name (string)
    2. List of primary actors (array of strings)
    3. List of secondary actors (array of strings)
    4. List of individual use cases (array of strings)
    5. Relationships between actors and use cases (array of dictionaries, each with these keys):
        - "Relation Code": Internal numeric identifier for the relationship. Standard codes:
            * 110 — association (communication link showing participation in a Use case)
            * 111 — include (one Use case always incorporates another)
            * 112 — generalization (inheritance between actors or between Use cases)
            * 113 — extend (one Use case adds optional behavior to another under certain conditions)
        - "Value": The UML relationship type — exactly one of "association", "include", "extend", "generalization", or "specialization".
        - "Source Name": Name of the source element (actor or Use case).
        - "Source Type": Type of source — exactly "actor" or "usecase".
        - "Target Name": Name of the target element (actor or Use case).
        - "Target Type": Type of target — exactly "actor" or "usecase".
        - "Extension": For extend relationships only — the extension point condition. For other relationship types, leave empty.
    6. Full SysML v1 (PlantUML) Use case diagram code (string) generated in the following format:
        - Outer UC frame: `rectangle "uc <system name> Use Case" {{ ... }}`
        - Primary actors (inside frame): `actor "<Actor Name>" as A_<SafeId>`
        - System boundary (inside frame): `package "<system name>" {{ ... }}`
        - Use cases (inside system boundary): `usecase "<Use case Name>" as UC_<SafeId>`
        - Secondary actors (inside frame): `actor "<Actor Name>" as A_<SafeId>`
        - Relationships (outside all frames):
            * Association (110): `A_Source -- UC_Target`
            * Include (111): `UC_Source ..> UC_Target : <<include>>`
            * Extend (113): `UC_Source .up.> UC_Target : <<extend>>`
            * Generalization (112): `Source --|> Target`

    Note: `<SafeId>` is the element name with non-alphanumeric characters replaced by underscores.

    OBJECTIVE:
    Analyze the PlantUML diagram and all provided metadata together. Cross-check and reconcile items across sources (PlantUML, Use case list, actors lists, relationships). Produce a single, backend-ready JSON object suitable for ingestion into case-based reasoning systems.

    OUTPUT FORMAT:
    Return exactly one valid JSON object (no extra text):

    {{
        "system_description": "<Complete, expert description of what the system does based solely on provided inputs and with what other stakeholders it interracts and especially what stakeholder interacts with what actions of the system. No speculation or invented features.>",
        "domains": ["<Up to 5 of the most relevant and highly specific thematic domains directly derived from the provided Use case diagram, actors, and relationships. These should reflect the functional scope and core business areas shown in the diagram. Order by relevance.>"],
        "use_case_descriptions": {{
            "<Use case Name>": "<Describe how the system interacts with its stakeholders for this use case: which stakeholders are involved, what actions they take, and what their interests/outcomes are. Keep it concise, factual, and grounded only in the provided actors/relationships.>"
        }}
    }}

    STRICT INSTRUCTIONS (follow in order):
    - Use only the provided inputs. Do not invent features or add functionality not implied by the data.
    - All descriptions must be professional, precise, non-redundant, and directly tied to actors and relationships present in the inputs.
    - Ensure the JSON is syntactically valid and parseable by Python's `json.loads`.
    - All JSON keys and string values must use double quotes.
    - Domains must be specific, directly relevant to the use cases and actors, and ranked by relevance (core business/functionality first).
    - Deduplicate domains and Use cases: no duplicates or repeated descriptions. If duplicate Use case names appear, merge and synthesize them into one canonical description.
    - **Use exactly the provided Use case names, without altering spelling, spacing, capitalization, or punctuation. DO NOT "fix" typos.** Preserve line breaks that appear in the PlantUML.
    - Before responding, take the provided Use case list (above) and ensure every one appears as a key in `use_case_descriptions`. If any are missing, add them with a concise, factual description. Missing keys are not allowed.
    - Do not add new use case names that were not provided.

    - Take an agentic, multi-pass reasoning approach:
        1. Internally generate multiple candidate outputs across several reasoning iterations.
        2. Compare and evaluate each candidate for factual accuracy, completeness, and clarity against the provided inputs.
        3. Extract the best, non-duplicative elements from all candidates and synthesize them into the final JSON.
        4. Produce the final JSON that is the most contextually accurate, concise, and complete representation possible.
    - You may spend additional internal processing effort to refine and synthesize—final answer must still be a single JSON object in this response.
    - Remove all line breaks from string values unless explicitly part of a Use case name or an extension condition.
    - Do not alter the content or formatting of Use case names or extension conditions, including line breaks that appear in the PlantUML.
    
    ACTUAL INPUT for which you have to perform the Objective:
    System name:
    "{system_name}"

    Primary actors:
    {json.dumps(stickman_actors, indent=4)}

    Secondary actors:
    {json.dumps(box_actors, indent=4)}

    Use cases:
    {json.dumps(use_cases, indent=4)}

    Relationships:
    {json.dumps(relationships, indent=4)}

    PlantUML code:
    \"\"\"
    {plantuml_code}
    \"\"\"

    """
        
        # 🧠 Safety cutoff for very large prompts
        if len(prompt) > 15000:
            print(f"⚠️ Prompt too long ({len(prompt)} characters) — truncating for safety")
            st.warning(f"⚠️ Prompt too long ({len(prompt)} chars) — truncated to 15,000. Results may be incomplete.")
            prompt = prompt[:15000] + "\n...(truncated)"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior system analyst AI with expertise in SysML / UML use case diagrams. "
                    "You must output JSON exactly in the same key names as provided in the input. "
                    "Never add, remove, or change any characters in the keys. "
                    "If the key is 'Generate Branded RUS', it must be identical in output, without parentheses or extra text."
                )
            },
            {
                "role": "user",
                "content": prompt
            },
            {
                "role": "system",
                "content": "Final check: Ensure the keys in 'use_case_descriptions' exactly match the ones given in the input."
            }
        ]

        REQUIRED_KEYS = ["system_description", "domains", "use_case_descriptions"]

        try:
            content = ParserOperations._call_llm(messages, temperature=0.0, max_tokens=8000)
            parsed = ParserOperations._extract_json_from_response(content)

            if not isinstance(parsed, dict):
                raise ValueError(f"Model output is not a JSON object: {type(parsed)}")

            missing_keys = [k for k in REQUIRED_KEYS if k not in parsed]
            if missing_keys:
                raise ValueError(f"Missing required keys in model output: {missing_keys}")

            return parsed

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Request failed: {e}")

    @staticmethod
    def _normalize_actor_like(name: str) -> str:
        n = _title_case_acronyms(name or "")
        return _force_singular(n)

    @staticmethod
    def _normalize_use_case(name: str) -> str:
        n = _verb_objectify(name or "")
        n = _title_case_acronyms(n)
        return _force_singular(n)

    @staticmethod
    def synonymsFromGPT(system_name: str, actors: list[str], use_cases: list[str]) -> dict:
        """
        Ask the LLM for up to 15 synonyms per canonical name,
        following strict naming rules. Returns a dict with keys:
          { 'system_name_synonyms': [..], 'actor_synonyms': {name:[..]}, 'use_case_synonyms': {name:[..]} }
        """
        # Build deterministic, compact prompt
        actors_list = "\n".join(f"- {a}" for a in actors)
        ucs_list = "\n".join(f"- {u}" for u in use_cases)

        prompt = f"""
You are a senior SysML analyst. Propose concise alternative names (synonyms/aliases) that strictly follow naming rules.

INPUT:
- System: {system_name}
- Actors:\n{actors_list}
- Use Cases:\n{ucs_list}

RULES:
- All outputs are Title Case; preserve acronyms in ALL CAPS (e.g., GPS).
- All items must be singular; never pluralize anything.
- Do not invent entities; only name variants for what is provided.

- Actors (and System): noun phrases; 1–3 words; no determiners (no 'the', 'a'); no prepositions; no gerunds; examples: 'Bank Customer', 'Payment Gateway', 'Sensor'.
- Use Cases: imperative Verb–Object; 2–3 words (max 4 only if essential); object is singular; avoid adverbs/adjectives; examples: 'Validate PIN', 'Acquire Data', 'Store Result'.

OUTPUT JSON SCHEMA (return exactly one object, no prose):
{{
  "system_name_synonyms": ["string"],            // up to 15 entries max
  "actor_synonyms": {{                           // up to 15 entries per actor
    "<Actor>": ["string"]
  }},
  "use_case_synonyms": {{                        // up to 15 entries per use case
    "<Use Case>": ["string"]
  }}
}}

CONSTRAINTS:
- Max 15 per list; de-duplicate case-insensitively.
- Keep each variant short and compliant with the rules above.
"""

        messages = [
            {"role": "system", "content": "Output one valid JSON object only. No commentary."},
            {"role": "user", "content": prompt},
        ]

        try:
            content = ParserOperations._call_llm(messages, temperature=0.2, max_tokens=2000)
            parsed = ParserOperations._extract_json_from_response(content)

            # Normalize and cap
            out = {
                "system_name_synonyms": [],
                "actor_synonyms": {},
                "use_case_synonyms": {}
            }

            sys_syn = parsed.get("system_name_synonyms") or []
            seen = set()
            for s in sys_syn:
                if not isinstance(s, str):
                    continue
                n = ParserOperations._normalize_actor_like(s)
                if n and n.lower() not in seen:
                    seen.add(n.lower())
                    out["system_name_synonyms"].append(n)
                if len(out["system_name_synonyms"]) >= 15:
                    break

            act_map = parsed.get("actor_synonyms") or {}
            for k, arr in act_map.items():
                if not isinstance(k, str) or not isinstance(arr, list):
                    continue
                canon = ParserOperations._normalize_actor_like(k)
                a_seen = set()
                out_list = []
                for s in arr:
                    if not isinstance(s, str):
                        continue
                    n = ParserOperations._normalize_actor_like(s)
                    if n and n.lower() not in a_seen:
                        a_seen.add(n.lower())
                        out_list.append(n)
                    if len(out_list) >= 15:
                        break
                out["actor_synonyms"][canon] = out_list

            uc_map = parsed.get("use_case_synonyms") or {}
            for k, arr in uc_map.items():
                if not isinstance(k, str) or not isinstance(arr, list):
                    continue
                canon = ParserOperations._normalize_use_case(k)
                u_seen = set()
                out_uc = []
                for s in arr:
                    if not isinstance(s, str):
                        continue
                    n = ParserOperations._normalize_use_case(s)
                    if n and n.lower() not in u_seen:
                        u_seen.add(n.lower())
                        out_uc.append(n)
                    if len(out_uc) >= 15:
                        break
                out["use_case_synonyms"][canon] = out_uc

            return out
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Request failed: {e}")

    @staticmethod
    def _validate_and_fix_ucd(stickman_actors, box_actors, use_cases, relationships):
        """Apply exhaustive UCD validation and light repair:
        - Normalize names
        - Enforce relationship type constraints
        - Remove conflicting Include/Extend pairs (and reverse-direction conflicts)
        - Ensure each actor has at least one association, except when it inherits via generalization
        Returns possibly adjusted (stickman_actors, box_actors, use_cases, relationships).
        """
        # Normalize names (title case + singular rules)
        prim = [_title_case_acronyms(a) for a in stickman_actors or []]
        prim = [_force_singular(a) for a in prim]
        sec = [_title_case_acronyms(a) for a in box_actors or []]
        sec = [_force_singular(a) for a in sec]
        ucs = [_force_singular(_title_case_acronyms(_verb_objectify(u))) for u in (use_cases or [])]

        # De-dup while preserving order
        def _dedupe(xs):
            seen = set(); out = []
            for x in xs:
                k = (x or "").strip().lower()
                if k and k not in seen:
                    seen.add(k); out.append(x)
            return out

        prim = _dedupe(prim)
        sec = _dedupe(sec)
        ucs = _dedupe(ucs)
        all_actors = prim + sec

        # Index helpers
        def _is_actor(name):
            return (name or "").strip() in all_actors
        def _is_uc(name):
            return (name or "").strip() in ucs

        # Pass 1: normalize relationships + enforce type constraints
        rels = []
        for r in relationships or []:
            try:
                rt = (r.get("Value") or r.get("relationship_type") or "association").lower()
                st = (r.get("Source Type") or r.get("source_type") or "").strip().lower()
                tt = (r.get("Target Type") or r.get("target_type") or "").strip().lower()
                sn = r.get("Source Name") or r.get("source_name") or ""
                tn = r.get("Target Name") or r.get("target_name") or ""
                ext = (r.get("Extension") or r.get("extension") or "").strip()
                # Normalize names
                if st == 'actor':
                    sn = ParserOperations._normalize_actor_like(sn)
                else:
                    sn = ParserOperations._normalize_use_case(sn)
                if tt == 'actor':
                    tn = ParserOperations._normalize_actor_like(tn)
                else:
                    tn = ParserOperations._normalize_use_case(tn)

                # Enforce types
                if rt in {"include", "extend"}:
                    st = tt = 'usecase'
                    if not (_is_uc(sn) and _is_uc(tn)):
                        continue
                elif rt == 'generalization':
                    # keep only actor-actor or uc-uc
                    same_type = ((st == 'actor' and tt == 'actor') or (st == 'usecase' and tt == 'usecase'))
                    if not same_type:
                        continue
                    # names must exist in their domains
                    if st == 'actor' and (not _is_actor(sn) or not _is_actor(tn)):
                        continue
                    if st == 'usecase' and (not _is_uc(sn) or not _is_uc(tn)):
                        continue
                else:
                    # association
                    rt = 'association'
                    # allow actor->uc or uc->actor only
                    if not ((st == 'actor' and tt == 'usecase') or (st == 'usecase' and tt == 'actor')):
                        continue
                    # both names exist
                    if st == 'actor' and (not _is_actor(sn) or not _is_uc(tn)):
                        continue
                    if st == 'usecase' and (not _is_uc(sn) or not _is_actor(tn)):
                        continue

                rels.append({
                    "Relation Code": r.get("Relation Code") or r.get("relation_code") or None,
                    "Value": rt,
                    "Source Name": sn,
                    "Source Type": 'actor' if (rt=='association' and st=='actor') else ('usecase' if st=='usecase' else st),
                    "Target Name": tn,
                    "Target Type": 'usecase' if (rt=='association' and tt=='usecase') else ('actor' if tt=='actor' else tt),
                    "Extension": ext if rt=='extend' else "",
                })
            except Exception:
                continue

        # Pass 2: remove Include/Extend conflicts (same and reverse direction)
        include_pairs = set()
        extend_pairs = set()
        cleaned = []
        for r in rels:
            rt = r["Value"]
            if rt == 'include':
                key = (r["Source Name"].lower(), r["Target Name"].lower())
                rev = (key[1], key[0])
                if key in extend_pairs or rev in include_pairs or rev in extend_pairs:
                    continue
                include_pairs.add(key)
                cleaned.append(r)
            elif rt == 'extend':
                key = (r["Source Name"].lower(), r["Target Name"].lower())
                rev = (key[1], key[0])
                if key in include_pairs or rev in include_pairs or rev in extend_pairs:
                    continue
                extend_pairs.add(key)
                cleaned.append(r)
            else:
                cleaned.append(r)

        # Pass 3: ensure every actor has at least one association (or inherits via generalization)
        actor_assoc = {a: 0 for a in all_actors}
        actor_parents = {a: set() for a in all_actors}
        for r in cleaned:
            if r["Value"] == 'association':
                if r["Source Type"] == 'actor':
                    actor_assoc[r["Source Name"]] = actor_assoc.get(r["Source Name"], 0) + 1
                elif r["Target Type"] == 'actor':
                    actor_assoc[r["Target Name"]] = actor_assoc.get(r["Target Name"], 0) + 1
            elif r["Value"] == 'generalization' and r["Source Type"] == 'actor' and r["Target Type"] == 'actor':
                # child -> parent
                actor_parents.setdefault(r["Source Name"], set()).add(r["Target Name"])

        # helper to check inherited assoc via any ancestor
        def _has_inherited_assoc(actor):
            seen = set(); stack = [actor]
            while stack:
                cur = stack.pop()
                if cur in seen: continue
                seen.add(cur)
                if actor_assoc.get(cur, 0) > 0:
                    return True
                stack.extend(list(actor_parents.get(cur, set())))
            return False

        if ucs:
            most_common_uc = None
            # pick the UC with most associations today
            uc_counts = {u:0 for u in ucs}
            for r in cleaned:
                if r["Value"] == 'association':
                    if r["Source Type"] == 'usecase':
                        uc_counts[r["Source Name"]] = uc_counts.get(r["Source Name"],0)+1
                    if r["Target Type"] == 'usecase':
                        uc_counts[r["Target Name"]] = uc_counts.get(r["Target Name"],0)+1
            most_common_uc = max(uc_counts, key=lambda k: uc_counts[k]) if uc_counts else ucs[0]

            for a in all_actors:
                if actor_assoc.get(a,0) == 0 and not _has_inherited_assoc(a):
                    # Add a low-confidence association to ensure diagram completeness
                    cleaned.append({
                        "Relation Code": 110,
                        "Value": 'association',
                        "Source Name": a,
                        "Source Type": 'actor',
                        "Target Name": most_common_uc,
                        "Target Type": 'usecase',
                        "Extension": "",
                    })

        return prim, sec, ucs, cleaned

    def addToDb(self):
        tree = ET.parse(self._file_name)
        root = tree.getroot()
        modeling_elems = [
            m for m in root.findall('Modeling')
            if m.attrib.get('type') in ('Avatar Analysis', 'Analysis')
        ]
        if not modeling_elems:
            st.error("No Use Case Diagram Found in File!")
            print("No Use Case Diagram Found in File!")
            return

        for modeling in modeling_elems:
            usecasediagrampanel = modeling.find('UseCaseDiagramPanel')
            if usecasediagrampanel is None:
                st.error(f"No Use Case Diagram present in {modeling}")
                print("No Use Case Diagram Found in File!")
                continue

            system_name = None
            name_of_ucd = usecasediagrampanel.attrib.get('name')

            stickman_actors = []
            box_actors = []
            use_cases = []
            system_boundary = []
            relationships = []

            print(f"The Name of the Use Case Diagram is : {name_of_ucd}")

            for component in usecasediagrampanel.findall('COMPONENT'):
                comp_type = component.attrib.get('type')
                value = component.find('infoparam').attrib.get('value')

                if comp_type == '700':
                    stickman_actors.append(value)
                elif comp_type == '701':
                    use_cases.append(value)
                elif comp_type == '702':
                    system_boundary.append(value)
                    system_name = value
                elif comp_type == '703':
                    box_actors.append(value)

            if len(system_boundary) != 1:
                st.error(f"It is advisable to have exactly 1 System per Use Case Diagram, skipping {name_of_ucd}")
                print(f"It is advisable to have exactly 1 System per Use Case Diagram, skipping {name_of_ucd}")
                continue

            # Pre-build ID → (name, type) map for O(1) connector lookup
            _id_map = {}
            for component in usecasediagrampanel.findall('COMPONENT'):
                comp_value = component.find('infoparam').attrib.get('value')
                comp_name = component.find('infoparam').attrib.get('name')
                for cp in component.findall('TGConnectingPoint'):
                    _id_map[cp.attrib.get('id')] = (comp_value, comp_name)

            # Normalize role types to match DB enum
            def _norm_role(t):
                t = (t or "").strip().lower()
                if "actor" in t:
                    return "actor"
                if "use" in t and "case" in t:
                    return "usecase"
                return t or ""

            for connector in usecasediagrampanel.findall('CONNECTOR'):
                extension = ''
                relation_code = connector.attrib.get('type')  # TTool reference number
                value = connector.find('infoparam').attrib.get('value')  # Type of connector

                relation_code_int = int(relation_code)
                val = (value or "").lower()

                if relation_code_int == 111 or "include" in val:
                    value = "include"
                elif relation_code_int == 113 or "extend" in val:
                    value = "extend"
                elif relation_code_int == 112 or "general" in val:
                    value = "generalization"
                else:
                    value = "association"

                source = connector.find('P1').attrib.get('id')
                target = connector.find('P2').attrib.get('id')

                source_name, source_type = _id_map.get(source, ('', ''))
                target_name, target_type = _id_map.get(target, ('', ''))



                # For extend relationships, prefer extension text from the use-case element
                if value == 'extend':
                    extension = extension or ''
                    # Prefer target use case; fallback to source if not found
                    for who in (target_name, source_name):
                        if not who:
                            continue
                        found = False
                        for component in usecasediagrampanel.findall('COMPONENT'):
                            comp_value = component.find('infoparam').attrib.get('value')
                            comp_name = component.find('infoparam').attrib.get('name')
                            if comp_name == 'Use case' and comp_value == who:
                                extension_elem = component.find('extraparam/info')
                                if extension_elem is not None:
                                    extension = (extension_elem.attrib.get('extension') or '').strip()
                                if extension:
                                    found = True
                                break
                        if found:
                            break

                relationships.append({
                    "Relation Code": relation_code,
                    "Value": value,
                    "Source Name": source_name,
                    "Source Type": _norm_role(source_type),
                    "Target Name": target_name,
                    "Target Type": _norm_role(target_type),
                    "Extension": extension
                })
                
            # --- Validate and repair UCD elements and relationships before going further ---
            stickman_actors, box_actors, use_cases, relationships = ParserOperations._validate_and_fix_ucd(
                stickman_actors, box_actors, use_cases, relationships
            )

            plantuml_code=ParserOperations.generate_plantuml(stickman_actors, box_actors, use_cases, system_name, relationships)

            with open(self._file_name, "r", encoding="utf-8") as f:
                xml_content = f.read()
            
            data = ParserOperations.dataFromGPT(
                        stickman_actors, box_actors, use_cases, system_name, relationships, plantuml_code
                    )
            if not isinstance(data, dict):
                st.error("Unexpected AI response format"); return

            valid, msg = ParserOperations.validate_ai_json(data, use_cases=use_cases)
            if not valid:
                st.error(f"AI JSON validation failed: {msg}")
                print("AI JSON validation failed:", msg)
                return

            else:

                system_desc = data["system_description"]

                domains = data["domains"]

                use_cases_desc = data["use_case_descriptions"]

                with connection.get_cursor() as cursor:

                    try:

                        # Create case
                        cursor.execute(
                            "INSERT INTO cases (title, description, title_embedding, description_embedding, domain_json) VALUES (%s, %s, %s, %s, %s)",
                            (
                                system_name,
                                system_desc,
                                embed_short(system_name),        # title → short model
                                embed_paragraph(system_desc),        # description → paragraph model
                                json.dumps(domains)
                            )
                        )

                        case_id = cursor.lastrowid

                        # Create diagram (1-to-1 with case)
                        cursor.execute("""
                            INSERT INTO diagrams (case_id, system_name, plantuml_code, xml_content)
                            VALUES (%s, %s, %s, %s)
                        """, (case_id, system_name, plantuml_code, xml_content))

                        # Insert actors
                        for actor in stickman_actors:
                            cursor.execute("""
                                INSERT INTO actors (case_id, actor_name, actor_type, name_embedding)
                                VALUES (%s, %s, %s, %s)
                                """, (case_id, actor, 'Primary', embed_short(actor)))  # <— short model

                        for actor in box_actors:
                            cursor.execute("""
                                INSERT INTO actors (case_id, actor_name, actor_type, actor_reference_number, name_embedding)
                                VALUES (%s, %s, %s, %s, %s)
                                """, (case_id, actor, 'Secondary', 703, embed_short(actor)))  # <— short model

                        # Insert use cases
                        for use_case in use_cases:
                            use_case_desc=use_cases_desc.get(use_case, f"Use case: {use_case}")
                            cursor.execute("""
                                INSERT INTO use_cases (case_id, name, description, name_embedding, description_embedding)
                                VALUES (%s, %s, %s, %s, %s)
                                """, (
                                case_id,
                                use_case,
                                use_case_desc,
                                embed_short(use_case),                 # <— short model
                                embed_paragraph(use_case_desc)         # <— paragraph model (it’s a sentence/paragraph)
                                ))

                        # Insert relationships
                        for relation in relationships:
                            source_name=relation["Source Name"]
                            target_name=relation["Target Name"]
                            source_type=relation["Source Type"]
                            target_type=relation["Target Type"]
                            value=relation["Value"]
                            relation_code=relation["Relation Code"]
                            extension=relation.get("Extension","")

                            cursor.execute("""
                                INSERT INTO relationships (
                                    relationship_type, relation_code,
                                    source_name, target_name, source_type, target_type,
                                    extension, case_id
                                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            """, (
                                value, relation_code,
                                source_name, target_name,
                                source_type, target_type,
                                extension, case_id
                            ))

                        # Insert domains
                        for domain in domains:
                            cursor.execute("""
                                INSERT INTO case_domains (case_id, domain_name, domain_embedding)
                                VALUES (%s, %s, %s)
                                """, (case_id, domain, embed_short(domain)))           # <— short model (labels)
                        
                        # Generate and store synonyms for system, actors, and use cases
                        try:
                            canonical_actors = []
                            canonical_actors.extend(stickman_actors)
                            canonical_actors.extend(box_actors)
                            # de-duplicate while preserving order
                            seen_a = set()
                            canon_actors = []
                            for a in canonical_actors:
                                key = (a or "").strip().lower()
                                if key and key not in seen_a:
                                    seen_a.add(key)
                                    canon_actors.append(a)

                            syn = ParserOperations.synonymsFromGPT(system_name, canon_actors, use_cases)

                            # System synonyms
                            for s in (syn.get("system_name_synonyms") or []):
                                cursor.execute(
                                    """
                                    INSERT IGNORE INTO system_synonyms (case_id, system_name, synonym)
                                    VALUES (%s, %s, %s)
                                    """,
                                    (case_id, system_name, s)
                                )

                            # Actor synonyms
                            act_map = syn.get("actor_synonyms") or {}
                            for canon_name, variants in act_map.items():
                                # choose original-casing base when available
                                base = None
                                for a in canon_actors:
                                    if ParserOperations._normalize_actor_like(a).lower() == ParserOperations._normalize_actor_like(canon_name).lower():
                                        base = a
                                        break
                                base = base or canon_name
                                for v in (variants or []):
                                    cursor.execute(
                                        """
                                        INSERT IGNORE INTO actor_synonyms (case_id, actor_name, synonym)
                                        VALUES (%s, %s, %s)
                                        """,
                                        (case_id, base, v)
                                    )

                            # Use case synonyms
                            uc_map = syn.get("use_case_synonyms") or {}
                            for canon_uc, variants in uc_map.items():
                                base_uc = None
                                for u in use_cases:
                                    if ParserOperations._normalize_use_case(u).lower() == ParserOperations._normalize_use_case(canon_uc).lower():
                                        base_uc = u
                                        break
                                base_uc = base_uc or canon_uc
                                for v in (variants or []):
                                    cursor.execute(
                                        """
                                        INSERT IGNORE INTO use_case_synonyms (case_id, use_case_name, synonym)
                                        VALUES (%s, %s, %s)
                                        """,
                                        (case_id, base_uc, v)
                                    )
                        except Exception as e:
                            # Log but do not fail ingestion on synonym errors
                            print(f"Synonym generation failed: {e}")

                        connection.commit()

                    except Exception as e:
                    
                        connection.rollback()
                        st.error(f"DB Insert Error: {e}")
                        print(f"DB Insert Error: {e}")
                        import traceback
                        traceback.print_exc()

        st.success("Use Case Diagram Data uploaded and processed successfully.")
        print('Use Case Diagram Data uploaded and processed successfully.')


"""
MyCBR/mycbr_rest.py
====================
Client for the myCBR REST API (myCBR Workbench launched in server mode).

myCBR REST API Documentation:
  POST /API/retrieval/concepts/{concept}/cases/{casebase}
  Body: JSON object where each key is an attribute name.
  Returns: list of {caseID, similarity} sorted descending.

By default myCBR REST server runs on http://localhost:8080

Usage:
    from MyCBR.mycbr_rest import MyCBRRestClient
    client = MyCBRRestClient()
    results = client.retrieve(query_dict, limit=5)
"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

# ── myCBR project constants (generated project name) ──────────────────────────
_CONCEPT              = "UCD_CBR_Cycle_ProjectCase"
_CASEBASE             = "UCD_CBR_Cycle_ProjectCB"
_BASE_URL             = "http://localhost:8080"
_AMALGAMATION_FUNC    = "balanced_similarity"  # default; auto-discovered at runtime

# ── myCBR attribute names (as defined in the .myCBR model) ────────────────────
_ATTR_SYSTEM_NAME   = "SystemName"
_ATTR_PRIMARY_DOMAIN = "PrimaryDomain"
_ATTR_ACTOR_NAMES   = "ActorNames"
_ATTR_UC_NAMES      = "UseCaseNames"
_ATTR_NUM_ACTORS    = "PrimaryActorCount"
_ATTR_NUM_UCS       = "UseCaseCount"
_ATTR_NUM_RELS      = "RelationshipCount"
_ATTR_HAS_INCLUDE   = "HasInclude"
_ATTR_HAS_EXTEND    = "HasExtend"
_ATTR_HAS_GENERALIZATION = "HasGeneralization"


def _pipe_join(items: List[str]) -> str:
    """Join a list of strings with ' | ' as myCBR symbol-list separator."""
    return " | ".join(str(i).strip() for i in items if i)


def _yn(flag: Any) -> str:
    """Convert a boolean-ish value to 'Yes' / 'No' for Symbol attributes."""
    if isinstance(flag, bool):
        return "Yes" if flag else "No"
    if isinstance(flag, str):
        return "Yes" if flag.lower() in {"yes", "true", "1"} else "No"
    return "Yes" if flag else "No"


class MyCBRRestClient:
    """
    Thin REST client that translates a structured CBR query dict into a
    myCBR REST API request and returns ranked case matches.

    Parameters
    ----------
    base_url  : Base URL of the myCBR REST server (default: http://localhost:8080)
    concept   : myCBR concept name
    casebase  : myCBR casebase name
    timeout   : HTTP request timeout in seconds
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        concept: str = _CONCEPT,
        casebase: str = _CASEBASE,
        amalgamation_function: str = _AMALGAMATION_FUNC,
        timeout: int = 10,
    ):
        self.base_url             = base_url.rstrip("/")
        self.concept              = concept
        self.casebase             = casebase
        self.amalgamation_function = amalgamation_function
        self.timeout              = timeout

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Return True if the myCBR REST server is reachable."""
        try:
            r = requests.get(f"{self.base_url}/concepts", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def get_amalgamation_functions(self) -> List[str]:
        """Return list of amalgamation function names available for this concept."""
        try:
            r = requests.get(
                f"{self.base_url}/concepts/{self.concept}/amalgamationFunctions",
                timeout=5,
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return [self.amalgamation_function]

    def retrieve(
        self,
        query: Dict[str, Any],
        limit: int = 5,
        threshold: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Send a retrieval request to myCBR and return ranked matches.

        Parameters
        ----------
        query     : CBR query dict with keys:
                      system_name, domains, actors, use_cases, relationships
        limit     : Max number of results to return
        threshold : Minimum similarity score (0.0 – 1.0)

        Returns
        -------
        List of dicts with keys:
          case_id, title, relevance, source="mycbr"
        """
        payload = self._build_payload(query)
        url = (
            f"{self.base_url}/concepts/{self.concept}"
            f"/casebases/{self.casebase}"
            f"/amalgamationFunctions/{self.amalgamation_function}"
            f"/retrievalByMultipleAttributes"
        )
        params = {
            "k": limit,
        }

        try:
            resp = requests.post(
                url,
                json=payload,
                params=params,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            raw = resp.json()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Cannot reach myCBR REST server at {self.base_url}. "
                "Make sure myCBR Workbench is running in REST server mode."
            )
        except Exception as exc:
            log.error("myCBR REST error: %s", exc)
            raise

        matches = self._parse_response(raw, threshold=threshold, limit=limit)
        return matches

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_payload(self, query: Dict[str, Any]) -> Dict[str, str]:
        """
        Convert a CBR query dict into the flat key-value dict that the
        myCBR REST API expects as the POST body.
        """
        system_name  = str(query.get("system_name") or "")
        domains      = list(query.get("domains") or [])
        actors       = list(query.get("actors")  or [])
        use_cases    = list(query.get("use_cases") or [])
        rels         = list(query.get("relationships") or [])

        # --- Derive relationship flag fields ---
        rel_types: List[str] = []
        for r in rels:
            if isinstance(r, dict):
                rel_types.append((r.get("relationship_type") or "").lower())
            else:
                rel_types.append(str(r).lower())

        has_include        = "include"        in rel_types
        has_extend         = "extend"         in rel_types
        has_generalization = "generalization" in rel_types

        payload: Dict[str, str] = {}
        
        if system_name:
            payload[_ATTR_SYSTEM_NAME] = system_name
        if actors:
            payload[_ATTR_ACTOR_NAMES] = _pipe_join(actors)
        if use_cases:
            payload[_ATTR_UC_NAMES] = _pipe_join(use_cases)
            
        payload[_ATTR_NUM_ACTORS]         = str(len(actors))
        payload[_ATTR_NUM_UCS]            = str(len(use_cases))
        payload[_ATTR_NUM_RELS]           = str(len(rels))
        payload[_ATTR_HAS_INCLUDE]        = _yn(has_include)
        payload[_ATTR_HAS_EXTEND]         = _yn(has_extend)
        payload[_ATTR_HAS_GENERALIZATION] = _yn(has_generalization)

        # PrimaryDomain must be one of the known symbol values; default to first match.
        if domains:
            payload[_ATTR_PRIMARY_DOMAIN] = str(domains[0])

        return payload

    def _parse_response(
        self,
        raw: Any,
        threshold: float,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Parse the myCBR REST response into our standard match list format.

        myCBR response format:
          { "caseID-1": 0.87, "caseID-2": 0.62, ... }
        or as an array of objects:
          [ {"caseID": "UCD_0001", "similarity": 0.87}, ... ]
        """
        results: List[Dict[str, Any]] = []

        if isinstance(raw, dict):
            # Format: { "caseID": score, ... }
            for case_id, score in raw.items():
                try:
                    sim = float(score)
                except (TypeError, ValueError):
                    sim = 0.0
                if sim >= threshold:
                    results.append({
                        "case_id":   _short_case_id(case_id),
                        "case_key":  f"mycbr-{case_id}",
                        "title":     _resolve_case_title(case_id),
                        "relevance": sim,
                        "source":    "mycbr",
                    })

        elif isinstance(raw, list):
            # Format: [ {"caseID": ..., "similarity": ...}, ... ]
            for item in raw:
                if not isinstance(item, dict):
                    continue
                case_id = str(item.get("caseID") or item.get("id") or "")
                try:
                    sim = float(item.get("similarity") or item.get("sim") or 0.0)
                except (TypeError, ValueError):
                    sim = 0.0
                if sim >= threshold:
                    results.append({
                        "case_id":   _short_case_id(case_id),
                        "case_key":  f"mycbr-{case_id}",
                        "title":     item.get("title") or _resolve_case_title(case_id),
                        "relevance": sim,
                        "source":    "mycbr",
                    })

        results.sort(key=lambda x: float(x["relevance"]), reverse=True)
        return results[:limit]


# ── Module-level convenience functions ────────────────────────────────────────

# CSV is at  <this_package>/output/full_export/casebase_mysql_full.csv
_CSV_PATH = Path(__file__).parent / "output" / "full_export" / "casebase_mysql_full.csv"

_case_name_map: Optional[Dict[str, str]] = None


def _load_case_name_map() -> Dict[str, str]:
    """Load CaseLabel → SystemName from the CSV, cached at module level."""
    global _case_name_map
    if _case_name_map is not None:
        return _case_name_map
    mapping: Dict[str, str] = {}
    try:
        with open(_CSV_PATH, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            for row in reader:
                label = (row.get("CaseLabel") or "").strip()   # e.g. "UCD_0049"
                name  = (row.get("SystemName") or "").strip()  # e.g. "Missile System"
                if label and name:
                    mapping[label.upper()] = name
    except Exception as exc:
        log.warning("Could not load case name map from CSV: %s", exc)
    _case_name_map = mapping
    return mapping


def _short_case_id(case_id: str) -> str:
    """Return a concise label like 'UCD_0049' from a raw myCBR case ID."""
    m = re.search(r"#?(\d+)\s*$", case_id)
    if m:
        return f"UCD_{int(m.group(1)):04d}"
    # If already a plain label (e.g. "UCD_0049"), return as-is
    return case_id


def _resolve_case_title(case_id: str) -> str:
    """
    Resolve a myCBR case ID to a human-readable system name.

    myCBR typically returns IDs in the form:
      "UCD_CBR_Cycle_ProjectCase #49"  (concept-name + row number)
    or plain:
      "UCD_0049"                        (CSV CaseLabel)

    Strategy:
      1. Try a direct lookup of the raw case_id against the CSV CaseLabel.
      2. If the ID ends with a number N, try "UCD_{N:04d}" as a CaseLabel.
      3. Fall back to returning the raw case_id.
    """
    mapping = _load_case_name_map()

    # 1. Direct match (handles plain "UCD_0049" variant)
    if case_id.upper() in mapping:
        return mapping[case_id.upper()]

    # 2. Extract trailing number from patterns like "UCD_CBR_Cycle_ProjectCase #49"
    m = re.search(r"#?(\d+)\s*$", case_id)
    if m:
        n = int(m.group(1))
        label = f"UCD_{n:04d}"
        if label in mapping:
            return mapping[label]

    # 3. Fallback
    return case_id


_default_client: Optional[MyCBRRestClient] = None


def get_default_client() -> MyCBRRestClient:
    """Return a module-level cached client instance."""
    global _default_client
    if _default_client is None:
        _default_client = MyCBRRestClient()
    return _default_client


def mycbr_retrieve(
    query: Dict[str, Any],
    limit: int = 5,
    threshold: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper — identical signature to `cbr_search.find_similar_cases`.
    Raises ConnectionError if myCBR REST server is not reachable.
    """
    return get_default_client().retrieve(query, limit=limit, threshold=threshold)


def mycbr_is_alive(base_url: str = _BASE_URL) -> bool:
    """Quick health check — returns True if myCBR server is reachable."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/concepts", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

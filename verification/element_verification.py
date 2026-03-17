"""
Element-level verification rules for UCD components.

Renamed from ``element_validation`` to ``element_verification``.
All static methods are preserved: actor/use-case naming checks, arrangement
geometry, connectivity via BFS, relationship semantics, and issue collection.
"""

import re
from difflib import get_close_matches

from verification.text_tools import TextVerificationTools, _is_spelling_valid
from verification.activity_panel import build_activity_panel, append_activity_panel


class element_verification:

    # ------------------------------------------------------------------ #
    #  Shared text helpers (used by validators AND collectors)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean(comment: str) -> str:
        """Strip rule prefixes and collapse all whitespace/newlines to single space."""
        for prefix in ("[Rule 0] ", "[Rule 1] ", "[Rule 2] ", "[Rule 3] ",
                       "[Rule 4] ", "[Rule 5] ", "[Rule 6] ", "[Rule 7] "):
            comment = comment.replace(prefix, "")
        return " ".join(comment.split())

    @staticmethod
    def _trunc(text: str, maxlen: int = 100) -> str:
        """Truncate comment to maxlen; keeps full step_text ≤ 179 chars (TTool constraint)."""
        return text if len(text) <= maxlen else text[:maxlen - 3] + "..."

    @staticmethod
    def _issue_dedupe_key(tag: str, label: str, comment: str) -> tuple:
        """Canonical key for exported issues so symmetric similarity warnings appear once."""
        cleaned = element_verification._clean(comment)

        pair_patterns = [
            r"^(Actors?) '([^']+)' and '([^']+)' (appear semantically similar|may be semantically related) ",
            r"^(Use cases?) '([^']+)' and '([^']+)' (appear semantically similar|may be semantically related) ",
        ]
        for pattern in pair_patterns:
            match = re.match(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                subject = match.group(1).lower()
                left = match.group(2).strip().lower()
                right = match.group(3).strip().lower()
                relation = match.group(4).lower()
                pair = tuple(sorted((left, right)))
                return ("pairwise_similarity", tag, subject, relation, pair)

        return (tag, label, cleaned)

    @staticmethod
    def _safe_append(meta: dict, msg: str) -> None:
        """Append msg to Comments only if not already present."""
        if msg and msg not in meta.get("Comments", []):
            meta.setdefault("Comments", []).append(msg)

    @staticmethod
    def _set_action(meta, level, msg):
        """Update Comments/Action with severity level (0 ok, 1 warning, 2 attention)."""
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        if msg:
            element_verification._safe_append(meta, msg)
        prev_level = {v: k for k, v in action_map.items()}.get(meta.get("Action", "Well Written"), 0)
        meta["Action"] = action_map[max(prev_level, level)]

    # Markers that identify comments owned by each structural validator.
    # These are the ONLY comments cleared on re-run; all others are preserved.
    _ARRANGEMENT_MARKERS = [
        "inside the system boundary but should be outside",
        "outside the system boundary but should be inside",
        "intersecting with the system boundary",
    ]
    _ISOLATION_MARKER = "isolated"
    _STRUCTURAL_RELATION_MARKERS = [
        "must connect use case to use case",
        "cannot link",
        "Duplicate relationship",
        "Generalization should stay within",
        "Generalization connects unknown",
    ]

    # ------------------------------------------------------------------ #
    #  Batch validators (called once in processData — they DO full reset)
    # ------------------------------------------------------------------ #

    @staticmethod
    def validateActors(actors_arr):
        # Full reset — called only once during processData
        for _, meta in actors_arr:
            meta["Comments"].clear()
            meta["Action"] = "Well Written"

        for i in range(len(actors_arr)):
            name_i, meta_i = actors_arr[i]
            for j in range(i + 1, len(actors_arr)):
                name_j, meta_j = actors_arr[j]
                if name_i == name_j:
                    msg = (f"Two {meta_i['Element Type']}s have the same name "
                           f"('{name_i}'). Please DELETE or MODIFY one of them.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        meta["Action"] = "Attention Required!"
                    continue

                score = TextVerificationTools.phraseSimilarity(name_i, name_j)
                if score >= 0.90:
                    msg = (f"Actors '{name_i}' and '{name_j}' appear semantically "
                           f"similar (score: {score:.0%}). Consider renaming or "
                           f"merging one of them.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        meta["Action"] = "Attention Required!"
                elif score > 0.75:
                    msg = (f"Actors '{name_i}' and '{name_j}' may be "
                           f"semantically related (score: {score:.0%}). "
                           f"Review if they should be merged or renamed.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        if meta.get("Action") != "Attention Required!":
                            meta["Action"] = "Warning!"

        for name, meta in actors_arr:
            nm = name.strip()
            tokens = nm.split()
            if len(nm) < 3:
                element_verification._set_action(meta, 1, f"Actor '{nm}' looks too short to be meaningful.")
            if len(tokens) > 5:
                element_verification._set_action(meta, 1, f"Actor '{nm}' is very long; keep role names concise.")

    @staticmethod
    def validateUsecases(usecases_arr):
        # Full reset — called only once during processData
        for _, meta in usecases_arr:
            meta["Comments"].clear()
            meta["Action"] = "Well Written"

        for i in range(len(usecases_arr)):
            name_i, meta_i = usecases_arr[i]
            for j in range(i + 1, len(usecases_arr)):
                name_j, meta_j = usecases_arr[j]
                if name_i == name_j:
                    msg = (f"Two use cases have the same name ('{name_i}'). "
                           "Please rename or delete one of them.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        meta["Action"] = "Attention Required!"
                    continue

                score = TextVerificationTools.phraseSimilarity(name_i, name_j)
                if score >= 0.90:
                    msg = (f"Use cases '{name_i}' and '{name_j}' appear "
                           f"semantically similar (score: {score:.0%}). "
                           f"Consider renaming or merging one of them.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        meta["Action"] = "Attention Required!"
                elif score > 0.75:
                    msg = (f"Use cases '{name_i}' and '{name_j}' may be "
                           f"semantically related (score: {score:.0%}). "
                           f"Review if they should be merged or renamed.")
                    for meta in (meta_i, meta_j):
                        element_verification._safe_append(meta, msg)
                        if meta.get("Action") != "Attention Required!":
                            meta["Action"] = "Warning!"

        for name, meta in usecases_arr:
            nm = name.strip()
            tokens = nm.split()
            if len(tokens) == 0:
                element_verification._set_action(meta, 2, "Use case name is empty.")
                continue
            if len(tokens) > 8:
                element_verification._set_action(meta, 1, f"Use case '{nm}' is long; keep it concise.")

    # ------------------------------------------------------------------ #
    #  Structural validators — selective-clear (safe to call multiple times)
    # ------------------------------------------------------------------ #

    @staticmethod
    def validateArrangement(stickman_actors_arr, box_actors_arr, use_cases_arr, system_boundary_arr):
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}
        temp = system_boundary_arr[0][1]
        sys_bound = element_verification.getBoundaryBox(
            float(temp["X"]), float(temp["Y"]), float(temp["W"]), float(temp["H"]))

        sev_map = {"Well Written": 0, "Warning!": 1, "Attention Required!": 2}

        def _selective_clear(meta):
            # Remove only arrangement-specific comments
            meta["Comments"] = [
                c for c in meta.get("Comments", [])
                if not any(m in c for m in element_verification._ARRANGEMENT_MARKERS)
            ]
            # Recompute action from ALL remaining comments (NLP + other structural)
            # Never let this downgrade an action set by NLP validators.
            if meta.get("Comments"):
                sev = max(
                    element_verification._per_comment_sev(c, 1)
                    for c in meta["Comments"]
                )
            else:
                sev = 0
            meta["Action"] = action_map[sev]

        for actor_list in [stickman_actors_arr, box_actors_arr]:
            for name, meta in actor_list:
                _selective_clear(meta)
                elem_bound = element_verification.getBoundaryBox(
                    float(meta["X"]), float(meta["Y"]), float(meta["W"]), float(meta["H"]))
                if not element_verification.isOutside(sys_bound, elem_bound):
                    if element_verification.isInside(sys_bound, elem_bound):
                        msg = (f"'{meta['Element Type']}' : '{name}' is present inside the system boundary "
                               f"but should be outside the system boundary.")
                    else:
                        msg = (f"'{meta['Element Type']}' : '{name}' is intersecting with the system boundary "
                               f"but should be completely outside the system boundary.")
                    element_verification._set_action(meta, 2, msg)

        for name, meta in use_cases_arr:
            _selective_clear(meta)
            elem_bound = element_verification.getBoundaryBox(
                float(meta["X"]), float(meta["Y"]), float(meta["W"]), float(meta["H"]))
            if not element_verification.isInside(sys_bound, elem_bound):
                if element_verification.isOutside(sys_bound, elem_bound):
                    msg = (f"'{meta['Element Type']}' : '{name}' is present outside the system boundary "
                           f"but should be inside the system boundary.")
                else:
                    msg = (f"'{meta['Element Type']}' : '{name}' is intersecting with the system boundary "
                           f"but should be completely inside the system boundary.")
                element_verification._set_action(meta, 2, msg)

    @staticmethod
    def getBoundaryBox(cx, cy, width, height):
        return {'left': cx, 'right': cx + width, 'top': cy, 'bottom': cy + height}

    @staticmethod
    def isInside(sys_boundary, element_boundary):
        return (
            element_boundary['left']   >= sys_boundary['left']  and
            element_boundary['right']  <= sys_boundary['right'] and
            element_boundary['top']    >= sys_boundary['top']   and
            element_boundary['bottom'] <= sys_boundary['bottom']
        )

    @staticmethod
    def isOutside(sys_boundary, element_boundary):
        return (
            element_boundary['right']  < sys_boundary['left']  or
            element_boundary['left']   > sys_boundary['right'] or
            element_boundary['bottom'] < sys_boundary['top']   or
            element_boundary['top']    > sys_boundary['bottom']
        )

    @staticmethod
    def validateActor(actors_name, actors_type):
        comments = []
        action_level = 0
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}

        if actors_name != actors_name.strip():
            comments.append(f"Name has leading or trailing whitespace ('{actors_name}'). Remove the extra spaces.")
            action_level = max(action_level, 1)
            actors_name = actors_name.strip()

        chars = re.findall(r"[^A-Za-z -]", actors_name)
        if chars:
            comments.append(f"Difficult to read and comprehend because it contains characters "
                            f"{', '.join(sorted(set(chars)))} that are neither alphabets, hyphens, nor whitespaces.")
            return comments, action_map[2]

        display_name = re.sub(r"\s*-\s*", " ", actors_name)
        if not (display_name == TextVerificationTools.toTitleCase(display_name) or
                display_name == TextVerificationTools.toTitleCaseSmart(display_name) or
                display_name == TextVerificationTools.toPascalCase(display_name)):
            comments.append("Difficult to read and comprehend because it lacks 'Title Casing' or 'PascalCasing'.")
            action_level = max(action_level, 1)

        processed_actors_name = actors_name
        cond, comment, warns = TextVerificationTools.isMeaningfulCommonSingularNounPhrase(processed_actors_name)

        if warns:
            comments.extend(warns)
            action_level = max(action_level, 1)

        if cond:
            check, stmt = TextVerificationTools.isPrimaryActor(processed_actors_name)
            if actors_type == "Primary Actor":
                if not check:
                    action_level = max(action_level, 1)
                    if "artifact" in stmt:
                        comments.append("Marked as a Primary Actor, but it appears more appropriate as a Secondary Actor. "
                                        "Consider using the representation with Primary Actor(Box Figure with <<Stereotype>>).")
                    elif "other" in stmt:
                        comments.append("Cannot determine whether this is a person or an artefact – "
                                        "please clarify the name (e.g. end with 'System', 'Controller', etc.).")
                    else:
                        comments.append(f"'{actors_type}' : '{actors_name}' {stmt}")
                        action_level = max(action_level, 2)
            else:
                if check:
                    comments.append("Marked as a Secondary Actor, but it appears more appropriate as a Primary Actor. "
                                    "Consider using the representation with Primary Actor(Stickman Figure).")
                    action_level = max(action_level, 1)
        else:
            # isMeaningfulCommonSingularNounPhrase failed — it returns a specific
            # reason (e.g. "found verb 'Repair'", "found plural", etc.).
            # Use that message directly.  Only fall back to isPrimaryActor if the
            # comment is empty or purely generic (no diagnostic info).
            action_level = max(action_level, 2)
            specific_comment = comment if isinstance(comment, str) and comment.strip() else ""
            if specific_comment and "found verb" in specific_comment:
                # Clearly verbal — give the targeted verb error
                comments.append(f"Invalid actor name because it {specific_comment}.")
            elif specific_comment:
                comments.append(f"Invalid actor name because {specific_comment}.")
                if isinstance(comment, list):
                    comments.extend(comment)
            else:
                # No specific comment — try isPrimaryActor for a hint
                check, stmt = TextVerificationTools.isPrimaryActor(processed_actors_name)
                if "other" in stmt:
                    comments.append(
                        "Cannot determine whether this is a person or an artefact – "
                        "please clarify the name (e.g. end with 'System', 'Controller', etc.)."
                    )
                else:
                    comments.append(
                        "Invalid actor name because it is expected to have common singular nouns or "
                        "combinations of adjectives and common singular nouns."
                    )

        return comments, action_map[action_level]

    @staticmethod
    def validateUsecase(uc_text, element):
        comments = []
        action_level = 0
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}

        if uc_text != uc_text.strip():
            comments.append(f"Name has leading or trailing whitespace ('{uc_text}'). Remove the extra spaces.")
            action_level = max(action_level, 1)
            uc_text = uc_text.strip()

        chars = re.findall(r"[^A-Za-z -]", uc_text)
        if chars:
            comments.append(f"Difficult to read and comprehend because it contains characters "
                            f"{', '.join(sorted(set(chars)))} that are neither alphabets, hyphens, nor whitespaces.")
            return comments, action_map[2]

        display_name = re.sub(r"\s*-\s*", " ", uc_text)
        if not (display_name == TextVerificationTools.toTitleCase(display_name) or
                display_name == TextVerificationTools.toTitleCaseSmart(display_name) or
                display_name == TextVerificationTools.toPascalCase(display_name)):
            comments.append("Difficult to read and comprehend because it lacks 'Title Casing' or 'PascalCasing'.")
            action_level = max(action_level, 1)

        processed_uc_name = uc_text
        cond, comment, warns = TextVerificationTools.isMeaningfulBaseVerbPhrase(processed_uc_name, element)

        if warns:
            comments.extend(warns)
            action_level = max(action_level, 1)

        if not cond:
            action_level = max(action_level, 2)
            if isinstance(comment, str):
                comments.append(f"Invalid use case name because {comment}")
            else:
                comments.append("Invalid use case name because it is expected to have combinations of base form verb, "
                                 "preposition (optional) adjective (optional) and common singular noun(s).")
                comments.extend(comment)

        return comments, action_map[action_level]

    @staticmethod
    def validateSystem(systems_name):
        comments = []
        action_level = 0
        action_map = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}

        if systems_name != systems_name.strip():
            comments.append(f"Name has leading or trailing whitespace ('{systems_name}'). Remove the extra spaces.")
            action_level = max(action_level, 1)
            systems_name = systems_name.strip()

        bad_chars = re.findall(r"[^A-Za-z -]", systems_name)
        if bad_chars:
            comments.append("Contains illegal characters: " + ", ".join(sorted(set(bad_chars))))
            return comments, action_map[2]

        display_name = re.sub(r"\s*-\s*", " ", systems_name)
        if not (display_name == TextVerificationTools.toTitleCase(display_name) or
                display_name == TextVerificationTools.toPascalCase(display_name) or
                display_name == TextVerificationTools.toTitleCaseSmart(display_name)):
            comments.append("Difficult to read and comprehend because it lacks 'Title Casing' or 'PascalCasing'.")
            action_level = max(action_level, 1)

        for token in re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)*", systems_name):
            compact = token.replace("-", "")
            if len(compact) <= 2 or re.fullmatch(r"[A-Z]{2,}", compact):
                continue
            token_lc = token.lower()
            if not _is_spelling_valid(token_lc, TextVerificationTools.WORD_LIST):
                suggestions = get_close_matches(
                    token_lc.replace("-", ""),
                    TextVerificationTools.WORD_LIST,
                    n=1,
                    cutoff=0.8,
                )
                if suggestions:
                    comments.append(
                        f"Possible spelling error in system name: '{token}' — did you mean '{suggestions[0].title()}'?"
                    )
                else:
                    comments.append(
                        f"Possible spelling error in system name: '{token}' is not a recognised English word."
                    )
                return comments, action_map[2]

        processed = systems_name
        ok, reason, warns = TextVerificationTools.isMeaningfulCommonSingularNounPhrase(processed)

        if warns:
            comments.extend(warns)
            action_level = max(action_level, 1)

        if not ok:
            if isinstance(reason, list):
                comments.extend(reason)
            else:
                comments.append(reason)
            return comments, action_map[2]

        orig_head = systems_name.split()[-1]
        if re.fullmatch(r'[A-Z]{2,}', orig_head):
            return comments, action_map[action_level]

        SYSTEM_HEADS = {
            "system", "subsystem", "controller", "server", "device", "machine",
            "station", "module", "engine", "gateway", "platform", "unit",
            "equipment", "terminal", "robot", "appliance", "data",
            # common abbreviations — "app" = application, "mgr" = manager, etc.
            "app", "application",
        }
        head = processed.split()[-1].lower()
        if head not in SYSTEM_HEADS:
            action_level = max(action_level, 1)
            comments.append(f"Ends with \u201c{head.title()}\u201d. "
                            "A system boundary should end with a concrete artefact noun "
                            "(e.g. *System*, *Module*, *Device* \u2026).")

        is_person, _ = TextVerificationTools.isPrimaryActor(processed)
        if is_person:
            action_level = 2
            comments.append("Looks like a person/role \u2013 a system boundary must be an artefact.")

        return comments, action_map[action_level]

    @staticmethod
    def validateActorConnectivity(actors, use_cases, connectors):
        # Selective clear — only remove isolation messages, preserve everything else
        for _, meta in actors:
            meta["Comments"] = [
                c for c in meta.get("Comments", [])
                if element_verification._ISOLATION_MARKER not in c.lower()
            ]

        graph = {}
        for conn_id, conn in connectors:
            src = conn["Source Name"]
            tgt = conn["Target Name"]
            graph.setdefault(src, set()).add(tgt)
            graph.setdefault(tgt, set()).add(src)

        use_case_names = {uc[0] for uc in use_cases}

        def bfsFromActor(actor_name):
            visited, queue = set(), [actor_name]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                if node in use_case_names:
                    return True
                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)
            return False

        for i, (actor_name, meta) in enumerate(actors):
            if not bfsFromActor(actor_name):
                msg = (f"Actor is isolated - not connected to any use case directly or through generalization. "
                       f"Please either remove '{actor_name}' or establish valid associations with use cases "
                       f"or other related elements.")
                element_verification._safe_append(actors[i][1], msg)
                actors[i][1]["Action"] = "Attention Required!"

    @staticmethod
    def validateUsecaseConnectivity(use_cases, actors, connectors):
        # Selective clear — only remove isolation messages, preserve everything else
        for _, meta in use_cases:
            meta["Comments"] = [
                c for c in meta.get("Comments", [])
                if element_verification._ISOLATION_MARKER not in c.lower()
            ]

        graph = {}
        for conn_id, conn in connectors:
            src = conn["Source Name"]
            tgt = conn["Target Name"]
            graph.setdefault(src, set()).add(tgt)
            graph.setdefault(tgt, set()).add(src)

        actor_names = {actor[0] for actor in actors}

        def isConnectedToActor(uc_name):
            visited, queue = set(), [uc_name]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                if node in actor_names:
                    return True
                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        queue.append(neighbor)
            return False

        for i, (uc_name, meta) in enumerate(use_cases):
            if not isConnectedToActor(uc_name):
                msg = (f"Use case is isolated \u2014 it is not connected to any actor directly or via generalization. "
                       f"Please either remove '{uc_name}' or establish valid associations with actors "
                       f"or other related elements.")
                element_verification._safe_append(use_cases[i][1], msg)
                use_cases[i][1]["Action"] = "Attention Required!"

    @staticmethod
    def validateRelations(connectors, actors, use_cases):
        """
        Structural relation checks.
        Selective-clear: only removes its own structural markers so that
        questionnaire answers written by step5_relationships.py are preserved.
        """
        actor_set  = {a[0] for a in actors}
        uc_set     = {u[0] for u in use_cases}
        seen_pairs = set()

        for _, meta in connectors:
            # Remove only structural markers — leave questionnaire answers intact
            meta["Comments"] = [
                c for c in meta.get("Comments", [])
                if not any(m in c for m in element_verification._STRUCTURAL_RELATION_MARKERS)
            ]
            # Recompute Action from remaining comments.
            # Use _per_comment_sev with fallback=2 so any unclassified questionnaire
            # comment (e.g. "Replace X with Y") is treated as an error, not silently
            # downgraded to Well Written.
            if meta.get("Comments"):
                remaining_sev = max(
                    element_verification._per_comment_sev(c, 2)
                    for c in meta["Comments"]
                )
            else:
                remaining_sev = 0
            meta["Action"] = {0: "Well Written", 1: "Warning!", 2: "Attention Required!"}[remaining_sev]

        for conn_id, meta in connectors:
            rt    = (meta.get("Relation Value") or "").lower()
            s     = meta.get("Source Name") or ""
            t     = meta.get("Target Name") or ""
            stype = (meta.get("Source Type") or "").lower()
            ttype = (meta.get("Target Type") or "").lower()

            pair_key = (s, t, rt)
            if pair_key in seen_pairs:
                element_verification._set_action(meta, 1, f"Duplicate relationship '{s}' -> '{t}' ({rt}).")
            seen_pairs.add(pair_key)

            if s == t and rt in {"include", "extend", "generalization"}:
                element_verification._set_action(meta, 2, f"Relationship '{rt}' cannot link '{s}' to itself.")

            stype_norm = stype.replace(" ", "")
            ttype_norm = ttype.replace(" ", "")

            if rt in {"include", "extend"}:
                if stype_norm != "usecase" or ttype_norm != "usecase" or s not in uc_set or t not in uc_set:
                    element_verification._set_action(
                        meta, 2,
                        f"{rt.title()} must connect use case to use case; "
                        f"found '{s}' ({stype}) -> '{t}' ({ttype}).")

            if rt == "generalization":
                if stype_norm != ttype_norm:
                    element_verification._set_action(
                        meta, 2,
                        f"Generalization should stay within actors or within use cases; "
                        f"'{s}' ({stype}) -> '{t}' ({ttype}).")
                if stype_norm == "actor" and (s not in actor_set or t not in actor_set):
                    element_verification._set_action(meta, 2, "Generalization connects unknown actors.")
                if stype_norm == "usecase" and (s not in uc_set or t not in uc_set):
                    element_verification._set_action(meta, 2, "Generalization connects unknown use cases.")

    # ------------------------------------------------------------------ #
    #  Per-comment severity classifier
    # ------------------------------------------------------------------ #

    @staticmethod
    def _per_comment_sev(comment: str, fallback_sev: int) -> int:
        """Infer severity of a single comment string."""
        c_low = comment.lower()
        if any(x in c_low for x in [
            "must", "cannot", "duplicate", "isolated", "invalid", "illegal",
            "inside", "outside", "intersecting", "empty", "same name",
            "reversed", "replace", "independent", "remove the", "attention",
            "none of the above", "should be reversed"
        ]):
            return 2
        if any(x in c_low for x in [
            "consider", "may be", "short", "long", "lacks", "appropriate",
            "warning", "extension point", "don't forget"
        ]):
            return 1
        return fallback_sev

    # ------------------------------------------------------------------ #
    #  Issue collection
    # ------------------------------------------------------------------ #

    @staticmethod
    def collect_issue_steps(modeldata) -> list:
        """Collect all warnings/errors into a flat ordered list (errors first)."""
        severity_order = {"Attention Required!": 2, "Warning!": 1, "Well Written": 0}
        steps = []
        seen  = set()

        def _add(label, meta):
            action   = meta.get("Action", "Well Written") or "Well Written"
            elem_sev = severity_order.get(action, 0)
            if elem_sev == 0:
                return
            for c in meta.get("Comments", []):
                sev = element_verification._per_comment_sev(c, elem_sev)
                if sev == 0:
                    continue
                tag       = "ERR" if sev == 2 else "WARN"
                # Full message for web display (no truncation)
                step_text = (f"[{tag}] {label}: "
                             f"{element_verification._clean(c)}")
                dedupe_key = element_verification._issue_dedupe_key(tag, label, c)
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    steps.append((sev, step_text))

        for model in modeldata or []:
            for _, tab in model.items():
                for ucd in tab.get("Ucd Data", []):
                    for ucd_name, details in ucd.items():
                        for name, meta in details.get("System Boundary", []):
                            _add(f"System '{name}'", meta)
                        for name, meta in details.get("Primary Actors", []):
                            _add(f"Actor '{name}'", meta)
                        for name, meta in details.get("Secondary Actors", []):
                            _add(f"Actor '{name}'", meta)
                        for name, meta in details.get("Use Cases", []):
                            _add(f"Use Case '{name}'", meta)
                        for cid, meta in details.get("Connectors", []):
                            src = meta.get("Source Name", "?")
                            tgt = meta.get("Target Name", "?")
                            _add(f"Rel {src} -> {tgt}", meta)

        steps.sort(key=lambda x: -x[0])
        result = [s for _, s in steps]
        return result if result else ["No verification issues detected."]

    @staticmethod
    def collect_grouped_steps(modeldata) -> dict:
        """Return verification steps grouped by element type (errors first per group)."""
        from collections import OrderedDict

        severity_order = {"Attention Required!": 2, "Warning!": 1, "Well Written": 0}
        groups = {
            "System":           [],
            "Primary Actors":   [],
            "Secondary Actors": [],
            "Use Cases":        [],
            "Connectors":       [],
        }
        seen = set()

        def _add(group_key, label, meta):
            action   = meta.get("Action", "Well Written") or "Well Written"
            elem_sev = severity_order.get(action, 0)
            if elem_sev == 0:
                return
            for c in meta.get("Comments", []):
                sev = element_verification._per_comment_sev(c, elem_sev)
                if sev == 0:
                    continue
                tag       = "ERR" if sev == 2 else "WARN"
                # Full message; truncation to 179 chars happens in activity_panel for TTool XML
                step_text = (f"[{tag}] {label}: "
                             f"{element_verification._clean(c)}")
                dedupe_key = element_verification._issue_dedupe_key(tag, label, c)
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    groups[group_key].append((sev, step_text))

        for model in modeldata or []:
            for _, tab in model.items():
                for ucd in tab.get("Ucd Data", []):
                    for _, details in ucd.items():
                        for name, meta in details.get("System Boundary", []):
                            _add("System", f"System '{name}'", meta)
                        for name, meta in details.get("Primary Actors", []):
                            _add("Primary Actors", f"Actor '{name}'", meta)
                        for name, meta in details.get("Secondary Actors", []):
                            _add("Secondary Actors", f"Actor '{name}'", meta)
                        for name, meta in details.get("Use Cases", []):
                            _add("Use Cases", f"Use Case '{name}'", meta)
                        for _, meta in details.get("Connectors", []):
                            src = meta.get("Source Name", "?")
                            tgt = meta.get("Target Name", "?")
                            _add("Connectors", f"Rel {src} -> {tgt}", meta)

        result = OrderedDict()
        for key, items in groups.items():
            sorted_items = [s for _, s in sorted(items, key=lambda x: -x[0])]
            if sorted_items:
                result[key] = sorted_items
        return result

    @staticmethod
    def append_activity_panel(xml_content: str, steps: list) -> str:
        """Append an AvatarADPanel with steps to the XML and return updated string."""
        return append_activity_panel(xml_content, steps)

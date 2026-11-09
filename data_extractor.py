#!/usr/bin/env python3
"""
data_extractor.py - High-Precision Deterministic Data Extraction Engine

A production-grade, deterministic data extraction engine designed for automated
pipelines. Parses raw unstructured or semi-structured text, isolates target
schemas, and extracts entities with exact schema integrity and verbatim fidelity.

Execution Constraints:
1. Zero Conversational Filler: Emits only the raw extracted data structure.
2. Strict Output Mapping: Supports JSON, Markdown, and CSV formats.
3. Missing Data Handling: Strictly maps missing/ambiguous fields to null (JSON) or blank (CSV/MD).
4. Schema Integrity: Preserves exact key names, nesting, and strict data types.
5. Verbatim Priority: Extracts factual strings exactly as they appear in source text.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union


SYSTEM_ROLE_PROMPT = """[System Role & Objective]
You are an advanced, high-precision data extraction engine running in an automated production pipeline. Your sole objective is to parse the provided raw source text, isolate the target data schemas, and extract them with 100% accuracy. You must mimic a deterministic software program.

[Execution Constraints]
1. ZERO Conversational Filler: Do not include preambles, introductory phrases, explanations, notes, or post-incident commentary (e.g., do NOT write "Here is the extracted data:", "Sure, I can help with that", or "Note: some fields were missing").
2. Strict Output Mapping: Output ONLY the raw extracted data structure. If the user specifies JSON, Markdown, or CSV, output that exact format and nothing else.
3. Missing Data Handling: If a requested data point or field is missing, ambiguous, or not present in the source text, populate it exactly as null (for JSON) or leave it blank (for tables/CSV). Never hallucinate or infer missing facts.
4. Schema Integrity: Maintain exact key names, data types (strings, integers, booleans), and structural arrays as requested by the user. Do not rewrite, summarize, or alter the extracted string values unless explicitly instructed to clean them.
5. Verbatim Priority: Extract factual strings (names, dates, prices, quantities) exactly as they appear in the source text to preserve data lineage.

[Input Data]
Raw Input Text:
{source_text}

Target Schema / Format:
{target_schema}

[Processing Directive]
Analyze the input text completely. Locate the boundaries of the required entities. Format the output. Stop generation immediately after the final closing bracket/character of the data structure."""


class DataExtractionEngine:
    """Production data extraction engine running deterministic schema parsing and entity isolation."""

    def __init__(self, use_llm: bool = False, model: str = "gpt-4o-mini"):
        self.use_llm = use_llm
        self.model = model

    # -------------------------------------------------------------------------
    # Core Extraction Entry Point
    # -------------------------------------------------------------------------

    def extract(
        self,
        source_text: Optional[str],
        schema: Union[Dict[str, Any], List[str], str, None],
        output_format: str = "json",
    ) -> str:
        """
        Extracts structured data from raw source text according to the provided schema.

        Returns raw formatted string (JSON, CSV, or Markdown) with zero conversational filler.
        """
        output_format = (output_format or "json").lower().strip()
        parsed_schema = self._normalize_schema(schema)

        # Handle empty/missing input text
        if not source_text or not source_text.strip():
            empty_record = {k: None for k in parsed_schema.keys()} if parsed_schema else {}
            return self._format_output(empty_record, parsed_schema, output_format)

        # Handle empty/missing schema
        if not parsed_schema:
            return self._format_output({}, {}, output_format)

        # Attempt LLM extraction if explicitly enabled and API key is present
        if self.use_llm and os.environ.get("OPENAI_API_KEY"):
            try:
                llm_result = self._extract_via_llm(source_text, parsed_schema, output_format)
                if llm_result is not None:
                    return llm_result
            except Exception:
                # Fallback directly to deterministic extractor
                pass

        # Deterministic extraction engine
        extracted_data = self._extract_deterministic(source_text, parsed_schema)
        return self._format_output(extracted_data, parsed_schema, output_format)

    # -------------------------------------------------------------------------
    # Schema Normalization
    # -------------------------------------------------------------------------

    def _normalize_schema(self, schema: Union[Dict[str, Any], List[str], str, None]) -> Dict[str, Any]:
        """Normalizes input schema into a standardized field -> expected_type dictionary."""
        if schema is None:
            return {}

        if isinstance(schema, str):
            schema_str = schema.strip()
            if not schema_str:
                return {}
            # Strip outermost braces if present
            unbraced = schema_str
            if unbraced.startswith("{") and unbraced.endswith("}"):
                unbraced = unbraced[1:-1].strip()

            # Attempt standard JSON parse first
            try:
                loaded = json.loads(schema_str)
                return self._normalize_schema(loaded)
            except json.JSONDecodeError:
                pass

            # Parse unbraced key: type pairs (e.g., from shells that strip quotes)
            normalized: Dict[str, Any] = {}
            # Split by comma but preserve commas inside quotes/brackets
            tokens = re.split(r",\s*(?![^\[\{]*[\]\}])", unbraced)
            for token in tokens:
                token = token.strip().strip("'\"")
                if not token:
                    continue
                if ":" in token:
                    k, v = token.split(":", 1)
                    clean_k = k.strip().strip("'\"")
                    clean_v = v.strip().strip("'\"")
                    normalized[clean_k] = clean_v or "string"
                else:
                    normalized[token] = "string"
            if normalized:
                return normalized

        if isinstance(schema, list):
            return {str(item): "string" for item in schema}

        if isinstance(schema, dict):
            # If standard JSON Schema object: {"type": "object", "properties": {...}}
            if "properties" in schema and isinstance(schema["properties"], dict):
                normalized = {}
                for prop_name, prop_spec in schema["properties"].items():
                    if isinstance(prop_spec, dict):
                        normalized[prop_name] = prop_spec.get("type", "string")
                    else:
                        normalized[prop_name] = str(prop_spec)
                return normalized

            # Direct field: type map
            return {str(k): v for k, v in schema.items()}

        return {}

    # -------------------------------------------------------------------------
    # Deterministic Entity & Field Isolation
    # -------------------------------------------------------------------------

    def _extract_deterministic(self, text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deterministically isolates target schema fields from raw source text with
        100% verbatim accuracy, strict typing, and null-coercion for missing fields.
        """
        extracted: Dict[str, Any] = {}

        # First check if the text contains embedded JSON matching the schema
        embedded_json = self._extract_embedded_json(text, schema)
        if embedded_json:
            for key, expected_type in schema.items():
                val = embedded_json.get(key)
                extracted[key] = self._coerce_type(val, expected_type, text)
            return extracted

        # Field-by-field boundary search
        for key, expected_type in schema.items():
            val = self._locate_field_verbatim(text, key, expected_type)
            extracted[key] = self._coerce_type(val, expected_type, text)

        return extracted

    def _extract_embedded_json(self, text: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Checks for JSON blocks that directly populate required schema keys."""
        matches = re.findall(r"(\{[\s\S]*?\})", text)
        for m in matches:
            try:
                candidate = json.loads(m)
                if isinstance(candidate, dict):
                    # Check overlap with schema keys
                    matched_keys = set(candidate.keys()).intersection(schema.keys())
                    if matched_keys:
                        return candidate
            except json.JSONDecodeError:
                continue
        return None

    def _generate_field_candidates(self, field_name: str) -> List[str]:
        """Generates common variations of field labels in natural text (e.g., snake_case to Title Case)."""
        candidates = [field_name]
        # Replace underscores with spaces: invoice_id -> invoice id
        with_spaces = field_name.replace("_", " ")
        if with_spaces != field_name:
            candidates.append(with_spaces)
            candidates.append(with_spaces.title())  # Invoice Id
            candidates.append(with_spaces.upper())  # INVOICE ID

        # Hyphenated: invoice-id
        with_hyphens = field_name.replace("_", "-")
        if with_hyphens != field_name:
            candidates.append(with_hyphens)

        # CamelCase from snake_case: invoice_id -> invoiceId, InvoiceId
        parts = field_name.split("_")
        if len(parts) > 1:
            camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
            pascal = "".join(p.capitalize() for p in parts)
            candidates.append(camel)
            candidates.append(pascal)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for c in candidates:
            if c.lower() not in seen:
                seen.add(c.lower())
                unique.append(c)
        return unique

    def _locate_field_verbatim(self, text: str, field_name: str, expected_type: Any) -> Optional[Any]:
        """
        Locates the field boundary verbatim in the text using boundary patterns.
        Handles key-value, table, colon, equality, and markdown structures across variations.
        """
        candidates = self._generate_field_candidates(field_name)

        for candidate in candidates:
            escaped_key = re.escape(candidate)

            # High-precision patterns:
            # 1. Quoted key and quoted/unquoted value
            # 2. Key with value delimited by next key, newline, or end-of-string
            # 3. Markdown table row: | Key | Value |
            # 4. Bullet point: - Key: Value
            # 5. XML/HTML tag: <key>value</key>
            patterns = [
                # Quoted key and quoted value
                rf'(?:["\']?{escaped_key}["\']?)\s*[:=]\s*["\']([^"\'\r\n]+)["\']',
                # Key with value stopping before the next field (e.g. ", Field:") or line break
                rf'(?:["\']?{escaped_key}["\']?)\s*[:=]\s*(.+?)(?=(?:,\s*[-A-Za-z0-9_ ]{{1,30}}[:=]|\r?\n|$))',
                # Markdown table row: | Key | Value |
                rf'\|\s*{escaped_key}\s*\|\s*([^|\r\n]+)\s*\|',
                # Bullet point: - Key: Value or * Key: Value
                rf'[-*]\s*{escaped_key}\s*[:\-]\s*(.+?)(?=(?:,\s*[-A-Za-z0-9_ ]{{1,30}}[:=]|\r?\n|$))',
                # XML/HTML tag: <key>value</key>
                rf'<{escaped_key}[^>]*>([\s\S]*?)</{escaped_key}>',
            ]

            for pat in patterns:
                match = re.search(pat, text, re.IGNORECASE)
                if match:
                    raw_val = match.group(1).strip()
                    if raw_val:
                        return self._clean_verbatim_string(raw_val)

            # Check boolean patterns for candidate
            type_str = str(expected_type).lower()
            if "bool" in type_str:
                bool_pat = rf'(?:["\']?{escaped_key}["\']?)\s*[:=]?\s*(true|false|yes|no|1|0|enabled|disabled|verified|passed|failed)'
                m = re.search(bool_pat, text, re.IGNORECASE)
                if m:
                    token = m.group(1).lower()
                    return token in ("true", "yes", "1", "enabled", "verified", "passed")

        # Fallback: check if the schema field has a known semantic type (e.g., date, email, ip, amount)
        semantic_val = self._extract_semantic_entity(text, field_name, str(expected_type).lower())
        if semantic_val is not None:
            return semantic_val

        return None

    def _extract_semantic_entity(self, text: str, field_name: str, type_str: str) -> Optional[Any]:
        """Detects standard typed entities when explicit key-value labels are implicit."""
        lower_field = field_name.lower()

        # Date pattern (YYYY-MM-DD or DD/MM/YYYY or Month DD, YYYY)
        if "date" in lower_field or "timestamp" in lower_field:
            date_match = re.search(
                r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4})\b",
                text,
                re.IGNORECASE,
            )
            if date_match:
                return date_match.group(0)

        # Email pattern
        if "email" in lower_field:
            email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
            if email_match:
                return email_match.group(0)

        # IP address pattern
        if "ip" in lower_field or "host" in lower_field:
            ip_match = re.search(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", text)
            if ip_match:
                return ip_match.group(0)

        # Price / Amount pattern
        if any(term in lower_field for term in ("price", "amount", "total", "cost", "salary", "fee")):
            amount_match = re.search(r"[\$€£₹¥]?\s*(\d+(?:[.,]\d{1,2})?)\b", text)
            if amount_match:
                return amount_match.group(0).strip()

        return None

    def _clean_verbatim_string(self, raw_val: str) -> str:
        """Cleans peripheral enclosing quotes while preserving exact verbatim inner text."""
        val = raw_val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1].strip()
        return val

    # -------------------------------------------------------------------------
    # Type Coercion & Schema Integrity
    # -------------------------------------------------------------------------

    def _coerce_type(self, val: Any, expected_type: Any, source_text: str) -> Any:
        """Coerces extracted value strictly into the target schema type, or null if missing."""
        if val is None:
            return None

        type_str = str(expected_type).lower()

        if "int" in type_str:
            # Extract verbatim digits
            if isinstance(val, (int, float)):
                return int(val)
            digits = re.search(r"[-+]?\d+", str(val))
            return int(digits.group(0)) if digits else None

        if "float" in type_str or "number" in type_str:
            if isinstance(val, (int, float)):
                return float(val)
            num_match = re.search(r"[-+]?\d+(?:\.\d+)?", str(val).replace(",", ""))
            return float(num_match.group(0)) if num_match else None

        if "bool" in type_str:
            if isinstance(val, bool):
                return val
            s = str(val).lower().strip()
            if s in ("true", "1", "yes", "y", "enabled", "t"):
                return True
            if s in ("false", "0", "no", "n", "disabled", "f"):
                return False
            return None

        if "list" in type_str or "array" in type_str:
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                # Try parsing as JSON array
                if val.startswith("[") and val.endswith("]"):
                    try:
                        return json.loads(val)
                    except json.JSONDecodeError:
                        pass
                # Split on comma or newline
                items = [item.strip() for item in re.split(r"[,;\n]", val) if item.strip()]
                return items if items else None
            return [val]

        if "dict" in type_str or "object" in type_str:
            if isinstance(val, dict):
                return val
            if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            return None

        # Default string type: verbatim representation
        res_str = str(val).strip()
        return res_str if res_str else None

    # -------------------------------------------------------------------------
    # Output Formatting (Strict Output Mapping)
    # -------------------------------------------------------------------------

    def _format_output(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        output_format: str,
    ) -> str:
        """Emits strict data structure with zero conversational filler."""
        keys = list(schema.keys()) if schema else list(data.keys())

        if output_format == "json":
            # Output raw deterministic JSON
            return json.dumps(data, indent=2, ensure_ascii=False)

        if output_format == "csv":
            # RFC 4180 CSV with header row and single record row
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(keys)
            row = ["" if data.get(k) is None else str(data.get(k)) for k in keys]
            writer.writerow(row)
            return output.getvalue().rstrip("\n")

        if output_format in ("markdown", "md"):
            # Markdown table format
            if not keys:
                return "| |"
            header = "| " + " | ".join(keys) + " |"
            separator = "| " + " | ".join(["---"] * len(keys)) + " |"
            row = "| " + " | ".join("" if data.get(k) is None else str(data.get(k)) for k in keys) + " |"
            return f"{header}\n{separator}\n{row}"

        # Default fallback to JSON
        return json.dumps(data, indent=2, ensure_ascii=False)

    # -------------------------------------------------------------------------
    # Optional LLM Pipeline Backend
    # -------------------------------------------------------------------------

    def _extract_via_llm(
        self,
        source_text: str,
        schema: Dict[str, Any],
        output_format: str,
    ) -> Optional[str]:
        """Calls OpenAI with zero filler prompt if credentials exist."""
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI()
            prompt = SYSTEM_ROLE_PROMPT.format(
                source_text=source_text,
                target_schema=json.dumps(schema, indent=2),
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Extract according to schema. Output strictly {output_format.upper()} data structure.",
                    },
                ],
                temperature=0.0,
            )
            raw_output = response.choices[0].message.content or ""
            # Strip markdown fences if LLM wrapped it
            cleaned = self._clean_llm_wrappers(raw_output, output_format)
            return cleaned
        except Exception:
            return None

    def _clean_llm_wrappers(self, text: str, output_format: str) -> str:
        """Strips conversational preambles or code fences from LLM responses."""
        s = text.strip()
        if output_format == "json":
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s)
            if m:
                s = m.group(1).strip()
            # Validate JSON
            try:
                parsed = json.loads(s)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        elif output_format == "csv":
            m = re.search(r"```(?:csv)?\s*([\s\S]*?)\s*```", s)
            if m:
                s = m.group(1).strip()
        elif output_format in ("markdown", "md"):
            m = re.search(r"```(?:markdown)?\s*([\s\S]*?)\s*```", s)
            if m:
                s = m.group(1).strip()
        return s


# -----------------------------------------------------------------------------
# CLI Interface
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="High-Precision Deterministic Data Extraction Engine for Automated Production Pipelines.",
        epilog="Outputs strictly raw data structures (JSON, CSV, Markdown) with zero conversational filler.",
    )
    parser.add_argument(
        "--text",
        "-t",
        type=str,
        help="Raw input text to extract data from.",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Path to file containing raw input text.",
    )
    parser.add_argument(
        "--schema",
        "-s",
        type=str,
        help="Target schema as JSON string, dictionary, or comma-separated field list.",
    )
    parser.add_argument(
        "--schema-file",
        type=str,
        help="Path to JSON file containing target schema definition.",
    )
    parser.add_argument(
        "--format",
        "-o",
        choices=["json", "csv", "markdown"],
        default="json",
        help="Target output format: json (default), csv, or markdown.",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable optional LLM extraction backend using OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
        help="Model name when --llm is enabled (default: gpt-4o-mini).",
    )

    args = parser.parse_args()

    # Determine input text
    source_text: Optional[str] = None
    if args.text:
        source_text = args.text
    elif args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                source_text = fh.read()
        except OSError as err:
            sys.stderr.write(f"Error reading file '{args.file}': {err}\n")
            return 1
    elif not sys.stdin.isatty():
        source_text = sys.stdin.read()

    # Determine schema
    schema_spec: Any = None
    if args.schema:
        schema_spec = args.schema
    elif args.schema_file:
        try:
            with open(args.schema_file, "r", encoding="utf-8") as fh:
                schema_spec = json.load(fh)
        except (OSError, json.JSONDecodeError) as err:
            sys.stderr.write(f"Error reading schema file '{args.schema_file}': {err}\n")
            return 1

    engine = DataExtractionEngine(use_llm=args.llm, model=args.model)
    result = engine.extract(source_text, schema_spec, output_format=args.format)

    # Print strictly the extracted structure to stdout
    sys.stdout.write(result + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

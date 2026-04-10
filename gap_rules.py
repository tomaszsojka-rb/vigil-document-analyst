"""
YAML DSL Gap Analysis Rule Engine for Vigil — Document Analyst.

Evaluates documents against declarative YAML rulesets to detect missing
documents, missing fields, and cross-document discrepancies — without
requiring code changes. Domain experts can author and modify rules
using the YAML DSL defined below.

Rule types:
  - required_document: Check that a document of a given type is present
  - required_field: Check that a specific fact (by category+label) exists in a document
  - cross_check: Check that a fact value is consistent across multiple documents
  - condition: Check that a fact value meets a condition (e.g. >= threshold)

Severity levels: HIGH, MEDIUM, LOW

Usage:
  from gap_rules import load_ruleset, evaluate_rules
  ruleset = load_ruleset("rulesets/default.yaml")
  findings = evaluate_rules(ruleset, indexer_output)
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger("vigil.gap_rules")


def load_ruleset(path: str | Path | None = None) -> dict:
    """Load a YAML ruleset from file. Returns empty ruleset if no path specified or file not found."""
    if path is None:
        return {"rules": []}
    path = Path(path)

    if not path.exists():
        logger.info("Ruleset file not found: %s — gap analysis rules will be skipped", path)
        return {"rules": []}

    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "rules" not in data:
            logger.warning("Ruleset %s has no 'rules' key — skipping", path)
            return {"rules": []}
        logger.info("Loaded %d gap analysis rules from %s", len(data["rules"]), path)
        return data
    except ImportError:
        logger.warning("PyYAML not installed — YAML gap analysis rules unavailable")
        return {"rules": []}
    except Exception as exc:
        logger.error("Failed to load ruleset %s: %s", path, exc)
        return {"rules": []}


def evaluate_rules(ruleset: dict, indexer_output: dict) -> list[dict]:
    """Evaluate all rules in a ruleset against the Indexer output.

    Returns a list of findings (violations / passes).
    """
    rules = ruleset.get("rules", [])
    if not rules:
        return []

    documents = indexer_output.get("documents", [])
    findings: list[dict] = []

    for rule in rules:
        rule_type = rule.get("type", "")
        try:
            if rule_type == "required_document":
                findings.extend(_eval_required_document(rule, documents))
            elif rule_type == "required_field":
                findings.extend(_eval_required_field(rule, documents))
            elif rule_type == "cross_check":
                findings.extend(_eval_cross_check(rule, documents))
            elif rule_type == "condition":
                findings.extend(_eval_condition(rule, documents))
            else:
                logger.warning("Unknown rule type '%s' in rule '%s' — skipping", rule_type, rule.get("id", "?"))
        except Exception as exc:
            logger.error("Error evaluating rule '%s': %s", rule.get("id", "?"), exc)
            findings.append({
                "rule_id": rule.get("id", "unknown"),
                "rule_name": rule.get("name", ""),
                "status": "ERROR",
                "severity": rule.get("severity", "MEDIUM"),
                "message": f"Rule evaluation error: {exc}",
            })

    return findings


# ---------------------------------------------------------------------------
# Rule evaluators
# ---------------------------------------------------------------------------

def _match_doc_type(doc: dict, doc_type: str) -> bool:
    """Check if a document matches the required type (case-insensitive, supports subtypes)."""
    t = (doc.get("type", "") or "").lower()
    st = (doc.get("subtype", "") or "").lower()
    target = doc_type.lower()
    return t == target or st == target or target in t or target in st


def _find_docs_by_type(documents: list[dict], doc_type: str) -> list[dict]:
    """Find all documents matching a type."""
    return [d for d in documents if _match_doc_type(d, doc_type)]


def _find_fact(doc: dict, category: str | None, label_pattern: str | None) -> list[dict]:
    """Find facts in a document matching category and/or label pattern."""
    results = []
    for fact in doc.get("facts", []):
        if category and (fact.get("category", "") or "").lower() != category.lower():
            continue
        if label_pattern:
            label = fact.get("label", "") or ""
            if not re.search(label_pattern, label, re.IGNORECASE):
                continue
        results.append(fact)
    return results


def _eval_required_document(rule: dict, documents: list[dict]) -> list[dict]:
    """Check that a document of the specified type exists."""
    doc_type = rule.get("document_type", "")
    matches = _find_docs_by_type(documents, doc_type)

    if matches:
        return [{
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Required document: {doc_type}"),
            "status": "PASS",
            "severity": rule.get("severity", "MEDIUM"),
            "message": f"Document type '{doc_type}' found: {matches[0].get('source_file', matches[0].get('title', ''))}",
            "source_file": matches[0].get("source_file", ""),
        }]
    else:
        return [{
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Required document: {doc_type}"),
            "status": "FAIL",
            "severity": rule.get("severity", "MEDIUM"),
            "message": rule.get("fail_message", f"Required document type '{doc_type}' is missing from the document pack"),
            "remediation": rule.get("remediation", f"Provide a {doc_type} document"),
        }]


def _eval_required_field(rule: dict, documents: list[dict]) -> list[dict]:
    """Check that a specific field/fact exists in matching documents."""
    doc_type = rule.get("document_type")
    category = rule.get("category")
    label = rule.get("label")
    findings = []

    target_docs = _find_docs_by_type(documents, doc_type) if doc_type else documents
    if not target_docs:
        findings.append({
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Required field: {label}"),
            "status": "SKIP",
            "severity": rule.get("severity", "MEDIUM"),
            "message": f"No matching documents of type '{doc_type}' to check",
        })
        return findings

    for doc in target_docs:
        matched_facts = _find_fact(doc, category, label)
        source = doc.get("source_file", doc.get("title", "unknown"))
        if matched_facts:
            # Check confidence if threshold specified
            min_confidence = rule.get("min_confidence")
            if min_confidence is not None:
                low_conf = [f for f in matched_facts if f.get("confidence", 1.0) < min_confidence]
                if low_conf:
                    findings.append({
                        "rule_id": rule.get("id", ""),
                        "rule_name": rule.get("name", f"Required field: {label}"),
                        "status": "WARNING",
                        "severity": "MEDIUM",
                        "message": f"Field '{label}' found in [{source}] but with low confidence ({low_conf[0].get('confidence', '?')})",
                        "source_file": source,
                        "confidence": low_conf[0].get("confidence"),
                    })
                    continue
            findings.append({
                "rule_id": rule.get("id", ""),
                "rule_name": rule.get("name", f"Required field: {label}"),
                "status": "PASS",
                "severity": rule.get("severity", "MEDIUM"),
                "message": f"Field '{label}' found in [{source}]",
                "source_file": source,
            })
        else:
            findings.append({
                "rule_id": rule.get("id", ""),
                "rule_name": rule.get("name", f"Required field: {label}"),
                "status": "FAIL",
                "severity": rule.get("severity", "MEDIUM"),
                "message": rule.get("fail_message", f"Required field '{label}' (category: {category}) not found in [{source}]"),
                "source_file": source,
                "remediation": rule.get("remediation", f"Ensure {label} is present in the document"),
            })

    return findings


def _eval_cross_check(rule: dict, documents: list[dict]) -> list[dict]:
    """Check that a fact has the same value across multiple documents."""
    category = rule.get("category")
    label = rule.get("label")
    findings = []

    occurrences: list[dict] = []
    for doc in documents:
        matched = _find_fact(doc, category, label)
        for fact in matched:
            occurrences.append({
                "source_file": doc.get("source_file", doc.get("title", "unknown")),
                "value": fact.get("value", ""),
                "section": fact.get("section", ""),
            })

    if len(occurrences) < 2:
        findings.append({
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Cross-check: {label}"),
            "status": "SKIP",
            "severity": rule.get("severity", "MEDIUM"),
            "message": f"Cross-check for '{label}' requires at least 2 occurrences, found {len(occurrences)}",
        })
        return findings

    values = set(o["value"].lower().strip() for o in occurrences)
    if len(values) <= 1:
        findings.append({
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Cross-check: {label}"),
            "status": "PASS",
            "severity": rule.get("severity", "MEDIUM"),
            "message": f"'{label}' is consistent across {len(occurrences)} documents",
        })
    else:
        detail = "; ".join(f"[{o['source_file']}, {o['section']}] = {o['value']}" for o in occurrences)
        findings.append({
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", f"Cross-check: {label}"),
            "status": "FAIL",
            "severity": rule.get("severity", "HIGH"),
            "message": rule.get("fail_message", f"Discrepancy in '{label}': {detail}"),
            "occurrences": occurrences,
            "remediation": rule.get("remediation", f"Resolve conflicting values for '{label}' across documents"),
        })

    return findings


def _parse_numeric(value: str) -> float | None:
    """Try to parse a numeric value from a fact string."""
    cleaned = re.sub(r"[^\d.\-,]", "", value.replace(",", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _eval_condition(rule: dict, documents: list[dict]) -> list[dict]:
    """Check that a fact value meets a numeric condition."""
    doc_type = rule.get("document_type")
    category = rule.get("category")
    label = rule.get("label")
    operator = rule.get("operator", ">=")  # >=, <=, >, <, ==, !=
    threshold = rule.get("threshold")
    findings = []

    if threshold is None:
        return [{
            "rule_id": rule.get("id", ""),
            "rule_name": rule.get("name", ""),
            "status": "ERROR",
            "severity": "LOW",
            "message": "Condition rule missing 'threshold' — skipping",
        }]

    target_docs = _find_docs_by_type(documents, doc_type) if doc_type else documents

    for doc in target_docs:
        matched = _find_fact(doc, category, label)
        source = doc.get("source_file", doc.get("title", "unknown"))
        for fact in matched:
            num = _parse_numeric(fact.get("value", ""))
            if num is None:
                continue

            ops = {
                ">=": num >= threshold,
                "<=": num <= threshold,
                ">": num > threshold,
                "<": num < threshold,
                "==": num == threshold,
                "!=": num != threshold,
            }
            passed = ops.get(operator, True)

            if passed:
                findings.append({
                    "rule_id": rule.get("id", ""),
                    "rule_name": rule.get("name", f"Condition: {label} {operator} {threshold}"),
                    "status": "PASS",
                    "severity": rule.get("severity", "MEDIUM"),
                    "message": f"'{label}' = {num} (meets condition {operator} {threshold}) in [{source}]",
                    "source_file": source,
                })
            else:
                findings.append({
                    "rule_id": rule.get("id", ""),
                    "rule_name": rule.get("name", f"Condition: {label} {operator} {threshold}"),
                    "status": "FAIL",
                    "severity": rule.get("severity", "HIGH"),
                    "message": rule.get("fail_message", f"'{label}' = {num} (fails condition {operator} {threshold}) in [{source}]"),
                    "source_file": source,
                    "remediation": rule.get("remediation", f"Review and correct '{label}' value in [{source}]"),
                })

    return findings

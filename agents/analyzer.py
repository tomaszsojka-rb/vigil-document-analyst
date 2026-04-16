"""
Agent 2 — Analyzer
Uses direct chat completions via Azure AI Inference SDK with Structured Outputs.
Forces JSON output via response_format to eliminate broken JSON responses.
Performs the core analytical work: version comparison, compliance checking,
cross-document consistency analysis, and gap detection.
"""

import asyncio
import json
import logging
import re

from foundry_client import get_agents_client, get_analyzer_model_name, get_inference_client

logger = logging.getLogger("vigil.agents.analyzer")

AGENT_NAME = "vigil-analyzer"

WORKFLOW_INSTRUCTIONS = {
    "version_comparison": """\
You are the **Analyzer** agent performing an EXHAUSTIVE VERSION COMPARISON.

You receive structured fact sheets (with number registries) for TWO OR MORE versions or \
variants of documents. Compare them pairwise or as a version progression (v1→v2→v3, etc.). \
If given a single document, compare its internal sections for inconsistencies.

## YOUR APPROACH
First, STUDY the documents. Determine what domain they belong to (legal, financial, \
technical, regulatory, HR, etc.) and what matters most for that domain. Then compare \
EVERYTHING — but prioritize what is MOST IMPORTANT for the document type.

## YOUR TASK

### A. Document Overview
For each document, produce a 3-5 sentence description: what it is, its purpose, the key parties, \
and the most important terms/values. Include the source filename.

### B. Number Consistency Analysis (HIGHEST PRIORITY)
Using the `number_registry` from each document's fact sheet:
1. Match EVERY number across documents by context (e.g. "monthly fee" in doc A vs doc B).
2. For EACH number that appears in both documents, compare the values.
3. Flag ANY discrepancy — even small ones (e.g. $185,000 vs $185,500, or 30 days vs 45 days).
4. For numbers that appear in one document but NOT the other, flag as ADDED or REMOVED.
5. Calculate percentage change for all modified numerical values.
6. Check internal arithmetic: do line items sum to totals? Do percentages apply correctly?

### C. Section-by-Section Comparison
Compare EVERY section side-by-side. For each section:
1. Identify EVERY change — numerical, wording, added/removed clauses, conditions, definitions.
2. Classify: ADDED | REMOVED | MODIFIED
3. Rate significance: HIGH | MEDIUM | LOW
4. Quote the EXACT original text in "before" and EXACT new text in "after".
5. Explain the concrete impact of this specific change.
6. Classify the risk dimension based on what the change actually affects:
   FINANCIAL | OPERATIONAL | LEGAL | REGULATORY | TECHNICAL | COMMERCIAL | HR | OTHER

Do NOT summarize multiple changes into one entry — each change is a SEPARATE item. \
Do NOT skip minor changes. Even wording in definitions or small threshold adjustments must be listed.

CRITICAL COMPARISON RULES:
- Compare EXACT extracted values. Do NOT normalize, round, or interpret before comparing.
- Different dates are ALWAYS a change (e.g. 2017-11-15 vs 2017-03-06 = MODIFIED).
- Different version/edition numbers are ALWAYS a change (e.g. ed. 02 vs ed. 03 = MODIFIED).
- Scientific notation must be compared precisely (e.g. 10^3 vs 10^2 = MODIFIED).
- When in doubt, list it as a change — it is far worse to miss a real difference than to flag a false one.

CRITICAL — SOURCE TRACEABILITY: Every change MUST include `source_file_before` and `source_file_after` \
with EXACT uploaded filenames, and `section` with the specific article/clause number.

Return ONLY a JSON object (no markdown fences):
{
  "comparison": {
    "doc_a": {"title": "...", "version": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"},
    "doc_b": {"title": "...", "version": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"},
    "document_domain": "legal|financial|technical|regulatory|commercial|hr|mixed|other",
    "total_changes": <int>,
    "executive_summary": "3-5 sentences: total changes, most critical shifts, most important \
number changes with before/after values, overall risk assessment",
    "number_changes": [
      {"context": "what this number represents", "section": "Article/§/clause", \
"source_file_before": "exact filename", "source_file_after": "exact filename", \
"before_value": "exact original value", "after_value": "exact new value", \
"percentage_change": "+X.X% or -X.X%", \
"significance": "HIGH|MEDIUM|LOW", \
"impact": "explanation of why this number change matters"}
    ],
    "changes": [
      {"section": "Article 5.3 / §7.1 / specific clause", "clause": "specific clause reference", \
"change_type": "ADDED|REMOVED|MODIFIED", \
"significance": "HIGH|MEDIUM|LOW", "risk_dimension": "FINANCIAL|OPERATIONAL|LEGAL|REGULATORY|TECHNICAL|COMMERCIAL|HR|OTHER", \
"source_file_before": "exact filename", "source_file_after": "exact filename", \
"before": "exact original text or value — verbatim quote", \
"after": "exact new text or value — verbatim quote", \
"impact": "concrete impact. For numerical changes, include percentage change."}
    ],
    "risk_summary": {
      "by_dimension": {"FINANCIAL": "summary", "OPERATIONAL": "summary", "LEGAL": "summary"},
      "most_critical_changes": ["top 3-5 changes that require immediate attention"]
    },
    "summary": "comprehensive summary with change counts by type, significance, and risk dimension"
  }
}

IMPORTANT: Be EXHAUSTIVE. Every numerical change, every added clause, every modified condition \
must appear. It is better to list too many changes than to miss any.
""",

    "compliance_check": """\
You are the **Analyzer** agent performing a COMPLIANCE CHECK.

You receive structured fact sheets (with number registries) for one or more documents. \
Determine which document(s) serve as REFERENCE (standards, templates, policies, regulations, \
contracts defining terms) and which are TARGET(s) to check against those references. \
If roles are ambiguous, check all documents against each other for mutual consistency.

## YOUR APPROACH
First, STUDY the documents. Determine the domain and what compliance means in this context \
(contractual compliance, regulatory compliance, policy adherence, pricing consistency, etc.). \
Then check EVERY requirement systematically.

## YOUR TASK

### A. Document Overview
For each document, produce a 3-5 sentence description with source filename.

### B. Number Consistency Analysis (HIGHEST PRIORITY)
Using the `number_registry` from each fact sheet:
1. Match numbers across reference and target by context.
2. Flag ANY discrepancy where a target's number doesn't match the reference \
(e.g. invoice total vs. PO amount, contracted price vs. billed price, \
policy limit vs. actual value).
3. For each discrepancy: show reference value, target value, percentage difference, and impact.
4. Check internal arithmetic in each document.

### C. Requirement-by-Requirement Check
For each requirement/provision in the reference:
1. Find the corresponding section in the target.
2. Classify: COMPLIANT | DEVIATION | MISSING | PARTIAL
3. For deviations: quote the EXACT text from both documents.
4. Assess severity: HIGH | MEDIUM | LOW
5. Classify risk dimension based on content: FINANCIAL | OPERATIONAL | LEGAL | REGULATORY | TECHNICAL | OTHER
6. Suggest specific remediation.

CRITICAL — SOURCE TRACEABILITY: Every finding MUST include `source_file` and `reference_file` \
with EXACT uploaded filenames. NEVER use "doc-1".

Return ONLY a JSON object (no markdown fences):
{
  "compliance_report": {
    "targets": [{"title": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"}],
    "references": [{"title": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"}],
    "document_domain": "legal|financial|technical|regulatory|commercial|hr|mixed|other",
    "executive_summary": "3-5 sentences: compliance posture, critical gaps, key number discrepancies, \
readiness assessment",
    "gap_rule_results": "summary of YAML DSL gap rule findings if provided",
    "number_discrepancies": [
      {"context": "what this number represents", \
"reference_file": "exact filename", "reference_section": "Article/§/clause", "reference_value": "...", \
"target_file": "exact filename", "target_section": "Article/§/clause", "target_value": "...", \
"percentage_difference": "+X.X% or -X.X%", \
"severity": "HIGH|MEDIUM|LOW", \
"impact": "why this discrepancy matters"}
    ],
    "findings": [
      {"requirement": "...", "reference_section": "Article/§/clause", \
"reference_file": "exact filename", \
"status": "COMPLIANT|DEVIATION|MISSING|PARTIAL", \
"target_section": "Article/§/clause", "source_file": "exact filename", \
"finding": "detailed description with exact quotes from both documents", \
"risk_dimension": "FINANCIAL|OPERATIONAL|LEGAL|REGULATORY|TECHNICAL|OTHER", \
"severity": "HIGH|MEDIUM|LOW", \
"remediation_suggestion": "specific recommendation"}
    ],
    "compliance_score": "X/Y requirements met",
    "risk_summary": {
      "critical_gaps": "summary of most important gaps",
      "critical_missing_items": ["HIGH severity missing requirements"]
    },
    "summary": "comprehensive summary with counts by status and severity"
  }
}

IMPORTANT — GAP RULE FINDINGS: If the input includes `gap_rule_findings`, incorporate all \
FAIL/WARNING findings into your report and include a `gap_rule_results` summary.
""",

    "document_pack": """\
You are the **Analyzer** agent performing a DOCUMENT PACK ANALYSIS.

You receive structured fact sheets (with number registries) for a SET of related documents.

## YOUR APPROACH
First, STUDY all documents. Determine what domain they belong to and what a COMPLETE pack \
looks like for this type of document set. Then assess completeness, consistency, and gaps.

## YOUR TASK

### A. Document Overview
For each document, produce a 3-5 sentence description with source filename, type, and purpose.

### B. Number Consistency Analysis (HIGHEST PRIORITY)
Using the `number_registry` from all fact sheets:
1. Find every number that appears in MULTIPLE documents and compare values.
2. Flag ANY discrepancy (e.g., contract says $100K/month but invoice shows $105K, \
or SOW says 10 deliverables but project plan lists 12).
3. For each discrepancy: show both values, their sources, percentage difference, and impact.
4. Check cross-document arithmetic (e.g., do individual invoices sum to the total in the summary?).
5. Flag numbers that should appear in multiple documents but are missing from some.

### C. Pack Completeness Assessment
Determine what documents SHOULD be in this pack based on the document types present. \
List what's present, what's missing, and what should be added.

### D. Conflict & Gap Detection
Find inconsistencies and gaps across ALL documents:
- Conflicting facts (different dates, amounts, party names, terms)
- Missing information that should exist given the other documents
- Duplicated or contradictory provisions

CRITICAL — SOURCE TRACEABILITY: Every conflict and gap MUST cite EXACT filenames and sections.

Return ONLY a JSON object (no markdown fences):
{
  "pack_analysis": {
    "documents_reviewed": [{"title": "...", "source_file": "exact_filename.pdf", "type": "...", \
"overview": "3-5 sentence document description"}],
    "document_domain": "legal|financial|technical|regulatory|commercial|hr|mixed|other",
    "executive_summary": "3-5 sentences: pack composition, completeness, critical number \
discrepancies, readiness assessment",
    "number_discrepancies": [
      {"context": "what these numbers represent", \
"doc_a_file": "exact filename", "doc_a_section": "Article/§/clause", "doc_a_value": "...", \
"doc_b_file": "exact filename", "doc_b_section": "Article/§/clause", "doc_b_value": "...", \
"percentage_difference": "+X.X% or -X.X%", \
"severity": "HIGH|MEDIUM|LOW", \
"impact": "why this matters"}
    ],
    "completeness": {
      "present": ["..."],
      "missing": ["..."],
      "recommended_additions": ["..."],
      "assessment": "Ready|Needs Work|Incomplete"
    },
    "conflicts": [
      {"fact": "...", "doc_a_file": "exact_filename.pdf", "doc_a_section": "Article/§/clause", "doc_a_value": "...", \
"doc_b_file": "exact_filename.pdf", "doc_b_section": "Article/§/clause", "doc_b_value": "...", \
"risk_dimension": "FINANCIAL|OPERATIONAL|LEGAL|REGULATORY|TECHNICAL|OTHER", "severity": "HIGH|MEDIUM|LOW"}
    ],
    "gaps": [
      {"description": "...", "source_file": "exact_filename.pdf", "section": "Article/§/clause", \
"risk_dimension": "...", "severity": "HIGH|MEDIUM|LOW", "recommendation": "..."}
    ],
    "summary": "..."
  }
}

IMPORTANT — GAP RULE FINDINGS: If the input includes `gap_rule_findings`, incorporate all \
FAIL findings as additional gaps and WARNING findings as data quality concerns.
""",

    "fact_extraction": """\
You are the **Analyzer** agent performing FACT EXTRACTION & CROSS-CHECK.

You receive structured fact sheets (with number registries) for one or more documents.

## YOUR APPROACH
First, STUDY the documents to understand their domain. Then build a complete fact catalog \
and rigorously cross-check every data point.

## YOUR TASK

### A. Document Overview
For each document, produce a 3-5 sentence description with source filename.

### B. Number Consistency Analysis (HIGHEST PRIORITY)
Using the `number_registry` from all fact sheets:
1. Build a master number table: every number, its context, its source, and its section.
2. Find EVERY number that appears in more than one document and compare.
3. Flag ALL discrepancies with exact values, sources, and percentage differences.
4. Check arithmetic: do line items sum to totals? Do percentages apply correctly?
5. Flag contextually related numbers even if labels differ \
(e.g., "monthly fee" in contract vs. "amount due" in invoice).

CRITICAL CONSISTENCY RULES:
- Two values are DISCREPANCY if they differ in ANY way — even slightly. \
Do NOT normalize, round, or interpret values before comparing. Compare the EXACT extracted values.
- Different dates are ALWAYS a discrepancy (e.g. 2017-11-15 vs 2017-03-06 = DISCREPANCY, not consistent).
- Different version numbers are ALWAYS a discrepancy (e.g. ed. 02 vs ed. 03 = DISCREPANCY).
- Scientific notation must be compared precisely (e.g. 10^3 vs 10^2 = DISCREPANCY).
- When in doubt, mark as DISCREPANCY — it is far worse to miss a real difference than to flag a false one.

### C. Master Fact Table
Consolidate ALL facts from all documents into a unified table by category.

### D. Cross-Document Discrepancies
Find same or related facts with DIFFERENT values across documents. \
Every fact that has different values across documents MUST appear here — do NOT skip any.

CRITICAL — SOURCE TRACEABILITY: Every fact MUST include `source_file` (exact filename) \
and `section` (exact clause). NEVER use "doc-1".

Return ONLY a JSON object (no markdown fences):
{
  "cross_check": {
    "documents_reviewed": [{"title": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"}],
    "document_domain": "legal|financial|technical|regulatory|commercial|hr|mixed|other",
    "executive_summary": "3-5 sentences: facts extracted, key discrepancies, number mismatches, \
overall data consistency assessment",
    "number_consistency": [
      {"context": "what these numbers represent", \
"occurrences": [{"source_file": "exact filename", "section": "Article/§/clause", "value": "...", "normalized": 0.0}], \
"status": "CONSISTENT|DISCREPANCY", \
"percentage_difference": "+X.X% (if discrepancy)", \
"severity": "HIGH|MEDIUM|LOW", \
"note": "explanation"}
    ],
    "fact_table": [
      {"fact": "...", "category": "date|amount|party|obligation|kpi|line_item|quantity|percentage|threshold", \
"sources": [{"source_file": "exact filename", "section": "Article/§/clause", "value": "..."}], \
"critical": true|false}
    ],
    "discrepancies": [
      {"fact": "...", \
"occurrences": [{"source_file": "exact filename", "section": "Article/§/clause", "value": "..."}], \
"risk_dimension": "FINANCIAL|OPERATIONAL|LEGAL|REGULATORY|TECHNICAL|OTHER", \
"severity": "HIGH|MEDIUM|LOW", "note": "explanation and recommended resolution"}
    ],
    "highlights": [
      {"fact": "...", "value": "...", "source_file": "exact filename", "section": "Article/§/clause", \
"note": "why this fact is noteworthy"}
    ],
    "summary": "comprehensive summary with discrepancy counts by severity"
  }
}
""",

    "summary": """\
You are the **Analyzer** agent performing CONTENT ANALYSIS for an EXECUTIVE SUMMARY.

You receive structured fact sheets (with number registries) for one or more documents.

## YOUR APPROACH
First, STUDY the documents. Identify the domain — this determines which themes and categories \
matter most. Then synthesize the content into a strategic overview.

## YOUR TASK

### A. Document Overview
For each document, produce a 3-5 sentence description with source filename.

### B. Key Numbers & Financial Summary (HIGHEST PRIORITY when applicable)
Identify the most important numbers in the documents and present them prominently. \
If multiple documents share numbers, highlight consistency or discrepancies.
Always surface material monetary amounts, prices, fees, contract durations, effective dates, deadlines, thresholds, and caps when they appear in the extracted data. \
If a recurring fee, total amount, contractual period, or pricing figure appears in the sections, facts, or `number_registry`, include it explicitly in `key_numbers` and in the relevant findings. \
Do NOT say a value is missing if it appears anywhere in the provided extracted data.
If there are only a few material numbers in the extracted data, include all of them rather than selecting a subset.

### C. Theme Identification & Key Findings
Identify the most important themes based on the ACTUAL DOCUMENT CONTENT. \
Do not use pre-determined categories — let the documents drive the analysis. \
For each finding: state what it is, why it matters, and cite the exact source.

### D. Critical Items
Flag items requiring immediate attention, with urgency classification.

CRITICAL — SOURCE TRACEABILITY: Every finding MUST include `source_file` (exact filename) \
and `section` (exact clause). NEVER use "doc-1".

Return ONLY a JSON object (no markdown fences):
{
  "analysis": {
    "documents_reviewed": [{"title": "...", "source_file": "exact_filename.pdf", \
"overview": "3-5 sentence document description"}],
    "document_domain": "legal|financial|technical|regulatory|commercial|hr|mixed|pharmaceutical|other",
    "executive_summary": "5-7 sentences for senior leadership: what these documents cover, \
key financial/commercial highlights, critical items, and overall assessment",
    "key_numbers": [
      {"value": "...", "context": "what it represents", \
"source_file": "exact filename", "section": "Article/§/clause", \
"importance": "HIGH|MEDIUM|LOW", "note": "why it matters"}
    ],
    "themes": ["..."],
    "key_findings": [
      {"category": "auto-determined based on document content", \
"finding": "detailed description", "importance": "HIGH|MEDIUM|LOW", \
"source_file": "exact_filename.pdf", "section": "Article/§/clause", \
"action_required": true|false, \
"action_description": "what needs to happen if action required"}
    ],
    "critical_items": [
      {"item": "...", "urgency": "IMMEDIATE|SHORT_TERM|MEDIUM_TERM", \
"source_file": "exact_filename.pdf", "section": "Article/§/clause", \
"recommended_action": "..."}
    ],
    "flags": ["items with significant implications — include source_file and section"],
    "summary": "..."
  }
}

IMPORTANT FOR SUMMARY WORKFLOWS: If pricing, fee amounts, contract durations, deadlines, \
or liability caps are present, they are material and should normally appear in both \
`key_numbers` and the final summary.
""",
}


BASE_INSTRUCTIONS = """\
You are the **Analyzer** agent, the second stage in a document analysis pipeline.
You receive structured fact sheets from the Indexer agent and perform analytical work.
You will be given specific workflow instructions for each analysis task.
Always return ONLY a JSON object (no markdown fences, no explanation).

YOUR APPROACH: First, study the documents to determine their domain and what matters most. \
Then adapt your analysis to what is actually important for THESE specific documents. \
Do not apply a fixed template — let the document content drive your focus areas.

YOUR HIGHEST PRIORITIES across ALL workflows:
1. **Number consistency** — Rigorously cross-reference every number across documents. \
Use the `number_registry` from fact sheets to find every discrepancy.
2. **Exact quotes** — Every finding must cite specific source files and sections with verbatim text.
3. **Exhaustiveness** — It is better to report too many findings than to miss any.
4. **Document overviews** — Always include a 3-5 sentence description of each document.
5. **Authoritative extracted data** — When structured reference data is provided, treat it as the authoritative extracted record. \
Do not claim a fact, quote, amount, duration, deadline, or cap is missing if it appears in that structured reference data, even if it is absent from narrower retrieved snippets.
6. **Semantic consistency** — Explicitly check for cross-document contradictions in meaning, terminology, units, timelines, obligations, and legal interpretation.

Always classify findings by risk dimension and severity (HIGH, MEDIUM, LOW). \
Use risk dimensions that match the actual content — do not force categories that don't apply.

CRITICAL: Always use actual uploaded filenames (from the `source_file` field in fact sheets) \
in your output — NEVER use generic identifiers like "doc-1", "Document 1", etc.
"""


def ensure_analyzer_agent() -> str:
    """Find or create the Analyzer agent in Foundry. Updates instructions if agent exists."""
    from agents import find_agent_by_name

    client = get_agents_client()
    model = get_analyzer_model_name()
    existing_id = find_agent_by_name(AGENT_NAME)
    if existing_id:
        try:
            kwargs = dict(agent_id=existing_id, model=model, instructions=BASE_INSTRUCTIONS)
            try:
                client.update_agent(**kwargs, temperature=0.1)
            except Exception:
                client.update_agent(**kwargs)
            logger.info("Updated Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, existing_id)
        except Exception as exc:
            logger.warning("Could not update agent '%s', using existing: %s", AGENT_NAME, exc)
        return existing_id

    try:
        agent = client.create_agent(model=model, name=AGENT_NAME, instructions=BASE_INSTRUCTIONS, temperature=0.1)
    except Exception:
        agent = client.create_agent(model=model, name=AGENT_NAME, instructions=BASE_INSTRUCTIONS)
    logger.info("Created Foundry agent '%s' (model=%s): %s", AGENT_NAME, model, agent.id)
    return agent.id


def _call_analyzer_sync(system_prompt: str, user_message: str) -> str:
    """Synchronous chat completion call with Structured Outputs (json_object mode).

    Uses the Azure AI Inference SDK for a single HTTP call with
    response_format={'type': 'json_object'} to guarantee valid JSON output.
    """
    from azure.ai.inference.models import SystemMessage, UserMessage

    model = get_analyzer_model_name()
    client = get_inference_client(model)

    call_kwargs = dict(
        messages=[
            SystemMessage(content=system_prompt),
            UserMessage(content=user_message),
        ],
    )
    # Try with structured outputs (json_object), fall back without if unsupported
    try:
        response = client.complete(**call_kwargs, response_format={"type": "json_object"}, temperature=0.1)
    except Exception:
        try:
            response = client.complete(**call_kwargs, response_format={"type": "json_object"})
        except Exception:
            try:
                response = client.complete(**call_kwargs, temperature=0.1)
            except Exception:
                response = client.complete(**call_kwargs)

    return response.choices[0].message.content or ""


async def run_analyzer(workflow: str, indexer_output: dict, language: str = "en", custom_instructions: str = "", search_context: str = "") -> dict:
    """Run the Analyzer via direct chat completions with Structured Outputs.

    Uses response_format={'type': 'json_object'} to guarantee valid JSON.
    When search_context is provided (from Azure AI Search facts index), the Analyzer
    receives compact structured reference data plus focused retrieved context instead
    of the full Indexer JSON dump. This preserves complete numbers and facts while
    still reducing prompt size and improving speed and reliability.
    Falls back to full JSON if search_context is empty.
    """
    instructions = WORKFLOW_INSTRUCTIONS.get(workflow, WORKFLOW_INSTRUCTIONS["summary"])

    if language == "pl":
        instructions += (
            "\n\nIMPORTANT: All text values in your JSON output (summaries, findings, descriptions, impacts) MUST be in Polish (polski). "
            "Keep JSON keys in English. However, any 'before', 'after', or 'original_quote' fields MUST contain the EXACT original text from the document — do NOT translate them."
        )

    if custom_instructions:
        instructions += f"\n\nUSER'S SPECIFIC INSTRUCTIONS: {custom_instructions}"

    # Build the user message: focused context when available, full JSON as fallback
    if search_context.strip():
        # Build compact document metadata plus the complete structured numbers/facts block.
        doc_summaries = _build_doc_summaries(indexer_output)
        structured_reference = _build_structured_reference_data(indexer_output)
        user_message = (
            f"{instructions}\n\n"
            f"Document summaries:\n{doc_summaries}\n\n"
            f"Structured reference data (authoritative extracted sections, facts, and number registry). "
            f"If a value appears here, treat it as present in the extracted document data and do not describe it as missing:\n"
            f"{structured_reference}\n\n"
            f"Relevant extracted data (retrieved via semantic search):\n{search_context}\n\n"
            f"Perform your analysis now."
        )
        # Also include gap_rule_findings if present
        gap_findings = indexer_output.get("gap_rule_findings")
        if gap_findings:
            user_message = (
                f"{instructions}\n\n"
                f"Document summaries:\n{doc_summaries}\n\n"
                f"Structured reference data (authoritative extracted sections, facts, and number registry). "
                f"If a value appears here, treat it as present in the extracted document data and do not describe it as missing:\n"
                f"{structured_reference}\n\n"
                f"Relevant extracted data (retrieved via semantic search):\n{search_context}\n\n"
                f"Gap rule findings:\n{json.dumps(gap_findings, indent=1)}\n\n"
                f"Perform your analysis now."
            )
    else:
        user_message = f"{instructions}\n\nIndexer output:\n\n{json.dumps(indexer_output, indent=2)}\n\nPerform your analysis now."

    # Run via direct chat completions with Structured Outputs
    system_prompt = f"{BASE_INSTRUCTIONS}\n\n{instructions}"

    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, _call_analyzer_sync, system_prompt, user_message)

    try:
        parsed = _parse_json_robust(text)
        if parsed is not None:
            if workflow == "summary":
                parsed = _ensure_summary_key_numbers(parsed, indexer_output)
            return parsed
    except Exception as exc:
        logger.warning("Analyzer JSON parse failed: %s", exc)

    logger.warning("Analyzer returned non-JSON. First 500 chars: %s", text[:500])
    return {"error": "Analyzer did not return valid JSON — please retry", "raw_output": text}


def _parse_json_robust(text: str) -> dict | None:
    """Parse JSON from model output, handling fences, extra data, and truncation."""
    import re
    # Strip markdown fences
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    start = stripped.find("{")
    if start < 0:
        return None

    # Try from first { to last }
    end = stripped.rfind("}") + 1
    if end > start:
        try:
            return json.loads(stripped[start:end])
        except json.JSONDecodeError:
            pass

    # "Extra data" case: find the end of the FIRST complete JSON object
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        c = stripped[i]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except json.JSONDecodeError:
                    break

    # Truncation repair: close unmatched braces/brackets
    candidate = stripped[start:end] if end > start else stripped[start:]
    candidate = re.sub(r",\s*$", "", candidate)
    open_b = candidate.count("{") - candidate.count("}")
    open_sq = candidate.count("[") - candidate.count("]")
    candidate += "]" * max(0, open_sq)
    candidate += "}" * max(0, open_b)
    try:
        result = json.loads(candidate)
        logger.info("Analyzer JSON repaired (closed %d braces, %d brackets)", open_b, open_sq)
        return result
    except json.JSONDecodeError:
        pass

    return None


def _build_doc_summaries(indexer_output: dict) -> str:
    """Build compact document metadata block for focused Analyzer prompts."""
    parts: list[str] = []
    for doc in indexer_output.get("documents", []):
        source = doc.get("source_file", doc.get("title", "unknown"))
        doc_type = doc.get("type", "other")
        overview = doc.get("document_overview", "")
        version = doc.get("version", "")
        date = doc.get("date", "")
        doc_num = doc.get("document_number", "")
        section_count = len(doc.get("sections", []))
        fact_count = len(doc.get("facts", []))
        number_count = len(doc.get("number_registry", []))

        summary = f"[{source}] type={doc_type}"
        if version:
            summary += f", version={version}"
        if date:
            summary += f", date={date}"
        if doc_num:
            summary += f", doc_number={doc_num}"
        summary += f", sections={section_count}, facts={fact_count}, numbers={number_count}"
        if overview:
            summary += f"\n  Overview: {overview}"
        parts.append(summary)

    return "\n".join(parts) if parts else "(no documents)"


def _build_structured_reference_data(indexer_output: dict) -> str:
    """Build a compact but complete facts/numbers block for Analyzer prompts."""
    parts: list[str] = []

    for doc in indexer_output.get("documents", []):
        source = doc.get("source_file", doc.get("title", "unknown"))
        parts.append(f"[{source}]")

        sections = doc.get("sections", [])
        if sections:
            parts.append("  Sections:")
            for section_data in sections:
                section_number = section_data.get("section_number", "")
                heading = section_data.get("heading", "")
                summary = section_data.get("summary", "")
                quote = section_data.get("original_quote", "")
                line = f"    - Section {section_number or '?'}"
                if heading:
                    line += f" | {heading}"
                if summary:
                    line += f" | Summary: {summary}"
                if quote:
                    line += f" | Quote: {quote}"
                parts.append(line[:500])

        facts = doc.get("facts", [])
        if facts:
            parts.append("  Facts:")
            for fact in facts:
                category = fact.get("category", "")
                label = fact.get("label", "")
                value = fact.get("value", "")
                section = fact.get("section", "")
                line = f"    - [{category}] {label} = {value}"
                if section:
                    line += f" (section: {section})"
                parts.append(line[:300])

        number_registry = doc.get("number_registry", [])
        if number_registry:
            parts.append("  Number registry:")
            for number in number_registry:
                value = number.get("value", "")
                unit = number.get("unit", "")
                context = number.get("context", "")
                section = number.get("section", "")
                line = f"    - {context or 'number'} = {value}"
                if unit and unit.lower() not in str(value).lower():
                    line += f" {unit}"
                if section:
                    line += f" (section: {section})"
                parts.append(line[:300])

    return "\n".join(parts) if parts else "(no structured reference data)"


def _ensure_summary_key_numbers(parsed: dict, indexer_output: dict) -> dict:
    """Ensure summary analyses carry forward material numeric clauses from the Indexer."""
    analysis = parsed.get("analysis")
    if not isinstance(analysis, dict):
        return parsed

    deterministic_numbers = _extract_summary_key_numbers(indexer_output)
    if not deterministic_numbers:
        return parsed

    existing = analysis.get("key_numbers")
    existing_list = existing if isinstance(existing, list) else []
    seen = {
        (
            str(item.get("source_file", "")),
            str(item.get("section", "")),
            str(item.get("value", "")),
        )
        for item in existing_list
        if isinstance(item, dict)
    }

    merged = list(existing_list)
    for item in deterministic_numbers:
        key = (item["source_file"], item["section"], item["value"])
        if key not in seen:
            merged.append(item)
            seen.add(key)

    analysis["key_numbers"] = merged
    return parsed


def _extract_summary_key_numbers(indexer_output: dict) -> list[dict]:
    """Build a deterministic list of material numeric clauses for summary workflows."""
    candidates: list[tuple[int, int, dict]] = []

    for doc in indexer_output.get("documents", []):
        source = doc.get("source_file", doc.get("title", "unknown"))
        for section_data in doc.get("sections", []):
            quote = str(section_data.get("original_quote", "")).strip()
            if not quote or not re.search(r"\d", quote):
                continue

            section_number = str(section_data.get("section_number", "")).strip()
            heading = str(section_data.get("heading", "")).strip() or f"Section {section_number or '?'}"
            summary = str(section_data.get("summary", "")).strip()
            score, importance = _score_summary_numeric_clause(heading, quote)
            note = summary or "Explicit numeric clause extracted from the document."
            sort_order = int(section_number) if section_number.isdigit() else 999

            candidates.append((
                score,
                sort_order,
                {
                    "value": quote,
                    "context": heading,
                    "source_file": source,
                    "section": heading,
                    "importance": importance,
                    "note": note,
                },
            ))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]["context"]))

    results: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for _, _, item in candidates:
        key = (item["source_file"], item["section"], item["value"])
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= 12:
            break

    return results


def _score_summary_numeric_clause(heading: str, quote: str) -> tuple[int, str]:
    """Rank numeric clauses so summary workflows keep the most material items first."""
    text = f"{heading} {quote}".lower()

    if any(token in text for token in ("fee", "price", "payment", "invoice", "amount", "cost", "rate")):
        return 100, "HIGH"
    if any(token in text for token in ("liability", "cap", "limit", "penalty", "damages")):
        return 95, "HIGH"
    if any(token in text for token in ("term", "duration", "period", "months", "days", "deadline", "effective date", "date")):
        return 85, "MEDIUM"
    return 60, "MEDIUM"

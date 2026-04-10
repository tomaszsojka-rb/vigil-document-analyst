# �️ Vigil — Document Analyst

> **Multi-agent AI pipeline for enterprise document analysis, comparison, and compliance validation.**
> Built with Azure AI Agent Service SDK, Azure AI Foundry, and Azure AI Search.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Azure AI Foundry](https://img.shields.io/badge/Azure_AI_Foundry-GPT--4.1-purple?logo=microsoft-azure&logoColor=white)
![Azure AI Search](https://img.shields.io/badge/Azure_AI_Search-Semantic-teal?logo=microsoft-azure&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agents](#agents)
- [Workflows](#workflows)
- [Document Parsing](#document-parsing)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Azure Resource Setup](#azure-resource-setup)
- [Cost Management](#cost-management)
- [Design Decisions & Best Practices](#design-decisions--best-practices)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Performance](#performance)
- [License](#license)

---

## Overview

Vigil is an AI-powered document analyst that helps enterprise users analyze, compare, and validate documents through a **three-stage multi-agent pipeline**. Upload your documents, select an analysis workflow, and three specialized AI agents will extract structured facts, perform deep analysis, and deliver a professional markdown report — in under a minute.

### What It Does

- **Version Comparison** — Upload two versions of the same contract and get a line-by-line change log with business impact ratings.
- **Compliance Check** — Compare a document against a reference standard and get a compliance matrix with remediation plan.
- **Document Pack Analysis** — Analyze a set of related documents (SOW + Budget + Risk Register) for completeness, conflicts, and gaps.
- **Fact Extraction** — Extract every key fact (dates, amounts, parties, obligations) and cross-check consistency across documents.
- **Executive Summary** — Generate a C-level overview with risk highlights and prioritized action items.

### Key Features

- **3 specialized AI agents** — Indexer → Analyzer → Advisor, sequential pipeline with separation of concerns
- **9 supported file formats** — PDF, DOCX, TXT, XLSX/XLS, PNG, JPG/JPEG, TIFF, BMP
- **Document parsing** — Python libraries (PyMuPDF, python-docx, openpyxl) extract text and tables from all formats; Azure AI Document Intelligence OCR handles scanned documents and images
- **Bilingual** — Full English and Polish (polski) support, including all UI text, agent prompts, and generated reports
- **Custom instructions** — Tell Vigil what to focus on (e.g., "Pay special attention to liability clauses")
- **Follow-up chat** — Ask questions about analysis results after the pipeline completes
- **Real-time pipeline visualization** — Watch each agent complete its stage with live progress indicators
- **Transparent outputs** — Inspect raw JSON from Indexer and Analyzer, not just the final Advisor report
- **Guided tour** — First-time visitors get an interactive walkthrough of the UI
- **Agent detail modals** — Click any agent card to read its full technical and business description

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Web UI (localhost:3000)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐  │
│  │   Home   │→│  Upload  │→│ Workflow │→│ Processing│→│ Results │  │
│  │  + Tour  │ │ drag&drop│ │  picker  │ │ live view │ │ + chat  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘ └─────────┘  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ POST /api/run
┌──────────────────────────▼───────────────────────────────────────────┐
│                    Orchestrator (app.py)                              │
│  • Multipart file upload + doc parsing                               │
│    (Python libraries + Document Intelligence OCR)                     │
│  • Async job management with TTL cleanup                             │
│  • Input validation (workflow whitelist, message length caps)         │
└──────────┬───────────────┬──────────────────┬────────────────────────┘
           │               │                  │
           ▼               ▼                  ▼
    ┌─────────────┐ ┌─────────────┐  ┌──────────────┐
    │   Agent 1   │ │   Agent 2   │  │   Agent 3    │
    │  Indexer &  │→│  Analyzer   │→ │   Advisor    │
    │  Extractor  │ │             │  │              │
    └──────┬──────┘ └──────┬──────┘  └──────┬───────┘
           │               │                │
    Structured JSON   Structured JSON   Markdown Report
    (facts, sections) (diffs, findings) (tables, actions)
           │               │                │
           └───────────────┼────────────────┘
                           │
               Azure AI Foundry Agent Service
               ┌───────────┴───────────┐
               │      AgentsClient     │
               │  DefaultAzureCredential│
               │ Indexer/Analyzer: GPT-4.1-mini│
               │ Advisor: GPT-4.1      │
               └───────────────────────┘
```

### Data Flow

1. **User uploads** documents via the web UI (drag & drop or file picker).
2. **Doc parser** extracts text and tables via Python libraries (PyMuPDF, python-docx, openpyxl) with Azure AI Document Intelligence OCR for scanned documents.
3. **Orchestrator** creates an async job and passes documents through the 3-agent pipeline.
4. **Agent 1 (Indexer)** receives raw text → produces structured JSON fact sheets.
5. **Agent 2 (Analyzer)** receives the fact sheets + workflow-specific instructions → produces analysis JSON.
6. **Agent 3 (Advisor)** receives the analysis JSON → produces a human-readable markdown report.
7. **Results page** renders the markdown report with tables, risk ratings, and action items. Users can switch tabs to inspect raw Indexer/Analyzer JSON.
8. **Follow-up chat** lets users ask questions about the analysis with full pipeline context.

### Agent Communication

All three agents run as **persistent Foundry agents** via the Azure AI Agent Service SDK. They are registered once at startup (`find-or-create` pattern) and reused across requests. Each invocation creates a new **thread** (conversation), sends the input as a user message, and polls for completion. Agents never share threads — each pipeline run is isolated.

---

## Agents

### Agent 1 — Indexer & Fact Extractor

| Aspect | Detail |
|--------|--------|
| **Purpose** | Convert unstructured document content into structured, machine-readable JSON |
| **Input** | Extracted content from uploaded documents — text, tables, and figures (all formats combined into a single prompt) |
| **Output** | Structured JSON fact sheet per document |
| **Temperature** | `0.1` (deterministic extraction) |
| **What it extracts** | Document metadata (title, type, version, author, date), section headings with summaries, structured facts (`date`, `amount`, `party`, `obligation`, `kpi`), and **exact verbatim quotes** (`original_quote`) from the source document for traceability |

**Key principle:** The Indexer only extracts facts that are **explicitly stated** in the document — it never infers or hallucinates. Every fact and section includes an `original_quote` field with the exact text from the source document in its original language, ensuring full traceability even when the output is translated.

**Output example:**
```json
{
  "documents": [
    {
      "doc_id": "doc-1",
      "title": "Vendor Services Agreement",
      "type": "contract",
      "version": "2.0",
      "sections": [
        {
          "heading": "Payment Terms",
          "summary": "Monthly fee of $185,000, due within 45 days of invoice receipt",
          "original_quote": "The Client shall pay the Vendor a monthly fee of $185,000 USD. Payment is due within 45 days of invoice receipt."
        }
      ],
      "facts": [
        {
          "category": "amount",
          "label": "Monthly fee",
          "value": "$185,000 USD",
          "section": "Payment Terms",
          "original_quote": "The Client shall pay the Vendor a monthly fee of $185,000 USD."
        },
        {
          "category": "date",
          "label": "Effective date",
          "value": "January 20, 2026",
          "section": "Definitions",
          "original_quote": "\"Effective Date\" means January 20, 2026."
        }
      ]
    }
  ]
}
```

> **Note:** The `original_quote` field always contains the exact verbatim text from the source document in its original language — even when the output language is set to Polish. This ensures traceability back to the source.

### Agent 2 — Analyzer

| Aspect | Detail |
|--------|--------|
| **Purpose** | Perform the specific analytical task requested by the user's chosen workflow |
| **Input** | Structured JSON from Agent 1 + workflow-specific system prompt |
| **Output** | Analysis result as structured JSON |
| **Temperature** | `0.1` (consistent analysis) |
| **5 workflow modes** | Version diff, compliance matrix, pack completeness, fact cross-check, content analysis |

**Key principle:** Every finding includes a **severity rating** (`HIGH` / `MEDIUM` / `LOW`) and **cites the specific section** in each document, making every output auditable.

### Agent 3 — Advisor

| Aspect | Detail |
|--------|--------|
| **Purpose** | Translate structured analysis into a business-ready, human-readable report |
| **Input** | Structured JSON from Agent 2 |
| **Output** | Professional markdown with tables, risk indicators (🔴🟡🟢), and numbered action items |
| **Temperature** | `0.3` (slightly creative for natural language) |
| **Report sections** | Executive summary, detailed findings (tables/matrices), risk highlights, recommended next actions |

**Key principle:** The Advisor always **separates facts from interpretation** and **cites specific document sections** for every finding, making reports fully traceable to source material.

---

## Workflows

| Workflow | Min. Docs | What it does | Analyzer output | Advisor report |
|----------|:---------:|-------------|----------------|----------------|
| **Version Comparison** | 2 | Side-by-side section diff with change classification (`ADDED` / `REMOVED` / `MODIFIED`) | Change list with significance ratings | Change log table + risk highlights + next actions |
| **Compliance Check** | 2 | Requirement-by-requirement validation of a target against a reference standard | Compliance findings with status (`COMPLIANT` / `DEVIATION` / `MISSING`) | Compliance matrix (✅/⚠️/❌) + remediation plan |
| **Document Pack** | 2+ | Completeness assessment, conflict detection, gap analysis across related documents | Pack analysis with conflicts, gaps, duplications | Completeness checklist + issue list + remediation actions |
| **Fact Extraction** | 1+ | Extract all key facts into a master table, cross-check consistency | Fact table with cross-document discrepancies | Fact summary table + discrepancy report + data quality assessment |
| **Executive Summary** | 1+ | Theme identification, criticality assessment, new/changed items | Key findings with category and importance | Executive overview bullets + risk highlights + decisions required |

---

## Document Parsing

Vigil uses **Python libraries** for document parsing:

- **PyMuPDF** (with pdfplumber fallback) for PDF text extraction
- **python-docx** for Word documents (paragraphs + tables)
- **openpyxl** for Excel spreadsheets (all sheets)
- **Azure AI Document Intelligence OCR** for scanned PDFs and images (PNG, JPG, TIFF, BMP)

Text-based formats work out of the box with no Azure services required. Set `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` to enable OCR for scanned documents.

### Supported File Formats

| Format | Extension(s) | Parser | What's extracted |
|--------|-------------|--------|------------------|
| **PDF** | `.pdf` | PyMuPDF → pdfplumber → Document Intelligence OCR | Embedded text; OCR for scanned PDFs |
| **Word** | `.docx` | python-docx | All paragraphs + table content |
| **Excel** | `.xlsx`, `.xls` | openpyxl | All sheets, rows and tables |
| **Plain text** | `.txt` | Built-in UTF-8 decode | Full text content |
| **Images** | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp` | Azure AI Document Intelligence OCR | Text from scans and photos |

> **Note:** Document Intelligence is optional. If it is not configured, Vigil will still work for all text-based documents using Python libraries. Scanned files will return a placeholder message.

### Parser Resilience

Each parser catches all exceptions (not just `ImportError`). If a file is corrupted or unreadable:

- The upload endpoint returns **partial results** — successfully parsed files are included alongside error details.
- The frontend shows a styled error banner for any files that failed to parse.
- The pipeline continues with whatever documents were successfully parsed.

### Large Document Processing (Chunking + Azure AI Search)

For documents exceeding ~30 pages (~15,000 words), Vigil automatically switches to a **chunked processing pipeline**:

```
200-page PDF
    │
    ▼
  Doc Parser (Python libraries + OCR)
    │ extract text, tables
    ▼
  Chunker (chunker.py)
    │ split into ~4,000-word chunks with 200-word overlap
    ▼
  ┌─────────────────────────────────────────────┐
  │  Concurrent chunk processing (max 3 parallel) │
  │  Chunk 1 → Indexer thread → facts JSON       │
  │  Chunk 2 → Indexer thread → facts JSON       │
  │  Chunk 3 → Indexer thread → facts JSON       │
  │  ...                                          │
  └─────────────┬───────────────────────────────┘
                │ merge + deduplicate
                ▼
         Unified fact sheet
                │
    ┌───────────┼──────────────┐
    │           │              │
    ▼           ▼              ▼
 Analyzer    (same as      Advisor
 (unchanged)  small docs)  (unchanged)
```

**How it works:**

1. **Automatic detection** — If any uploaded document exceeds 15,000 words, the chunked path is activated.
2. **Chunking** — The document is split into ~4,000-word chunks with 200-word overlap at boundaries to preserve context.
3. **Concurrent extraction** — Each chunk is sent to the Indexer agent in a separate thread, with up to 3 running concurrently (bounded by a semaphore to avoid rate limits).
4. **Merge & deduplication** — Extracted facts from all chunks are merged into a single fact sheet. Facts are deduplicated by `(category, label, value)`. Document metadata (title, type, version) is taken from the first chunk that provides it.
5. **Azure AI Search indexing** (optional) — If `AZURE_SEARCH_ENDPOINT` is configured, chunks are indexed in a `vigil-document-chunks` Search index. The follow-up chat uses semantic search over these chunks to retrieve relevant sections when answering questions.
6. **Downstream pipeline unchanged** — The Analyzer and Advisor receive the same merged fact sheet JSON as they would from a small document.

**Cost comparison for a 200-page document (~60K words):**

| Approach | Indexer tokens | Quality | Speed |
|----------|:-:|:-:|:-:|
| Full text (single call) | ~85K input | Degraded ("lost in the middle") | ~60s |
| Chunked (15 × 4K-word chunks) | ~90K input total | High (focused attention per chunk) | ~30s (parallel) |

> **Note:** Chunking is fully automatic and requires no configuration. Small documents (< 15K words) always use the fast single-call path. The chunking threshold and chunk size can be adjusted via environment variables (`LARGE_DOC_THRESHOLD`, `CHUNK_SIZE`, `CHUNK_OVERLAP`).

### Gap Analysis Rulesets (Optional)

Vigil includes an optional **deterministic YAML rule engine** that runs between the Indexer and Analyzer stages for `compliance_check` and `document_pack` workflows. Rules provide guaranteed, repeatable checks that complement the LLM's analysis — they will always flag a missing document or a number mismatch, regardless of prompt complexity.

**Rulesets are NOT loaded by default.** To enable, set `GAP_ANALYSIS_RULESET` in your `.env`:

```bash
GAP_ANALYSIS_RULESET=rulesets/default.yaml  # example rules
```

Rule types: `required_document`, `required_field`, `cross_check`, `condition`. See [`rulesets/default.yaml`](rulesets/default.yaml) for the DSL reference and examples. Copy and customize for your domain.

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| **AI Model** | GPT-4.1-mini (Indexer, Analyzer) + GPT-4.1 (Advisor) via Azure AI Foundry Agent Service | Mini for fast structured JSON extraction; full model for report quality. Streaming advisor output. |
| **Agent SDK** | `azure-ai-agents` | Azure AI Agent Service SDK: create agents, threads, messages, runs |
| **Search** | Azure AI Search (semantic + keyword) | RAG grounding for follow-up chat on large (200+ page) documents |
| **Doc parsing** | PyMuPDF, pdfplumber, python-docx, openpyxl | Text and table extraction from PDF, DOCX, XLSX, TXT |
| **OCR** | Azure AI Document Intelligence (prebuilt-layout) | OCR for scanned documents and images with table preservation |
| **Backend** | Python 3.10+ with aiohttp | Lightweight async web server, native asyncio support |
| **Auth** | `DefaultAzureCredential` (Entra ID) | No API keys in code; works with `az login`, managed identity, and service principals |
| **Frontend** | Vanilla HTML/CSS/JS | Zero build step, no node_modules, instant load; Remix Icons + marked.js for markdown |

---

## Project Structure

```
vigil-document-analyst/
├── app.py                  # Web server entry point & app factory (aiohttp)
├── middleware.py            # Security headers middleware (CSP, CORS, X-Frame-Options)
├── foundry_client.py       # Shared AgentsClient singleton (DefaultAzureCredential)
├── doc_parser.py           # Document parsing
│                           #   - Python libraries (PyMuPDF, python-docx, openpyxl)
│                           #   - OCR: Azure AI Document Intelligence
├── chunker.py              # Large document chunking
│                           #   - Auto-detects docs > 15K words
│                           #   - Splits into ~4K-word overlapping chunks
├── search_client.py        # Azure AI Search integration
│                           #   - Chunk index creation + upload for follow-up chat RAG
│                           #   - Semantic + keyword search over document chunks
├── routes/
│   ├── __init__.py         # Shared config, validation constants, job store
│   ├── upload.py           # POST /api/upload — file upload & document parsing
│   ├── pipeline.py         # POST /api/run, GET /api/job — 3-agent pipeline orchestration
│   └── chat.py             # POST /api/chat — follow-up conversation with RAG
├── agents/
│   ├── __init__.py         # Agent registry: find-or-create on startup
│   ├── indexer.py          # Agent 1 — Fact extraction → structured JSON
│   ├── analyzer.py         # Agent 2 — 5 workflow modes → analysis JSON
│   └── advisor.py          # Agent 3 — Analysis → markdown report
├── static/
│   ├── index.html          # Single-page app (5 step pages + modals + tour)
│   ├── style.css           # Light professional theme
│   └── app.js              # Frontend logic, i18n (EN/PL), agent modals
├── agent.yaml              # Foundry agent manifest (hosted deployment)
├── Dockerfile              # Container image for deployment
├── .env.template           # Environment variable reference
├── requirements.txt        # Python dependencies
├── DEMO_SCRIPT.md          # Demo walkthrough script
├── LICENSE                 # MIT license
├── restart.ps1             # Recreate Azure resources after stop
└── stop.ps1                # Delete expensive resources (model deployment + search)
```

---

## Prerequisites

- **Python 3.10+**
- **Azure CLI** — logged in (`az login`)
- **Azure Subscription** with the following resources:

| Resource | Required | Purpose |
|----------|:--------:|---------|
| Azure AI Services (Cognitive Services) | ✅ | Hosts the GPT-4.1 model deployment + Foundry Agent Service |
| Azure AI Search (Basic tier) | Optional | Semantic search for follow-up chat RAG on large (200+ page) documents |
| Azure AI Document Intelligence | Optional | OCR for scanned PDFs and images |

### Azure RBAC Permissions

Your identity (or service principal) needs these roles:

| Role | Scope | Why |
|------|-------|-----|
| `Azure AI Developer` | Foundry project | Agent and thread operations |
| `Azure AI User` | AI Services resource | Agent create/run |
| `Cognitive Services OpenAI Contributor` | AI Services resource | Chat completions model access |
| `Search Index Data Contributor` | AI Search resource | Read/write document index (if using search) |
| `Search Service Contributor` | AI Search resource | Create/manage search indexes (if using search) |

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/<your-org>/vigil-document-analyst.git
cd vigil-document-analyst
cp .env.template .env
# Edit .env with your Azure endpoints (see Environment Variables below)
```

### 2. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

### 3. Login to Azure

```bash
az login --tenant <your-tenant>
```

### 4. Run

```bash
python app.py
```

Open **http://localhost:3000** in your browser.

On first launch, the app will register three agents in Azure AI Foundry Agent Service. Subsequent launches reuse existing agents automatically.

---

## Environment Variables

Copy `.env.template` to `.env` and fill in your values:

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | ✅ | — | Your Foundry project endpoint (e.g., `https://<resource>.services.ai.azure.com/api/projects/<project>`) |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME` | — | `gpt-4.1` | Default model deployment name (used by Advisor) |
| `FOUNDRY_INDEXER_MODEL` | — | `gpt-4.1-mini` | Model for Agent 1 (Indexer). Uses mini for speed — structured JSON output |
| `FOUNDRY_ANALYZER_MODEL` | — | `gpt-4.1-mini` | Model for Agent 2 (Analyzer). Uses mini for speed — structured JSON output |
| `FOUNDRY_ADVISOR_MODEL` | — | `gpt-4.1` | Model for Agent 3 (Advisor). Uses full model for report quality |
| `AZURE_SEARCH_ENDPOINT` | — | — | Azure AI Search endpoint URL (used for follow-up chat RAG on large documents). Optional — app works without it |
| `AZURE_SEARCH_CHUNKS_INDEX` | — | `vigil-document-chunks` | Name of the chunks index for RAG |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | — | — | Document Intelligence endpoint for OCR on scanned documents. Falls back to `FOUNDRY_PROJECT_ENDPOINT` |
| `VIGIL_PORT` | — | `3000` | Local server port |
| `VIGIL_ALLOWED_ORIGINS` | — | — | Comma-separated CORS allowed origins (e.g., `https://your-app.azurewebsites.net`). Empty = deny all cross-origin |
| `LARGE_DOC_THRESHOLD` | — | `15000` | Word count above which chunked processing is used |
| `CHUNK_SIZE` | — | `4000` | Words per chunk for large document processing |
| `CHUNK_OVERLAP` | — | `200` | Word overlap between consecutive chunks |
| `MAX_CONCURRENT_CHUNKS` | — | `5` | Max parallel chunk processing threads for large documents |
| `GAP_ANALYSIS_RULESET` | — | — | Path to a YAML ruleset for deterministic gap analysis (e.g., `rulesets/default.yaml`). Not loaded by default — see [Gap Analysis Rulesets](#gap-analysis-rulesets-optional) |

---

## Usage

### Step-by-Step

1. **Home** — Browse the five capabilities, read about the three agents. An interactive guided tour starts on first visit.
2. **Upload** — Drag & drop files or click to browse. Supported: PDF, DOCX, TXT, XLSX, PNG, JPG, TIFF, BMP. Documents are parsed via Python libraries (PyMuPDF, python-docx, openpyxl) with Document Intelligence OCR for scans.
3. **Workflow** — Select one of five analysis types. Optionally add custom instructions (e.g., "Focus on financial impact").
4. **Processing** — Watch the three-stage pipeline execute in real time: Indexer → Analyzer → Advisor.
5. **Results** — Read the Advisor's markdown report. Switch tabs to inspect raw Indexer JSON and Analyzer JSON. Use the follow-up chat to ask questions about the results.

### Example Scenarios

| Scenario | Documents to upload | Workflow |
|----------|-------------------|----------|
| Contract version diff | Two versions of the same contract | Version Comparison |
| NDA compliance audit | An NDA + corporate NDA template | Compliance Check |
| Submission pack review | SOW + Risk Register + Budget | Document Pack |
| Financial cross-check | SOW + Budget breakdown | Fact Extraction |
| Policy update summary | An updated policy document | Executive Summary |
| Scanned contract analysis | Scanned PDF or photo of a contract | Executive Summary |

### Follow-up Chat

After the pipeline completes, a chat interface appears below the results. You can ask:

- *"Explain the change in Article 3 in more detail"*
- *"What are the financial implications of the new pricing?"*
- *"Draft an email summarizing the key risks for the legal team"*
- *"Compare only the liability clauses"*

The chat includes full context from all three agents (Indexer, Analyzer, Advisor) so it can reference specific facts and findings. Context is automatically truncated for large analyses to stay within model token limits.

### Language Support

Toggle between English and Polish using the flag dropdown in the top-right corner. When set to Polish:

- All UI text, labels, and navigation are in Polish
- Agent prompts include instructions to output in Polish
- Generated reports (Indexer JSON values, Analyzer findings, Advisor markdown) are in Polish
- Follow-up chat responses are in Polish

---

## Azure Resource Setup

If you need to create the Azure resources from scratch:

```bash
# Create resource group
az group create --name vigil-demo-rg --location eastus2

# Register required providers
az provider register --namespace Microsoft.CognitiveServices --wait
az provider register --namespace Microsoft.Search --wait

# Create AI Services with custom subdomain (required for DefaultAzureCredential token auth)
az cognitiveservices account create \
  --name vigil-ai-services \
  --resource-group vigil-demo-rg \
  --location eastus2 \
  --kind AIServices \
  --sku S0 \
  --custom-domain vigil-ai-services \
  --yes

# Deploy GPT-4.1 (used by Advisor agent)
az cognitiveservices account deployment create \
  --name vigil-ai-services \
  --resource-group vigil-demo-rg \
  --deployment-name gpt-4.1 \
  --model-name gpt-4.1 \
  --model-version "2025-04-14" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name GlobalStandard

# Deploy GPT-4.1-mini (used by Indexer and Analyzer agents)
az cognitiveservices account deployment create \
  --name vigil-ai-services \
  --resource-group vigil-demo-rg \
  --deployment-name gpt-4.1-mini \
  --model-name gpt-4.1-mini \
  --model-version "2025-04-14" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name GlobalStandard

# Create Azure AI Search (Basic tier with semantic search)
az search service create \
  --name vigil-search-std \
  --resource-group vigil-demo-rg \
  --location eastus2 \
  --sku basic \
  --semantic-search free

# Assign RBAC roles to your identity
PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)
AI_RESOURCE_ID=$(az cognitiveservices account show \
  --name vigil-ai-services --resource-group vigil-demo-rg --query id -o tsv)
SEARCH_RESOURCE_ID=$(az search service show \
  --name vigil-search-std --resource-group vigil-demo-rg --query id -o tsv)

az role assignment create \
  --role "Azure AI Developer" --assignee $PRINCIPAL_ID --scope $AI_RESOURCE_ID
az role assignment create \
  --role "Cognitive Services OpenAI Contributor" --assignee $PRINCIPAL_ID --scope $AI_RESOURCE_ID
az role assignment create \
  --role "Search Index Data Contributor" --assignee $PRINCIPAL_ID --scope $SEARCH_RESOURCE_ID
az role assignment create \
  --role "Search Service Contributor" --assignee $PRINCIPAL_ID --scope $SEARCH_RESOURCE_ID
```

---

## Cost Management

Azure AI Search (Basic tier) costs ~$75/month even when idle. Use the included scripts to stop/start resources:

```powershell
# Stop everything (deletes model deployment + search service)
.\stop.ps1

# Restart (recreates model deployment + search service, ~3 min)
.\restart.ps1
```

The AI Services account itself is free when idle (no deployment). Only the model deployment and search service incur costs.

---

## Design Decisions & Best Practices

### Single-client pattern
All agent operations use a **single `AgentsClient`** singleton (`foundry_client.py`), authenticated via `DefaultAzureCredential`. This follows the Azure AI Agent Service best practice of sharing one client instance across all agent runtime operations (create, list, threads, messages, runs) for connection pooling and consistent auth handling.

### Agent registration separated from invocation
Agents are registered once at startup (`ensure_agents()`) and reused across requests. This follows the hackathon best practice: agent registration in a deployment pipeline, agent invocation at runtime. The `find-or-create` pattern means re-deploying the app doesn't create duplicate agents.

### Sequential pipeline with strict contracts
The three agents run in strict sequence (Indexer → Analyzer → Advisor) because each stage depends on the previous. Agent 1 and Agent 2 output **structured JSON** — not free-text — creating explicit contracts between pipeline stages that are auditable, testable, and composable.

### Input validation at system boundaries
All API endpoints validate inputs: workflow whitelist, language whitelist, message length caps (10K chars), and chat history limits (30 entries). This prevents prompt injection, token exhaustion, and malformed requests from reaching the LLM.

### Job memory management
The in-memory job store has a **TTL of 1 hour** and a **max capacity of 100 jobs**. Expired and overflow jobs are cleaned up before each new job creation. This prevents unbounded memory growth in a long-running server.

### Automatic chunking for large documents
Documents over ~30 pages are automatically split into overlapping chunks and processed concurrently. This avoids "lost in the middle" quality degradation, keeps token costs bounded, and enables parallel processing for faster results. The chunking threshold and chunk size are configurable via environment variables. If Azure AI Search is available, chunks are indexed for semantic retrieval in follow-up chat.

### Context truncation for chat
Follow-up chat context is **truncated** (stage outputs to 8K chars, final report to 12K chars) to prevent exceeding model token limits on large document analyses. For chunked jobs, the chat handler also queries Azure AI Search for relevant document sections, providing focused context even for 200+ page documents.

### Graceful error handling
- **Document parsing** catches all exceptions per-file, returning partial results + error details to the frontend.
- **Agent JSON parse failures** return a consistent `{"error": "..."}` field so the pipeline detects and reports failures cleanly instead of silently passing broken data downstream.
- **The Advisor agent** wraps its run in try/except and returns markdown-formatted error messages instead of crashing.

### DefaultAzureCredential everywhere
No API keys in code. Azure AI Foundry Agent Service and (optionally) Azure AI Search all authenticate via `DefaultAzureCredential`. This works with `az login` locally, managed identity in containers, and service principals in CI/CD.

---

## Security

| Concern | How it's handled |
|---------|-----------------|
| **Secrets in code** | None. All credentials via `DefaultAzureCredential` (Entra ID tokens). `.env` is gitignored |
| **Azure AI Search auth** | RBAC-only via `DefaultAzureCredential`. Assign "Search Index Data Contributor" role to your identity |
| **Security headers** | CSP, X-Frame-Options (DENY), X-Content-Type-Options, Referrer-Policy, Permissions-Policy on all responses |
| **CORS** | Denied by default. Configure `VIGIL_ALLOWED_ORIGINS` for cross-origin access |
| **File upload** | 50 MB limit server-side. File extension allowlist enforced (PDF, DOCX, TXT, XLSX, PNG, JPG, TIFF, BMP). Only text extracted — no code execution |
| **Input validation** | Workflow and language whitelisted. Job IDs validated against `^[a-f0-9\-]{1,36}$`. Chat messages capped at 10K chars. History capped at 30 entries |
| **Error sanitization** | Internal errors logged server-side; only generic messages returned to clients |
| **OData injection** | Search filter `job_id` values sanitized to alphanumeric + hyphens |
| **Context injection** | Agent prompts use structured formats; user input isolated in designated fields |
| **Job isolation** | Each pipeline run creates a new Foundry thread — no cross-request data leakage |

---

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `FOUNDRY_PROJECT_ENDPOINT must be set` | Missing `.env` file or env var | Copy `.env.template` to `.env` and fill in your Foundry project endpoint |
| `DefaultAzureCredential failed` | Not logged in to Azure CLI | Run `az login --tenant <your-tenant>` |
| `Agent run failed: 404` | Model deployment doesn't exist | Deploy GPT-4.1 via `az cognitiveservices account deployment create` (see [Azure Resource Setup](#azure-resource-setup)) |
| `Indexer returned no documents` | Token limit exceeded or malformed input | Try smaller documents or enable chunked processing by lowering `LARGE_DOC_THRESHOLD` |
| `Chunk search failed` | Azure AI Search not configured or index missing | Set `AZURE_SEARCH_ENDPOINT` in `.env` — the chunks index is auto-created on first large document upload |
| `Search index not found` | Search service was deleted by `stop.ps1` | Run `.\restart.ps1` to recreate the search service |
| `OCR requires AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Scanned PDF uploaded without Document Intelligence OCR configured | Set `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` in `.env`, or use text-based PDFs |
| `DOCX/XLSX parsing error` | Corrupted or password-protected file | Re-save the file in a supported format without password protection |
| App hangs on startup | Foundry endpoint unreachable or credential issue | Check network connectivity and ensure `az account get-access-token` succeeds |
| `stop.ps1` doesn't stop the app | App not running on port 3000 | Stop the process manually via Task Manager, or run `Get-Process python \| Stop-Process` |

### Resetting Agents

Vigil agents persist in Azure AI Foundry between app restarts. To force a clean re-registration:

1. Go to the [Azure AI Foundry portal](https://ai.azure.com) → your project → **Agents**
2. Delete the three agents: `vigil-indexer`, `vigil-analyzer`, `vigil-advisor`
3. Restart the app — new agents will be created automatically

---

## Performance

Approximate processing times (GPT-4.1, 10 TPM capacity):

| Document size | Chunked? | Indexer | Analyzer | Advisor | Total |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 pages (~2K words) | No | ~10s | ~10s | ~10s | **~30s** |
| 30 pages (~15K words) | No | ~25s | ~15s | ~15s | **~55s** |
| 100 pages (~50K words) | Yes (13 chunks) | ~25s | ~15s | ~15s | **~55s** |
| 200 pages (~100K words) | Yes (25 chunks) | ~40s | ~20s | ~15s | **~75s** |

> **Note:** Times vary based on model load, document complexity, and Azure region latency. Chunked processing runs up to 5 chunks concurrently — configurable via `MAX_CONCURRENT_CHUNKS`. The chunking threshold and chunk size can also be adjusted via `LARGE_DOC_THRESHOLD`, `CHUNK_SIZE`, and `CHUNK_OVERLAP`.

### Cost Estimates

| Component | Cost driver | Approximate cost |
|-----------|-----------|----------|
| **GPT-4.1** | Token usage (~100K tokens per 100-page analysis) | ~$0.50–$1.00 per run |
| **Azure AI Search (Basic)** | Fixed monthly | ~$75/month (use `stop.ps1` when idle) |
| **Document Intelligence OCR** | Per page processed | ~$0.01 per page (scanned docs only) |
| **AI Services account** | Free when no deployment | $0 when idle |

---

## License

MIT

---

## Contributing

This is a demo/POC project. Contributions welcome — please open an issue first to discuss proposed changes.

---

## Production Deployment

### Deploy to Azure Container Apps

Vigil ships with a production-ready `Dockerfile`. To deploy to Azure Container Apps:

```bash
# Build and push to Azure Container Registry
az acr create --name vigilacr --resource-group vigil-demo-rg --sku Basic
az acr build --registry vigilacr --image vigil:latest .

# Create Container Apps environment
az containerapp env create \
  --name vigil-env \
  --resource-group vigil-demo-rg \
  --location eastus2

# Deploy with managed identity
az containerapp create \
  --name vigil-app \
  --resource-group vigil-demo-rg \
  --environment vigil-env \
  --image vigilacr.azurecr.io/vigil:latest \
  --target-port 3000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1.0 --memory 2.0Gi \
  --env-vars \
    FOUNDRY_PROJECT_ENDPOINT=<your-endpoint> \
    FOUNDRY_MODEL_DEPLOYMENT_NAME=gpt-4.1 \
    AZURE_SEARCH_ENDPOINT=<your-search-endpoint> \
  --registry-server vigilacr.azurecr.io \
  --system-assigned

# Assign RBAC to the managed identity
IDENTITY_PRINCIPAL=$(az containerapp show --name vigil-app --resource-group vigil-demo-rg --query identity.principalId -o tsv)

az role assignment create --role "Azure AI Developer" --assignee $IDENTITY_PRINCIPAL --scope $AI_RESOURCE_ID
az role assignment create --role "Cognitive Services OpenAI Contributor" --assignee $IDENTITY_PRINCIPAL --scope $AI_RESOURCE_ID
az role assignment create --role "Search Index Data Contributor" --assignee $IDENTITY_PRINCIPAL --scope $SEARCH_RESOURCE_ID
az role assignment create --role "Search Service Contributor" --assignee $IDENTITY_PRINCIPAL --scope $SEARCH_RESOURCE_ID
```

### Scaling Considerations

| Concern | Current (Demo) | Production Recommendation |
|---------|---------------|---------------------------|
| **Job store** | In-memory dict (100 jobs, 1h TTL) | Replace with Azure Redis Cache or Cosmos DB for persistence across replicas |
| **Concurrency** | Single-process aiohttp | Container Apps auto-scaling (1–5+ replicas) handles horizontal scale; each replica runs independently |
| **Model throughput** | 10 TPM (tokens per minute) | Increase model deployment capacity (`--sku-capacity`) or use provisioned throughput for guaranteed latency |
| **File storage** | Uploaded files kept in-memory only | Add Azure Blob Storage for durable document storage and support for larger files |
| **Rate limits** | Exponential backoff with 4 retries | Increase `MAX_CONCURRENT_CHUNKS` and model quota together; add request queuing for burst traffic |
| **Authentication** | None (open localhost) | Add Azure Entra ID (AAD) authentication via Easy Auth on Container Apps, or add an API key middleware |
| **Monitoring** | Console logging only | Enable Azure Application Insights via `opencensus-ext-azure` or OpenTelemetry for tracing, metrics, and alerting |

---

## Upgrading Document Parsing

Vigil uses Python libraries for document parsing by default. For production workloads with complex document layouts (multi-column PDFs, embedded tables, scanned documents with figures), consider upgrading to **Azure AI Content Understanding**:

| Aspect | Python Libraries (default) | Azure AI Content Understanding |
|--------|---------------------------|-------------------------------|
| **Tables** | Basic pipe-separated text | Structured markdown tables with headers |
| **Figures/charts** | Not extracted | Captions and descriptions extracted |
| **Scanned PDFs** | Requires separate Document Intelligence OCR | Native multi-modal OCR built-in |
| **Scientific notation** | OCR may flatten superscripts (e.g., 10³ → 103) | Better preservation of formatting |
| **API calls** | One library call per format | Single API call for all formats (`prebuilt-layout` analyzer) |
| **Cost** | Free (local Python) | ~$0.01 per page |

To implement: replace the `parse_document()` function in `doc_parser.py` with a Content Understanding API call using the `prebuilt-layout` analyzer. The response includes structured `contents` with markdown text, tables, and figure descriptions. Set a `AZURE_CONTENT_UNDERSTANDING_ENDPOINT` environment variable and fall back to Python libraries when not configured.

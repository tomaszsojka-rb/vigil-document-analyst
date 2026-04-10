"""
Document parser — extracts text and tables from documents.

Uses Python libraries (PyMuPDF, python-docx, openpyxl) for text-based formats
and Azure AI Document Intelligence OCR for scanned documents and images.

Performance: files are parsed concurrently during upload.
"""

import io
import logging
import os

logger = logging.getLogger("vigil.doc_parser")

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tiff", "tif", "bmp"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_document(filename: str, content_bytes: bytes) -> str:
    """Parse a document file and return its text content.

    Uses Python libraries for text-based formats and Azure AI Document
    Intelligence OCR for scanned documents and images.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "txt":
        return content_bytes.decode("utf-8", errors="replace")
    elif ext == "pdf":
        return _parse_pdf(content_bytes)
    elif ext == "docx":
        return _parse_docx(content_bytes)
    elif ext in ("xlsx", "xls"):
        return _parse_xlsx(content_bytes)
    elif ext in IMAGE_EXTENSIONS:
        return _ocr_with_document_intelligence(content_bytes, filename)
    else:
        # Try as plain text
        return content_bytes.decode("utf-8", errors="replace")


# --- PDF (PyMuPDF / pdfplumber) ---

def _parse_pdf(data: bytes) -> str:
    """Extract text from PDF. Falls back to Azure Document Intelligence OCR
    if the PDF appears to be a scan (very little embedded text)."""
    text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=data, filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        text = "\n".join(parts)
    except ImportError:
        logger.warning("PyMuPDF not installed — trying pdfplumber")
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            pass
        except Exception as exc:
            logger.error("pdfplumber failed: %s", exc)
    except Exception as exc:
        logger.error("PyMuPDF failed: %s", exc)

    # If we got very little text, it's likely a scanned PDF — try OCR
    stripped = text.strip()
    if len(stripped) < 50:
        logger.info("PDF has little embedded text (%d chars) — running Azure OCR", len(stripped))
        ocr_text = _ocr_with_document_intelligence(data, "document.pdf")
        if ocr_text and not ocr_text.startswith("["):
            return ocr_text

    return text if text.strip() else "[No text could be extracted from this PDF]"


# --- DOCX (python-docx) ---

def _parse_docx(data: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                paragraphs.append(" | ".join(cells))
        return "\n".join(paragraphs)
    except ImportError:
        return "[DOCX parsing requires python-docx]"
    except Exception as exc:
        logger.error("DOCX parsing failed: %s", exc)
        return f"[DOCX parsing error: {exc}]"


# --- XLSX (openpyxl) ---

def _parse_xlsx(data: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        lines = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            lines.append(f"=== Sheet: {sheet_name} ===")
            for row in ws.iter_rows(values_only=True):
                vals = [str(c) if c is not None else "" for c in row]
                if any(v.strip() for v in vals):
                    lines.append(" | ".join(vals))
        return "\n".join(lines)
    except ImportError:
        return "[XLSX parsing requires openpyxl]"
    except Exception as exc:
        logger.error("XLSX parsing failed: %s", exc)
        return f"[XLSX parsing error: {exc}]"


# ---------------------------------------------------------------------------
# Azure AI Document Intelligence OCR (scanned PDFs and images)
# ---------------------------------------------------------------------------

# Cached OCR client (initialized lazily, thread-safe for concurrent uploads)
_ocr_client = None


def _get_ocr_client():
    """Return a cached DocumentIntelligenceClient, or None if not configured."""
    global _ocr_client
    if _ocr_client is not None:
        return _ocr_client

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.identity import DefaultAzureCredential

        endpoint = os.getenv(
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
            os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""),
        )
        if not endpoint:
            return None

        _ocr_client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=DefaultAzureCredential()
        )
        logger.info("OCR client initialized for %s", endpoint)
        return _ocr_client
    except ImportError:
        logger.warning("azure-ai-documentintelligence not installed")
        return None


def _ocr_with_document_intelligence(data: bytes, filename: str) -> str:
    """Extract text from a scanned document or image using Azure AI Document Intelligence."""
    try:
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        client = _get_ocr_client()
        if not client:
            return "[OCR requires AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT to be set]"

        poller = client.begin_analyze_document(
            "prebuilt-layout",
            AnalyzeDocumentRequest(bytes_source=data),
        )
        result = poller.result()

        # prebuilt-layout returns structured content with tables as markdown
        if hasattr(result, "content") and result.content:
            text = result.content
            logger.info("Azure OCR (layout) extracted %d chars from %s", len(text), filename)
            return text if text.strip() else "[OCR completed but no text was detected]"

        # Fallback: extract line-by-line from pages
        pages_text = []
        for page in result.pages:
            lines = [line.content for line in (page.lines or [])]
            pages_text.append("\n".join(lines))

        text = "\n\n".join(pages_text)
        logger.info("Azure OCR (layout/lines) extracted %d chars from %s", len(text), filename)
        return text if text.strip() else "[OCR completed but no text was detected]"

    except ImportError:
        logger.warning("azure-ai-documentintelligence not installed")
        return "[OCR requires azure-ai-documentintelligence package]"
    except Exception as e:
        logger.error("Azure Document Intelligence OCR failed: %s", e)
        return f"[OCR failed: {e}]"

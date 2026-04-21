/* ═══════════════════════════════════════════════════════
   Vigil — Document Analyst — v2 Frontend (EN/PL)
   ═══════════════════════════════════════════════════════ */

let currentStep = 0;
let selectedWorkflow = null;
let uploadedDocuments = [];
let currentUploadId = null;
let currentJobId = null;
let currentLang = localStorage.getItem("vigil-lang") || "en";
let chatHistory = [];
let chatAbortController = null;

// ═══ TRANSLATIONS ══════════════════════════════════════
const T = {
  en: {
    // Sidebar
    sidebar_home: "Home", sidebar_upload: "Upload", sidebar_workflow: "Workflow",
    sidebar_processing: "Processing", sidebar_results: "Results",
    // Hero
    hero_badge: "Multi-Agent AI Pipeline", hero_title_pre: "Meet ", hero_title_accent: "Vigil",
    hero_subtitle: "Upload enterprise documents — even 200+ page contracts — pick an analysis workflow, and let three specialized AI agents extract, analyze, and advise. Large documents are automatically chunked for quality.",
    hero_btn: "Get Started",
    // Capabilities
    cap_version_title: "Version Comparison", cap_version_desc: "Compare versions or variants of documents — track every change with exact source citations.",
    cap_compliance_title: "Compliance Check", cap_compliance_desc: "Check documents against references or standards. Finds deviations with exact clause citations.",
    cap_pack_title: "Document Pack", cap_pack_desc: "Analyze a document set for completeness, conflicts, and gaps — fully traceable to source.",
    cap_fact_title: "Fact Extraction", cap_fact_desc: "Extract all key facts with exact source file and section citations. Cross-check consistency.",
    cap_summary_title: "Executive Summary", cap_summary_desc: "Strategic overview with risk highlights — every finding traced to its source document and section.",
    cap_tag_1plus: "1+ documents",
    cap_tag_2: "2 documents",
    cap_tag_2plus: "2+ documents",
    // Agents section
    agents_title: "Meet the Agents",
    agents_intro: "Vigil uses a three-stage multi-agent pipeline. Each agent is a specialized LLM with tailored instructions, running on Azure AI Foundry. They communicate sequentially — the output of one becomes the input of the next — ensuring separation of concerns, auditability, and composability.",
    agent1_title: "Indexer & Extractor", agent1_desc: "Parses documents and extracts structured facts — dates, amounts, parties, obligations — into a JSON fact sheet. Automatically chunks large documents (200+ pages) for quality.",
    agent2_title: "Analyzer", agent2_desc: "Compares, checks compliance, cross-references facts, and identifies conflicts, gaps, and deviations.",
    agent3_title: "Advisor", agent3_desc: "Produces human-readable reports — executive summaries, risk highlights, remediation plans, and action items.",
    agent_view_details: "View details",
    // Upload page
    upload_title: "Upload Documents", upload_desc: "Upload the documents you want to analyze. Supported formats: PDF, DOCX, TXT, XLSX, PNG, JPG, TIFF, BMP.",
    upload_drop_title: "Drag & drop files here", upload_drop_sub: "or click to browse — up to 50 MB per file",
    upload_words: "words", upload_back: "Back", upload_next: "Choose Workflow",
    // Workflow page
    wf_title: "Select Analysis Workflow", wf_desc: "Choose what kind of analysis Vigil should perform on your documents.",
    wf_version_title: "Version Comparison", wf_version_desc: "Compare two versions and get a detailed change log with business impact ratings.",
    wf_compliance_title: "Compliance Check", wf_compliance_desc: "Check against a reference standard and get a compliance matrix with remediation plan.",
    wf_pack_title: "Document Pack Analysis", wf_pack_desc: "Analyze a document set for completeness, conflicts, duplications, and gaps.",
    wf_fact_title: "Fact Extraction & Cross-Check", wf_fact_desc: "Extract key facts and cross-check for inconsistencies across documents.",
    wf_summary_title: "Executive Summary", wf_summary_desc: "Generate a concise overview with risk highlights and recommended actions.",
    wf_run: "Run Analysis",
    // Processing page
    proc_title: "Agents Working", proc_desc: "Your documents are being processed through the three-stage AI pipeline.",
    proc_agent1: "Agent 1 — Indexer & Extractor", proc_agent1_desc: "Parsing documents, extracting facts…",
    proc_agent2: "Agent 2 — Analyzer", proc_agent2_desc: "Comparing, checking, cross-referencing…",
    proc_agent3: "Agent 3 — Advisor", proc_agent3_desc: "Generating report and recommendations…",
    // Results page
    res_title: "Analysis Results", res_desc: "All three agents have completed. Here's your report.",
    res_tab_report: "Final Report", res_tab_indexer: "Indexer Output", res_tab_analyzer: "Analyzer Output",
    res_new: "New Analysis", res_copy: "Copy Report", res_copied: "Copied!",
    res_export_pdf: "Export PDF", res_export_docx: "Export Word",
    res_exporting_pdf: "Exporting PDF…", res_exporting_docx: "Exporting Word…",
    res_no_report: "No report to export yet.",
    res_export_not_supported: "Export is not available in this browser.",
    res_export_failed: "Export failed. Please try again.",
    // Custom instructions + chat
    custom_label: "Custom Instructions", custom_optional: "(optional)",
    custom_placeholder: "Tell Vigil what to focus on, e.g. 'Pay special attention to liability clauses and payment terms'\u2026",
    chat_title: "Follow-up Chat", chat_desc: "Ask questions about the analysis, request more detail on specific findings, or explore further.",
    chat_placeholder: "Ask about the analysis results\u2026",
    // Workflow labels
    wfl_version_comparison: "Version Comparison", wfl_compliance_check: "Compliance Check",
    wfl_document_pack: "Document Pack Analysis", wfl_fact_extraction: "Fact Extraction",
    wfl_summary: "Executive Summary",
    // Log messages
    log_starting: "Starting {wf} with {n} document(s)…",
    log_job: "Job: {id}", log_working: "🤖 {agent} working…", log_done: "✅ {agent} done",
    log_all_done: "✅ All agents completed!", log_error: "❌ Error: {msg}",
    log_no_docs: "No documents!",
    // Tour
    tour_skip: "Skip tour", tour_back: "Back", tour_next: "Next", tour_finish: "Finish",
    tour: [
      { title: "Welcome to Vigil!", text: "This is the home page. You'll see Vigil's five analysis capabilities and the three AI agents that power them. Click any capability card to jump straight into a workflow, or follow the guided steps." },
      { title: "Meet the Agents", text: "Scroll down to see the three-agent pipeline. Click any agent card to read its full technical and business description — how it works, what it does, and why." },
      { title: "Upload Documents", text: "Here you upload your files (PDF, DOCX, TXT, XLSX, or scanned images like PNG, JPG, TIFF, BMP). Documents are parsed using Python libraries (PyMuPDF, python-docx, openpyxl), with Azure AI Document Intelligence OCR for scanned documents." },
      { title: "Choose a Workflow", text: "Select one of five analysis workflows. Each one configures the Analyzer and Advisor agents differently — version comparison produces change logs, compliance check produces matrices, etc." },
      { title: "Watch the Agents Work", text: "Once you start an analysis, you'll see real-time progress as each agent completes its stage. The pipeline flows: Indexer → Analyzer → Advisor." },
      { title: "Review Results", text: "The final report from the Advisor is shown here in rich markdown. You can also inspect the raw JSON output from the Indexer and Analyzer in the tabs above." },
    ],
    // Agent modals
    modal_biz: "Business Purpose", modal_tech: "Technical Details", modal_how: "How It Works",
    modal_modes: "Workflow Modes", modal_reports: "Report Sections", modal_principle: "Key Principle",
    agent_modal: {
      indexer: {
        title: "Agent 1 — Indexer & Fact Extractor",
        biz: "The Indexer is the foundation of every analysis. It converts unstructured document content into a structured, machine-readable format. All extracted data is automatically indexed in Azure AI Search, enabling instant semantic retrieval for the Analyzer and follow-up chat.",
        tech: "Uses the Indexer model (default: GPT-4.1-mini, configurable via FOUNDRY_INDEXER_MODEL) via direct Chat Completions (single HTTP call) for maximum speed. Parses PDF, DOCX, TXT, XLSX via Python libraries and Azure AI Document Intelligence OCR for scans. For large documents (200+ pages), text is split into ~4,000-word overlapping chunks processed concurrently. All facts, sections, and numbers are indexed in Azure AI Search (vigil-facts index). Raw document chunks are also indexed (vigil-document-chunks) for follow-up chat grounding.",
        how: ["Receives parsed text from all uploaded documents", "Single Chat Completions call per document", "For large docs: splits into chunks, processes concurrently", "Indexes structured facts in Azure AI Search (vigil-facts)", "Indexes raw document chunks in Azure AI Search (vigil-document-chunks)", "Outputs structured JSON fact sheet per document"],
        principle: "The Indexer only extracts facts explicitly stated in the document — it never infers or hallucinates. All extracted data is indexed in Azure AI Search for instant semantic retrieval.",
      },
      analyzer: {
        title: "Agent 2 — Analyzer",
        biz: "The Analyzer is the analytical engine. It receives a compact structured fact and number block plus focused Azure AI Search context, enabling faster analysis without dropping key extracted values. It performs comparison, compliance check, or cross-reference as requested.",
        tech: "Uses the Analyzer model (default: GPT-4.1-mini, configurable via FOUNDRY_ANALYZER_MODEL) via direct Chat Completions with a robust JSON parser that handles fences, extra data, and truncated output. Before analysis, the pipeline passes compact document summaries, the full structured facts and number registry from the Indexer, and focused Azure AI Search context from the vigil-facts index — reducing prompt size while preserving critical extracted data. Falls back to full Indexer JSON if Search is unavailable.",
        how: ["Receives document summaries plus the full structured fact and number registry", "Adds focused Azure AI Search context instead of relying on a raw JSON dump", "Version Comparison — side-by-side section diff with impact ratings", "Compliance Check — requirement-by-requirement validation matrix", "Document Pack — completeness, conflict, and gap analysis", "Fact Extraction — master fact table with cross-document discrepancies", "Summary — theme identification and criticality assessment"],
        principle: "The Analyzer classifies every finding with a severity rating (HIGH/MEDIUM/LOW) and always cites the specific section in each document. This makes its output auditable and actionable.",
      },
      advisor: {
        title: "Agent 3 — Advisor",
        biz: "The Advisor translates technical analysis into business-ready reports. It produces clear, executive-level markdown documents with tables, risk ratings, and prioritized action items — streamed in real-time as they're generated.",
        tech: "Uses the Advisor model (default: GPT-4.1, configurable via FOUNDRY_ADVISOR_MODEL) via direct Chat Completions with streaming output. Receives the Analyzer's JSON and generates a markdown report. Each workflow produces a different report format: change logs, compliance matrices, completeness checklists, fact sheets, or executive overviews. Reports stream to the UI in real-time.",
        how: ["Executive Summary — key findings for senior leadership", "Detailed Analysis — tables, matrices, or fact sheets depending on workflow", "Risk Highlights — severity-rated issues with 🔴🟡🟢 indicators", "Recommended Next Actions — numbered, prioritized steps to take"],
        principle: "The Advisor always separates facts from interpretation and recommendations. It cites specific document sections for every finding, making the report fully traceable back to source documents.",
      },
    },
  },
  pl: {
    sidebar_home: "Start", sidebar_upload: "Pliki", sidebar_workflow: "Analiza",
    sidebar_processing: "Przetwarzanie", sidebar_results: "Wyniki",
    hero_badge: "Wieloagentowy pipeline AI", hero_title_pre: "Poznaj ", hero_title_accent: "Vigil",
    hero_subtitle: "Prześlij dokumenty firmowe — nawet 200+ stron — wybierz rodzaj analizy, a trzy wyspecjalizowane agenty AI wyodrębnią dane, przeanalizują je i doradzą. Duże dokumenty są automatycznie dzielone na fragmenty.",
    hero_btn: "Rozpocznij",
    cap_version_title: "Porównanie wersji", cap_version_desc: "Porównaj wersje lub warianty dokumentów — śledź każdą zmianę z dokładnym źródłem.",
    cap_compliance_title: "Kontrola zgodności", cap_compliance_desc: "Sprawdź dokumenty względem wzorców lub standardów. Odchylenia z cytowaniem klauzul.",
    cap_pack_title: "Pakiet dokumentów", cap_pack_desc: "Analiza zestawu dokumentów pod kątem kompletności, konfliktów i braków — pełna identyfikowalność źródeł.",
    cap_fact_title: "Ekstrakcja faktów", cap_fact_desc: "Wyodrębnij kluczowe fakty z dokładnym wskazaniem pliku źródłowego i sekcji. Sprawdź spójność.",
    cap_summary_title: "Podsumowanie", cap_summary_desc: "Strategiczny przegląd z zagrożeniami — każde ustalenie powiązane z dokumentem źródłowym i sekcją.",
    cap_tag_1plus: "1+ dokumentów",
    cap_tag_2: "2 dokumenty",
    cap_tag_2plus: "2+ dokumentów",
    agents_title: "Poznaj agentów",
    agents_intro: "Vigil wykorzystuje trzyetapowy pipeline wieloagentowy. Każdy agent to wyspecjalizowany model LLM z dedykowanymi instrukcjami, działający na Azure AI Foundry. Komunikują się sekwencyjnie — wynik jednego staje się wejściem kolejnego — zapewniając rozdzielenie odpowiedzialności, audytowalność i modularnosć.",
    agent1_title: "Indekser i ekstraktor", agent1_desc: "Parsuje dokumenty i wyodrębnia strukturalne fakty — daty, kwoty, strony, zobowiązania — do arkusza faktów JSON. Automatycznie dzieli duże dokumenty (200+ stron) na fragmenty.",
    agent2_title: "Analizator", agent2_desc: "Porównuje, sprawdza zgodność, krzyżowo weryfikuje fakty i identyfikuje konflikty, braki i odchylenia.",
    agent3_title: "Doradca", agent3_desc: "Tworzy raporty czytelne dla biznesu — podsumowania, zagrożenia, plany naprawcze i listy działań.",
    agent_view_details: "Szczegóły",
    upload_title: "Prześlij dokumenty", upload_desc: "Prześlij dokumenty do analizy. Obsługiwane formaty: PDF, DOCX, TXT, XLSX, PNG, JPG, TIFF, BMP.",
    upload_drop_title: "Przeciągnij i upuść pliki tutaj", upload_drop_sub: "lub kliknij, aby przeglądać — do 50 MB na plik",
    upload_words: "słów", upload_back: "Wstecz", upload_next: "Wybierz analizę",
    wf_title: "Wybierz rodzaj analizy", wf_desc: "Wybierz, jaki rodzaj analizy Vigil ma przeprowadzić na Twoich dokumentach.",
    wf_version_title: "Porównanie wersji", wf_version_desc: "Porównaj dwie wersje i uzyskaj szczegółowy dziennik zmian z oceną wpływu biznesowego.",
    wf_compliance_title: "Kontrola zgodności", wf_compliance_desc: "Sprawdź zgodność ze standardem i uzyskaj matrycę zgodności z planem naprawczym.",
    wf_pack_title: "Analiza pakietu dokumentów", wf_pack_desc: "Przeanalizuj zestaw dokumentów pod kątem kompletności, konfliktów, duplikatów i braków.",
    wf_fact_title: "Ekstrakcja i weryfikacja faktów", wf_fact_desc: "Wyodrębnij kluczowe fakty i sprawdź niespójności między dokumentami.",
    wf_summary_title: "Podsumowanie wykonawcze", wf_summary_desc: "Wygeneruj zwięzły przegląd z zagrożeniami i rekomendowanymi działaniami.",
    wf_run: "Uruchom analizę",
    proc_title: "Agenty pracują", proc_desc: "Twoje dokumenty są przetwarzane przez trzyetapowy pipeline AI.",
    proc_agent1: "Agent 1 — Indekser i ekstraktor", proc_agent1_desc: "Parsowanie dokumentów, ekstrakcja faktów…",
    proc_agent2: "Agent 2 — Analizator", proc_agent2_desc: "Porównywanie, sprawdzanie, krzyżowa weryfikacja…",
    proc_agent3: "Agent 3 — Doradca", proc_agent3_desc: "Generowanie raportu i rekomendacji…",
    res_title: "Wyniki analizy", res_desc: "Wszystkie trzy agenty zakończyły pracę. Oto Twój raport.",
    res_tab_report: "Raport końcowy", res_tab_indexer: "Wynik indeksera", res_tab_analyzer: "Wynik analizatora",
    res_new: "Nowa analiza", res_copy: "Kopiuj raport", res_copied: "Skopiowano!",
    res_export_pdf: "Eksport PDF", res_export_docx: "Eksport Word",
    res_exporting_pdf: "Eksport PDF…", res_exporting_docx: "Eksport Word…",
    res_no_report: "Brak raportu do eksportu.",
    res_export_not_supported: "Eksport nie jest dostępny w tej przeglądarce.",
    res_export_failed: "Nie udało się wyeksportować raportu. Spróbuj ponownie.",
    custom_label: "Instrukcje dodatkowe", custom_optional: "(opcjonalnie)",
    custom_placeholder: "Powiedz Vigil, na czym si\u0119 skupi\u0107, np. \u2018Zwr\u00f3\u0107 szczeg\u00f3ln\u0105 uwag\u0119 na klauzule odpowiedzialno\u015bci i warunki p\u0142atno\u015bci\u2019\u2026",
    chat_title: "Czat uzupe\u0142niaj\u0105cy", chat_desc: "Zadawaj pytania o analiz\u0119, pro\u015b o wi\u0119cej szczeg\u00f3\u0142\u00f3w lub eksploruj dalej.",
    chat_placeholder: "Zapytaj o wyniki analizy\u2026",
    wfl_version_comparison: "Porównanie wersji", wfl_compliance_check: "Kontrola zgodności",
    wfl_document_pack: "Analiza pakietu dokumentów", wfl_fact_extraction: "Ekstrakcja faktów",
    wfl_summary: "Podsumowanie wykonawcze",
    log_starting: "Uruchamiam {wf} dla {n} dokumentu(-ów)…",
    log_job: "Zadanie: {id}", log_working: "🤖 {agent} pracuje…", log_done: "✅ {agent} zakończono",
    log_all_done: "✅ Wszystkie agenty zakończyły pracę!", log_error: "❌ Błąd: {msg}",
    log_no_docs: "Brak dokumentów!",
    tour_skip: "Pomiń przewodnik", tour_back: "Wstecz", tour_next: "Dalej", tour_finish: "Zakończ",
    tour: [
      { title: "Witaj w Vigil!", text: "To jest strona główna. Zobaczysz pięć możliwości analizy i trzech agentów AI, którzy je obsługują. Kliknij dowolną kartę, aby od razu przejść do analizy, lub podążaj za przewodnikiem." },
      { title: "Poznaj agentów", text: "Przewiń w dół, aby zobaczyć pipeline trzech agentów. Kliknij dowolną kartę agenta, aby przeczytać pełny opis techniczny i biznesowy — jak działa, co robi i dlaczego." },
      { title: "Prześlij dokumenty", text: "Tutaj przesyłasz pliki (PDF, DOCX, TXT, XLSX lub skany: PNG, JPG, TIFF, BMP). Dokumenty są przetwarzane przez biblioteki Python (PyMuPDF, python-docx, openpyxl), z Azure AI Document Intelligence OCR dla skanów." },
      { title: "Wybierz analizę", text: "Wybierz jeden z pięciu rodzajów analizy. Każdy rodzaj inaczej konfiguruje Analizatora i Doradcę — porównanie wersji tworzy dziennik zmian, kontrola zgodności tworzy matrycę itd." },
      { title: "Obserwuj agentów", text: "Po uruchomieniu analizy zobaczysz postęp w czasie rzeczywistym, gdy każdy agent ukończy swój etap. Pipeline: Indekser → Analizator → Doradca." },
      { title: "Przejrzyj wyniki", text: "Raport końcowy od Doradcy jest wyświetlany tutaj w formacie markdown. Możesz także sprawdzić surowe dane JSON z Indeksera i Analizatora w zakładkach powyżej." },
    ],
    modal_biz: "Cel biznesowy", modal_tech: "Szczegóły techniczne", modal_how: "Jak to działa",
    modal_modes: "Tryby analizy", modal_reports: "Sekcje raportu", modal_principle: "Kluczowa zasada",
    agent_modal: {
      indexer: {
        title: "Agent 1 — Indekser i ekstraktor faktów",
        biz: "Indekser jest fundamentem każdej analizy. Konwertuje nieustrukturyzowaną treść dokumentów na ustrukturyzowany format. Wszystkie wyodrębnione dane są automatycznie indeksowane w Azure AI Search, umożliwiając natychmiastowe wyszukiwanie semantyczne dla Analizatora i czatu.",
        tech: "Używa modelu Indexer (domyślnie: GPT-4.1-mini, konfigurowalne przez FOUNDRY_INDEXER_MODEL) przez bezpośrednie wywołanie Chat Completions (pojedyncze zapytanie HTTP) dla maksymalnej szybkości. Parsuje PDF, DOCX, TXT, XLSX bibliotekami Python i Azure AI Document Intelligence OCR dla skanów. Dla dużych dokumentów (200+ stron) tekst jest dzielony na fragmenty ~4000 słów przetwarzane równolegle. Wszystkie fakty, sekcje i liczby są indeksowane w Azure AI Search (indeks vigil-facts). Surowe fragmenty dokumentów również (vigil-document-chunks) dla czatu.",
        how: ["Otrzymuje sparsowany tekst ze wszystkich dokumentów", "Pojedyncze wywołanie Chat Completions na dokument", "Dla dużych dok.: dzieli na fragmenty, przetwarza równolegle", "Indeksuje fakty w Azure AI Search (vigil-facts)", "Indeksuje fragmenty dokumentów w Azure AI Search (vigil-document-chunks)", "Zwraca ustrukturyzowany arkusz faktów JSON"],
        principle: "Indekser wyodrębnia tylko fakty jawnie zawarte w dokumencie — nigdy nie wnioskuje ani nie halucynuje. Wszystkie dane są indeksowane w Azure AI Search dla natychmiastowego wyszukiwania semantycznego.",
      },
      analyzer: {
        title: "Agent 2 — Analizator",
        biz: "Analizator jest silnikiem analitycznym. Otrzymuje zwarty blok faktów i liczb oraz skoncentrowany kontekst z Azure AI Search, co przyspiesza analizę bez gubienia kluczowych danych wyodrębnionych przez Indexer. Przeprowadza porównanie, kontrolę zgodności lub krzyżową weryfikację.",
        tech: "Używa modelu Analyzer (domyślnie: GPT-4.1-mini, konfigurowalne przez FOUNDRY_ANALYZER_MODEL) przez bezpośrednie wywołanie Chat Completions z odpornym parserem JSON obsługującym markdown fences, dodatkowe dane i ucięty wynik. Przed analizą pipeline przekazuje zwarte podsumowania dokumentów, pełny rejestr faktów i liczb z Indexera oraz skoncentrowany kontekst z Azure AI Search (indeks vigil-facts) — redukując rozmiar prompta przy zachowaniu krytycznych danych.",
        how: ["Otrzymuje podsumowania dokumentów oraz pełny rejestr faktów i liczb", "Dodaje skoncentrowany kontekst z Azure AI Search zamiast polegać na pełnym zrzucie JSON", "Porównanie wersji — różnicowanie sekcja po sekcji z oceną wpływu", "Kontrola zgodności — matryca walidacji wymaganie po wymaganiu", "Pakiet dokumentów — analiza kompletności, konfliktów i braków", "Ekstrakcja faktów — główna tabela faktów z rozbieżnościami", "Podsumowanie — identyfikacja tematów i ocena krytyczności"],
        principle: "Analizator klasyfikuje każde znalezisko z oceną istotności (WYSOKA/ŚREDNIA/NISKA) i zawsze cytuje konkretne sekcje dokumentów.",
      },
      advisor: {
        title: "Agent 3 — Doradca",
        biz: "Doradca przekłada analizę techniczną na raporty gotowe dla biznesu. Tworzy czytelne dokumenty markdown z tabelami, ocenami ryzyka i priorytetyzowanymi działaniami — streamowane w czasie rzeczywistym.",
        tech: "Używa modelu Advisor (domyślnie: GPT-4.1, konfigurowalne przez FOUNDRY_ADVISOR_MODEL) przez bezpośrednie wywołanie Chat Completions ze streamingiem. Otrzymuje JSON z Analizatora i generuje raport markdown. Każdy workflow ma inny format raportu. Raporty są streamowane do UI w czasie rzeczywistym.",
        how: ["Podsumowanie wykonawcze — kluczowe ustalenia dla kadry zarządzającej", "Szczegółowa analiza — tabele, matryca lub arkusze w zależności od workflow", "Zagrożenia — problemy z oceną istotności 🔴🟡🟢", "Rekomendowane działania — ponumerowane, priorytetyzowane kroki"],
        principle: "Doradca zawsze oddziela fakty od interpretacji i rekomendacji. Cytuje konkretne sekcje dokumentów dla każdego ustalenia.",
      },
    },
  },
};

function t(key) { return T[currentLang]?.[key] || T.en[key] || key; }

// ═══ LANGUAGE TOGGLE ═══════════════════════════════════
function setLanguage(lang) {
  currentLang = lang;
  localStorage.setItem("vigil-lang", currentLang);
  document.getElementById("lang-dropdown").classList.remove("open");
  document.documentElement.lang = lang;
  applyLanguage();
}

// Close dropdown when clicking outside
document.addEventListener("click", e => {
  const dd = document.getElementById("lang-dropdown");
  if (dd && !dd.contains(e.target)) dd.classList.remove("open");
});

function applyLanguage() {
  const flag = document.getElementById("lang-flag");
  const label = document.getElementById("lang-label");
  if (flag) flag.textContent = currentLang === "en" ? "🇬🇧" : "🇵🇱";
  if (label) label.textContent = currentLang === "en" ? "English" : "Polski";

  // Sidebar
  document.querySelectorAll(".nav-btn .nav-label").forEach((el, i) => {
    const keys = ["sidebar_home", "sidebar_upload", "sidebar_workflow", "sidebar_processing", "sidebar_results"];
    el.textContent = t(keys[i]);
  });
  // Breadcrumb labels
  document.querySelectorAll(".step-box span:not(.step-icon)").forEach((el, i) => {
    const keys = ["sidebar_home", "sidebar_upload", "sidebar_workflow", "sidebar_processing", "sidebar_results"];
    if (keys[i]) el.textContent = t(keys[i]);
  });

  // Hero
  const heroContent = document.querySelector(".hero-content");
  if (heroContent) {
    heroContent.querySelector(".hero-badge").innerHTML = `<i class="ri-sparkling-2-fill"></i> ${t("hero_badge")}`;
    heroContent.querySelector("h1").innerHTML = `${t("hero_title_pre")}<span class="accent">${t("hero_title_accent")}</span>`;
    heroContent.querySelector(".hero-subtitle").textContent = t("hero_subtitle");
    heroContent.querySelector(".btn-hero").innerHTML = `${t("hero_btn")} <i class="ri-arrow-right-line"></i>`;
  }

  // Capability cards
  const capCards = document.querySelectorAll(".cap-card");
  const capKeys = [
    { title: "cap_version_title", desc: "cap_version_desc", tag: "cap_tag_2" },
    { title: "cap_compliance_title", desc: "cap_compliance_desc", tag: "cap_tag_2" },
    { title: "cap_pack_title", desc: "cap_pack_desc", tag: "cap_tag_2plus" },
    { title: "cap_fact_title", desc: "cap_fact_desc", tag: "cap_tag_1plus" },
    { title: "cap_summary_title", desc: "cap_summary_desc", tag: "cap_tag_1plus" },
  ];
  capCards.forEach((card, i) => {
    if (capKeys[i]) {
      card.querySelector("h3").textContent = t(capKeys[i].title);
      card.querySelector("p").textContent = t(capKeys[i].desc);
      card.querySelector(".cap-tag").textContent = t(capKeys[i].tag);
    }
  });

  // Agents section
  const agSec = document.querySelector(".agents-section");
  if (agSec) {
    agSec.querySelector("h2").innerHTML = `<i class="ri-robot-2-line"></i> ${t("agents_title")}`;
    agSec.querySelector(".agents-intro").textContent = t("agents_intro");
    const agCards = agSec.querySelectorAll(".agent-card");
    const agKeys = [
      { title: "agent1_title", desc: "agent1_desc" },
      { title: "agent2_title", desc: "agent2_desc" },
      { title: "agent3_title", desc: "agent3_desc" },
    ];
    agCards.forEach((card, i) => {
      if (agKeys[i]) {
        card.querySelector("h4").textContent = t(agKeys[i].title);
        card.querySelector(".agent-summary").textContent = t(agKeys[i].desc);
        card.querySelector(".agent-expand").innerHTML = `<i class="ri-information-line"></i> ${t("agent_view_details")}`;
      }
    });
  }

  // Upload page
  setText("#page-1 .page-header h2", `<i class="ri-upload-cloud-2-line"></i> ${t("upload_title")}`, true);
  setText("#page-1 .page-header p", t("upload_desc"));
  setText(".upload-title", t("upload_drop_title"));
  setText(".upload-sub", t("upload_drop_sub"));
  const uploadActions = document.querySelectorAll("#page-1 .page-actions button");
  if (uploadActions[0]) uploadActions[0].innerHTML = `<i class="ri-arrow-left-line"></i> ${t("upload_back")}`;
  if (uploadActions[1]) uploadActions[1].innerHTML = `${t("upload_next")} <i class="ri-arrow-right-line"></i>`;

  // Workflow page
  setText("#page-2 .page-header h2", `<i class="ri-flow-chart"></i> ${t("wf_title")}`, true);
  setText("#page-2 .page-header p", t("wf_desc"));
  const wfCards = document.querySelectorAll(".wf-card");
  const wfKeys = [
    { title: "wf_version_title", desc: "wf_version_desc" },
    { title: "wf_compliance_title", desc: "wf_compliance_desc" },
    { title: "wf_pack_title", desc: "wf_pack_desc" },
    { title: "wf_fact_title", desc: "wf_fact_desc" },
    { title: "wf_summary_title", desc: "wf_summary_desc" },
  ];
  wfCards.forEach((card, i) => {
    if (wfKeys[i]) {
      card.querySelector("h3").textContent = t(wfKeys[i].title);
      card.querySelector("p").textContent = t(wfKeys[i].desc);
    }
  });
  const wfActions = document.querySelectorAll("#page-2 .page-actions button");
  if (wfActions[0]) wfActions[0].innerHTML = `<i class="ri-arrow-left-line"></i> ${t("upload_back")}`;
  if (wfActions[1]) wfActions[1].innerHTML = `<i class="ri-play-circle-line"></i> ${t("wf_run")}`;

  // Processing page
  setText("#page-3 .page-header h2", `<i class="ri-robot-2-line"></i> ${t("proc_title")}`, true);
  setText("#page-3 .page-header p", t("proc_desc"));
  const pipes = document.querySelectorAll(".pipe-stage");
  const pipeKeys = [
    { title: "proc_agent1", desc: "proc_agent1_desc" },
    { title: "proc_agent2", desc: "proc_agent2_desc" },
    { title: "proc_agent3", desc: "proc_agent3_desc" },
  ];
  pipes.forEach((pipe, i) => {
    if (pipeKeys[i]) {
      pipe.querySelector("h4").textContent = t(pipeKeys[i].title);
      pipe.querySelector(".pipe-info p").textContent = t(pipeKeys[i].desc);
    }
  });

  // Results page
  setText("#page-4 .page-header h2", `<i class="ri-file-chart-line"></i> ${t("res_title")}`, true);
  setText("#page-4 .page-header p", t("res_desc"));
  const tabs = document.querySelectorAll(".tab-btn");
  const tabKeys = ["res_tab_report", "res_tab_indexer", "res_tab_analyzer"];
  tabs.forEach((tab, i) => { if (tabKeys[i]) tab.textContent = t(tabKeys[i]); });
  const btnNew = document.querySelector("#page-4 .page-actions .btn-secondary");
  if (btnNew) btnNew.innerHTML = `<i class="ri-restart-line"></i> ${t("res_new")}`;
  const btnCopy = document.getElementById("btn-copy-report");
  if (btnCopy) btnCopy.innerHTML = `<i class="ri-file-copy-line"></i> ${t("res_copy")}`;
  const btnExportPdf = document.getElementById("btn-export-pdf");
  if (btnExportPdf) btnExportPdf.innerHTML = `<i class="ri-file-pdf-2-line"></i> ${t("res_export_pdf")}`;
  const btnExportDocx = document.getElementById("btn-export-docx");
  if (btnExportDocx) btnExportDocx.innerHTML = `<i class="ri-file-word-2-line"></i> ${t("res_export_docx")}`;

  // Custom instructions
  const ciLabel = document.querySelector(".custom-instructions label");
  if (ciLabel) ciLabel.innerHTML = `<i class="ri-chat-3-line"></i> ${t("custom_label")} <span class="optional-tag">${t("custom_optional")}</span>`;
  const ciInput = document.getElementById("custom-input");
  if (ciInput) ciInput.placeholder = t("custom_placeholder");

  // Follow-up chat sidebar
  setText(".followup-title-text", t("chat_title"));
  setText(".followup-desc", t("chat_desc"));
  const chatInputEl = document.getElementById("chat-input");
  if (chatInputEl) chatInputEl.placeholder = t("chat_placeholder");
  const chatToggleLabel = document.querySelector(".chat-toggle-label");
  if (chatToggleLabel) chatToggleLabel.textContent = t("chat_title");

  // Language dropdown label
  const langLabel = document.getElementById("lang-label");
  if (langLabel) langLabel.textContent = currentLang === "en" ? "English" : "Polski";

  // Tour
  if (tourActive) showTourStep();
  document.querySelector(".tour-dismiss").textContent = t("tour_skip");
}

function setText(sel, val, isHtml = false) {
  const el = document.querySelector(sel);
  if (el) { if (isHtml) el.innerHTML = val; else el.textContent = val; }
}

// ─── Init ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.documentElement.lang = currentLang;
  applyLanguage();
  bindUpload();
  bindWorkflow();
  bindResultTabs();
  initChat();
  if (!localStorage.getItem("vigil-tour-done")) setTimeout(() => startTour(), 800);
});

// ═══ NAVIGATION ════════════════════════════════════════
function goToStep(step) {
  currentStep = step;
  document.querySelectorAll(".page").forEach((p, i) => p.classList.toggle("active", i === step));
  document.querySelectorAll(".nav-btn").forEach((b, i) => { b.classList.toggle("active", i === step); if (i < step) b.classList.add("completed"); else b.classList.remove("completed"); });
  document.querySelectorAll(".step-box").forEach((b, i) => { b.classList.toggle("active", i === step); b.classList.toggle("done", i < step); });
  document.querySelectorAll(".step-connector").forEach((c, i) => c.classList.toggle("done", i < step));
  if (tourActive) showTourForPage(step);
}

document.querySelectorAll(".nav-btn, .step-box").forEach(el => {
  el.addEventListener("click", () => { const s = parseInt(el.dataset.step); if (s <= currentStep || s === 0) goToStep(s); });
});

function selectWorkflowAndGo(wf) { selectedWorkflow = wf; goToStep(1); }

// ═══ UPLOAD ════════════════════════════════════════════
function bindUpload() {
  const zone = document.getElementById("drop-zone"), input = document.getElementById("file-input");
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("drag-over"); handleFiles(e.dataTransfer.files); });
  input.addEventListener("change", () => handleFiles(input.files));
}

async function handleFiles(fileList) {
  if (!fileList || !fileList.length) return;

  const fd = new FormData();
  for (const f of fileList) fd.append("files", f);
  if (currentUploadId) fd.append("upload_id", currentUploadId);

  // Show loading overlay
  const zone = document.getElementById("drop-zone");
  const loading = document.getElementById("upload-loading");
  zone.classList.add("uploading");
  loading.classList.remove("hidden");

  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();

    if (!res.ok) {
      if (res.status === 410) {
        currentUploadId = null;
        uploadedDocuments = [];
        renderUploadedFiles();
        updateUploadBtn();
      }
      showUploadError(data.error || "Upload failed — please try again.");
      return;
    }

    if (data.upload_id) currentUploadId = data.upload_id;
    if (Array.isArray(data.documents) && data.documents.length) {
      uploadedDocuments.push(...data.documents);
      renderUploadedFiles();
      updateUploadBtn();
    }
    if (data.errors && data.errors.length) {
      const names = data.errors.map(e => e.filename).join(", ");
      showUploadError(`Failed to parse: ${names}`);
    }
  } catch (e) {
    console.error("Upload failed:", e);
    showUploadError("Upload failed — please try again.");
  } finally {
    zone.classList.remove("uploading");
    loading.classList.add("hidden");
  }
}

function showUploadError(msg) {
  let el = document.getElementById("upload-error");
  if (!el) {
    el = document.createElement("div");
    el.id = "upload-error";
    el.style.cssText = "color:var(--red,#e53e3e);background:var(--red-bg,#fff5f5);padding:10px 16px;border-radius:10px;margin:12px 0;font-size:0.9rem;display:flex;align-items:center;gap:8px;";
    const zone = document.getElementById("drop-zone");
    zone.parentNode.insertBefore(el, zone.nextSibling);
  }
  el.innerHTML = `<i class="ri-error-warning-line"></i> ${esc(msg)}`;
  setTimeout(() => el.remove(), 8000);
}

function renderUploadedFiles() {
  document.getElementById("uploaded-files").innerHTML = uploadedDocuments.map((d, i) =>
    `<div class="uploaded-item"><div class="u-icon"><i class="ri-file-text-line"></i></div><span class="u-name">${esc(d.filename)}</span><span class="u-size">${d.word_count} ${t("upload_words")}</span><button class="u-remove" onclick="removeUploaded(${i})"><i class="ri-close-line"></i></button></div>`).join("");
}
function removeUploaded(i) { uploadedDocuments.splice(i, 1); renderUploadedFiles(); updateUploadBtn(); }
function updateUploadBtn() { document.getElementById("btn-to-workflow").disabled = uploadedDocuments.length === 0; }

// ═══ WORKFLOW ══════════════════════════════════════════
function bindWorkflow() {
  document.querySelectorAll(".wf-card").forEach(card => {
    card.addEventListener("click", () => {
      document.querySelectorAll(".wf-card").forEach(c => c.classList.remove("selected"));
      card.classList.add("selected"); selectedWorkflow = card.dataset.wf;
      document.getElementById("btn-run").disabled = false;
    });
  });
}

// ═══ PIPELINE ══════════════════════════════════════════
async function startPipeline() {
  if (!selectedWorkflow) return; goToStep(3); resetProcessingUI();
  const allDocs = [...uploadedDocuments];
  if (!allDocs.length) { addLog(t("log_no_docs"), "red"); return; }
  if (!currentUploadId) {
    addLog(t("log_error").replace("{msg}", "Upload session expired. Please upload your files again."), "red");
    return;
  }
  addLog(t("log_starting").replace("{wf}", wfLabel(selectedWorkflow)).replace("{n}", allDocs.length), "blue");
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow: selectedWorkflow,
        upload_id: currentUploadId,
        document_ids: allDocs.map(doc => doc.id),
        language: currentLang,
        custom_instructions: document.getElementById("custom-input").value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to start analysis");
    currentJobId = data.job_id; addLog(t("log_job").replace("{id}", currentJobId), "blue");
    streamJob(currentJobId);
  } catch (e) {
    addLog(t("log_error").replace("{msg}", e.message), "red");
    if ((e.message || "").toLowerCase().includes("upload session expired")) {
      currentUploadId = null;
      goToStep(1);
    }
  }
}

let streamingReportText = "";
let eventSource = null;

function streamJob(jobId) {
  streamingReportText = "";
  eventSource = new EventSource(`/api/job/${jobId}/stream`);

  eventSource.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);

      if (msg.type === "stages") {
        updatePipelineUI(msg);
      }

      if (msg.type === "advisor_chunk") {
        streamingReportText += msg.text;
        document.getElementById("result-report").innerHTML = renderMD(streamingReportText);
        // Auto-switch to results page on first chunk to show streaming
        if (currentStep === 3 && streamingReportText.length > 20) {
          goToStep(4);
        }
      }

      if (msg.type === "done") {
        eventSource.close(); eventSource = null;
        if (msg.status === "done") {
          addLog(t("log_all_done"), "green");
          renderResults(msg);
          if (currentStep !== 4) goToStep(4);
        } else {
          addLog(t("log_error").replace("{msg}", msg.error), "red");
        }
      }
    } catch (e) { /* parse error — ignore */ }
  };

  eventSource.onerror = () => {
    // SSE disconnected — fall back to final poll
    if (eventSource) { eventSource.close(); eventSource = null; }
    setTimeout(() => pollJobOnce(jobId), 1000);
  };
}

async function pollJobOnce(jobId) {
  try {
    const job = await (await fetch(`/api/job/${jobId}`)).json();
    updatePipelineUI(job);
    if (job.status === "done") { addLog(t("log_all_done"), "green"); renderResults(job); goToStep(4); }
    else if (job.status === "error") { addLog(t("log_error").replace("{msg}", job.error), "red"); }
    else { setTimeout(() => pollJobOnce(jobId), 2000); }
  } catch (e) { /* transient */ }
}

function updatePipelineUI(job) {
  const ids = ["stage-indexer", "stage-analyzer", "stage-advisor"], conns = document.querySelectorAll(".pipe-connector");
  ids.forEach((id, i) => {
    const el = document.getElementById(id), s = job.stages[i];
    el.classList.remove("active", "done", "error");
    if (s) {
      if (s.status === "running") { el.classList.add("active"); el.querySelector(".pipe-status").innerHTML = '<div class="spinner"></div>'; addLogOnce(`a${i}s`, t("log_working").replace("{agent}", s.agent), "blue"); }
      else if (s.status === "done") { el.classList.add("done"); el.querySelector(".pipe-status").innerHTML = '<i class="ri-checkbox-circle-fill done-check"></i>'; if (i < conns.length) conns[i].classList.add("done"); addLogOnce(`a${i}d`, t("log_done").replace("{agent}", s.agent), "green"); }
      else if (s.status === "error") { el.classList.add("error"); el.querySelector(".pipe-status").innerHTML = '<i class="ri-error-warning-fill" style="color:var(--red)"></i>'; }
    }
  });
}

function resetProcessingUI() {
  ["stage-indexer","stage-analyzer","stage-advisor"].forEach(id => { const el = document.getElementById(id); el.classList.remove("active","done","error"); el.querySelector(".pipe-status").innerHTML = '<i class="ri-time-line" style="color:var(--text-muted)"></i>'; });
  document.querySelectorAll(".pipe-connector").forEach(c => c.classList.remove("done"));
  document.getElementById("processing-log").innerHTML = ""; loggedMsgs.clear();
}

const loggedMsgs = new Set();
function addLog(msg, c="") { const log = document.getElementById("processing-log"); log.innerHTML += `<div class="log-entry"><div class="log-dot ${c==='green'?'green':c==='blue'?'blue':''}"></div><span>${msg}</span></div>`; log.scrollTop = log.scrollHeight; }
function addLogOnce(k,m,c) { if (loggedMsgs.has(k)) return; loggedMsgs.add(k); addLog(m,c); }

// ═══ RESULTS ═══════════════════════════════════════════
function renderResults(job) {
  document.getElementById("result-report").innerHTML = renderMD(job.result || "No report.");
  const idx = job.stage_outputs?.[0]?.output;
  document.getElementById("result-indexer").innerHTML = idx ? `<pre><code>${esc(JSON.stringify(idx,null,2))}</code></pre>` : "<p>No data.</p>";
  const ana = job.stage_outputs?.[1]?.output;
  document.getElementById("result-analyzer").innerHTML = ana ? `<pre><code>${esc(JSON.stringify(ana,null,2))}</code></pre>` : "<p>No data.</p>";
}
function bindResultTabs() { document.querySelectorAll(".tab-btn").forEach(b => b.addEventListener("click", () => { document.querySelectorAll(".tab-btn").forEach(x => x.classList.remove("active")); b.classList.add("active"); document.querySelectorAll(".result-panel").forEach(p => p.classList.add("hidden")); document.getElementById(`result-${b.dataset.tab}`).classList.remove("hidden"); })); }
function copyReport() {
  const txt = document.getElementById("result-report").innerText;
  navigator.clipboard.writeText(txt).then(() => {
    const b = document.getElementById("btn-copy-report");
    if (!b) return;
    const o = b.innerHTML;
    b.innerHTML = `<i class="ri-check-line"></i> ${t("res_copied")}`;
    setTimeout(() => b.innerHTML = `<i class="ri-file-copy-line"></i> ${t("res_copy")}`, 1500);
    if (!o) b.innerHTML = `<i class="ri-file-copy-line"></i> ${t("res_copy")}`;
  });
}

function getReportElement() {
  return document.getElementById("result-report");
}

function hasExportableReport() {
  const reportEl = getReportElement();
  return reportEl && reportEl.innerText.trim().length > 0;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function makeReportFilename(ext) {
  const baseLabel = selectedWorkflow ? wfLabel(selectedWorkflow) : "report";
  const safeBase = baseLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "report";
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `vigil-${safeBase}-${yyyy}-${mm}-${dd}.${ext}`;
}

function buildExportHtml(contentHtml) {
  return `<!doctype html>
<html lang="${currentLang}">
<head>
  <meta charset="utf-8">
  <title>Vigil Report</title>
  <style>
    body { margin: 0; padding: 24px; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1e293b; line-height: 1.7; font-size: 13px; background: #ffffff; }
    .report { max-width: 980px; margin: 0 auto; }
    h1, h2, h3, h4 { margin: 14px 0 6px; color: #1e293b; }
    h1 { font-size: 20px; } h2 { font-size: 17px; } h3 { font-size: 15px; } h4 { font-size: 14px; }
    p { margin: 5px 0; }
    ul, ol { padding-left: 18px; margin: 6px 0; }
    li { margin: 3px 0; }
    table { border-collapse: collapse; width: 100%; margin: 10px 0; table-layout: fixed; }
    th, td { border: 1px solid #e3e8ef; padding: 7px 10px; text-align: left; vertical-align: top; word-break: break-word; }
    th { background: #f0f3f8; font-weight: 600; }
    code { background: #f0f3f8; padding: 2px 6px; border-radius: 4px; font-size: .9em; }
    pre { background: #f0f3f8; padding: 12px; border-radius: 10px; overflow: auto; margin: 8px 0; }
    pre code { background: none; padding: 0; }
    blockquote { border-left: 3px solid #003B71; padding-left: 14px; color: #475569; margin: 8px 0; }
  </style>
</head>
<body><div class="report">${contentHtml}</div></body>
</html>`;
}

async function exportReportPdf() {
  if (!hasExportableReport()) {
    alert(t("res_no_report"));
    return;
  }
  if (typeof html2pdf === "undefined") {
    alert(t("res_export_not_supported"));
    return;
  }

  const btn = document.getElementById("btn-export-pdf");
  const oldHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="ri-loader-4-line"></i> ${t("res_exporting_pdf")}`;
  }

  try {
    const reportEl = getReportElement();
    const clone = reportEl.cloneNode(true);
    clone.style.background = "#ffffff";
    clone.style.border = "none";
    clone.style.borderRadius = "0";
    clone.style.padding = "0";
    clone.style.fontSize = "13px";
    clone.querySelectorAll("table, tr, td, th").forEach(el => {
      el.style.pageBreakInside = "avoid";
    });

    const container = document.createElement("div");
    container.style.background = "#ffffff";
    container.style.padding = "16px";
    container.style.maxWidth = "980px";
    container.appendChild(clone);

    const opts = {
      margin: [8, 8, 8, 8],
      filename: makeReportFilename("pdf"),
      image: { type: "jpeg", quality: 0.98 },
      html2canvas: { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
      jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
      pagebreak: { mode: ["css", "legacy"] },
    };

    await html2pdf().set(opts).from(container).save();
  } catch (err) {
    alert(t("res_export_failed"));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = oldHtml || `<i class="ri-file-pdf-2-line"></i> ${t("res_export_pdf")}`;
    }
  }
}

async function exportReportDocx() {
  if (!hasExportableReport()) {
    alert(t("res_no_report"));
    return;
  }
  if (!window.htmlDocx || typeof window.htmlDocx.asBlob !== "function") {
    alert(t("res_export_not_supported"));
    return;
  }

  const btn = document.getElementById("btn-export-docx");
  const oldHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="ri-loader-4-line"></i> ${t("res_exporting_docx")}`;
  }

  try {
    const reportEl = getReportElement();
    const htmlDoc = buildExportHtml(reportEl.innerHTML);
    const blob = window.htmlDocx.asBlob(htmlDoc, {
      orientation: "portrait",
      margins: { top: 720, right: 720, bottom: 720, left: 720 },
    });
    downloadBlob(blob, makeReportFilename("docx"));
  } catch (err) {
    alert(t("res_export_failed"));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = oldHtml || `<i class="ri-file-word-2-line"></i> ${t("res_export_docx")}`;
    }
  }
}

function resetAll() { if (eventSource) { eventSource.close(); eventSource = null; } uploadedDocuments=[]; currentUploadId=null; selectedWorkflow=null; currentJobId=null; chatHistory=[]; streamingReportText=""; document.querySelectorAll(".wf-card").forEach(c=>c.classList.remove("selected")); document.getElementById("uploaded-files").innerHTML=""; document.getElementById("btn-to-workflow").disabled=true; document.getElementById("btn-run").disabled=true; document.getElementById("chat-messages").innerHTML=""; document.getElementById("custom-input").value=""; document.getElementById("chat-panel").classList.remove("open"); document.getElementById("chat-backdrop").classList.remove("open"); goToStep(0); }

// ═══ AGENT DETAIL MODALS ═══════════════════════════════
function openAgentModal(agentId) {
  const icons = { indexer: "ri-search-eye-line", analyzer: "ri-scales-3-line", advisor: "ri-lightbulb-flash-line" };
  const colors = { indexer: { c: "var(--blue)", bg: "var(--blue-bg)" }, analyzer: { c: "var(--purple)", bg: "var(--purple-bg)" }, advisor: { c: "var(--green)", bg: "var(--green-bg)" } };
  const am = t("agent_modal")?.[agentId]; if (!am) return;
  const ic = icons[agentId], cl = colors[agentId];
  const howTitle = agentId === "analyzer" ? t("modal_modes") : agentId === "advisor" ? t("modal_reports") : t("modal_how");

  const modal = document.getElementById("agent-modal");
  modal.innerHTML = `<div class="modal">
    <div class="modal-head">
      <h2><div style="width:36px;height:36px;border-radius:10px;background:${cl.bg};color:${cl.c};display:grid;place-items:center;font-size:1.1rem"><i class="${ic}"></i></div> ${am.title}</h2>
      <button class="modal-close" onclick="closeAgentModal()"><i class="ri-close-line"></i></button>
    </div>
    <div class="modal-section"><h3><i class="ri-briefcase-line"></i> ${t("modal_biz")}</h3><p>${am.biz}</p></div>
    <div class="modal-section"><h3><i class="ri-code-s-slash-line"></i> ${t("modal_tech")}</h3><p>${am.tech}</p></div>
    <div class="modal-section"><h3><i class="ri-flow-chart"></i> ${howTitle}</h3><ul>${am.how.map(l=>`<li>${l}</li>`).join('')}</ul></div>
    <div class="modal-section"><h3><i class="ri-shield-star-line"></i> ${t("modal_principle")}</h3><p>${am.principle}</p></div>
    <div class="modal-tag-row">
      <span class="modal-tag tech">Azure AI Foundry</span>
      <span class="modal-tag tech">${agentId === "indexer" ? "Chat Completions" : agentId === "analyzer" ? "Chat Completions" : "Streaming"}</span>
      <span class="modal-tag tech">${agentId === "indexer" ? "Indexer model" : agentId === "analyzer" ? "Analyzer model" : "Advisor model"}</span>
      <span class="modal-tag tech">${agentId === "advisor" ? "Markdown" : "JSON"} output</span>
      ${agentId === "advisor" ? '<span class="modal-tag tech">Streaming</span>' : ''}
      ${agentId !== "advisor" ? '<span class="modal-tag tech">Azure AI Search</span>' : ''}
      <span class="modal-tag biz">${currentLang === "pl" ? "Analiza dokumentów" : "Document analysis"}</span>
    </div>
  </div>`;
  modal.classList.remove("hidden");
  modal.addEventListener("click", e => { if (e.target === modal) closeAgentModal(); });
}
function closeAgentModal() { document.getElementById("agent-modal").classList.add("hidden"); }

// ═══ GUIDED TOUR ═══════════════════════════════════════
const TOUR_PAGES = [0, 0, 1, 2, 3, 4];
let tourActive = false, tourStep = 0;

function startTour() { tourActive = true; tourStep = 0; showTourStep(); document.getElementById("tour-popup").classList.remove("hidden"); }
function endTour() { tourActive = false; document.getElementById("tour-popup").classList.add("hidden"); localStorage.setItem("vigil-tour-done", "1"); }

function tourNav(dir) {
  tourStep += dir;
  if (tourStep >= t("tour").length) { endTour(); return; }
  if (tourStep < 0) { tourStep = 0; return; }
  if (TOUR_PAGES[tourStep] !== currentStep) goToStep(TOUR_PAGES[tourStep]);
  showTourStep();
}

function showTourStep() {
  const steps = t("tour");
  const ts = steps[tourStep];
  document.getElementById("tour-title").textContent = ts.title;
  document.getElementById("tour-text").textContent = ts.text;
  document.getElementById("tour-prev").textContent = t("tour_back");
  document.getElementById("tour-prev").style.visibility = tourStep === 0 ? "hidden" : "visible";
  document.getElementById("tour-next").textContent = tourStep === steps.length - 1 ? t("tour_finish") : t("tour_next");
  document.querySelector(".tour-dismiss").textContent = t("tour_skip");
  document.getElementById("tour-dots").innerHTML = steps.map((_, i) => `<div class="tour-dot${i === tourStep ? ' active' : ''}"></div>`).join('');
}

function showTourForPage(page) {
  const match = TOUR_PAGES.indexOf(page);
  if (match >= 0) { tourStep = match; showTourStep(); }
}

// ═══ UTILITIES ═════════════════════════════════════════
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function sanitizeHtml(html) {
  if (typeof DOMPurify !== "undefined") {
    return DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
    });
  }
  return html;
}

function addSafeLinkAttrs(html) {
  const wrapper = document.createElement("div");
  wrapper.innerHTML = html;
  wrapper.querySelectorAll("a[href]").forEach(link => {
    const href = link.getAttribute("href") || "";
    if (/^https?:\/\//i.test(href)) {
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
    }
  });
  return wrapper.innerHTML;
}

function renderMD(txt) {
  // Clean up literal \n that LLM agents sometimes emit inside markdown table cells
  txt = txt.replace(/(?<=\|[^|]*?)\\n(?=[^|]*?\|)/g, '<br>');
  // Also clean up any remaining literal \n outside tables
  txt = txt.replace(/\\n/g, '\n');
  let html = `<pre>${esc(txt)}</pre>`;
  if (typeof marked !== "undefined") {
    marked.setOptions({ breaks: true, gfm: true });
    html = marked.parse(txt);
  }
  return addSafeLinkAttrs(sanitizeHtml(html));
}
function wfLabel(w) {
  const key = `wfl_${w}`;
  return t(key) !== key ? t(key) : w;
}

// ═══ CHAT SIDEBAR PANEL ═══════════════════════════════

function toggleChatPanel() {
  const panel = document.getElementById("chat-panel");
  const backdrop = document.getElementById("chat-backdrop");
  const isOpen = panel.classList.toggle("open");
  backdrop.classList.toggle("open", isOpen);
  if (isOpen) {
    setTimeout(() => document.getElementById("chat-input").focus(), 300);
  }
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && document.getElementById("chat-panel").classList.contains("open")) {
    toggleChatPanel();
  }
});

function initChat() {
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send-btn");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = input.scrollHeight + "px";
    sendBtn.disabled = !input.value.trim();
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("chat-form").requestSubmit(); }
  });
}

async function sendChat(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = ""; input.style.height = "auto";
  document.getElementById("chat-send-btn").disabled = true;
  document.getElementById("chat-send-btn").classList.add("hidden");
  document.getElementById("chat-stop-btn").classList.remove("hidden");

  // Add user message
  appendChatMsg("user", msg);
  chatHistory.push({ role: "user", content: msg });

  // Add thinking indicator
  const thinkId = "chat-thinking-" + Date.now();
  const container = document.getElementById("chat-messages");
  const thinkEl = document.createElement("div");
  thinkEl.className = "chat-msg assistant"; thinkEl.id = thinkId;
  thinkEl.innerHTML = `<div class="chat-avatar"><i class="ri-eye-2-line"></i></div><div class="chat-bubble"><div class="chat-thinking"><div class="chat-thinking-dot"></div><div class="chat-thinking-dot"></div><div class="chat-thinking-dot"></div></div></div>`;
  container.appendChild(thinkEl);
  container.scrollTop = container.scrollHeight;

  // Create abort controller
  chatAbortController = new AbortController();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: currentJobId,
        message: msg,
        history: chatHistory.slice(0, -1), // exclude current msg, it's in message
        language: currentLang,
      }),
      signal: chatAbortController.signal,
    });
    const data = await res.json();
    document.getElementById(thinkId)?.remove();

    if (data.error) {
      appendChatMsg("assistant", `Error: ${data.error}`);
    } else {
      appendChatMsg("assistant", data.reply, true);
      chatHistory.push({ role: "assistant", content: data.reply });
    }
  } catch (err) {
    document.getElementById(thinkId)?.remove();
    if (err.name === "AbortError") {
      appendChatMsg("assistant", "Response stopped.");
    } else {
      appendChatMsg("assistant", `Connection error: ${err.message}`);
    }
  } finally {
    chatAbortController = null;
    document.getElementById("chat-stop-btn").classList.add("hidden");
    document.getElementById("chat-send-btn").classList.remove("hidden");
    document.getElementById("chat-send-btn").disabled = !document.getElementById("chat-input").value.trim();
  }
}

function stopChat() {
  if (chatAbortController) {
    chatAbortController.abort();
  }
}

function appendChatMsg(role, content, isMarkdown = false) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  const avatarIcon = role === "user" ? "ri-user-3-line" : "ri-eye-2-line";
  const bubbleContent = isMarkdown ? renderMD(content) : esc(content);
  div.innerHTML = `<div class="chat-avatar"><i class="${avatarIcon}"></i></div><div class="chat-bubble">${bubbleContent}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

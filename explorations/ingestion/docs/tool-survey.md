# Tool survey

Before building the prototype, the existing open-source parsers, table and form tools, chunkers, pipelines and evaluation tools were cloned at pinned commits, read at the modules that matter for drilling reports, and, where practical, run locally on selected source pages. Each tool has a note under [tools/](tools/) with its licence, local install result, the relevant source locations, observed output and a verdict. Papers and standards are summarized in [papers.md](papers.md). Captured scores and outputs are in [tool-survey.json](../results/tool-survey.json); pins and licences are in [the input lock](../configs/inputs.lock.json) and [NOTICE](../NOTICE.md).

Selection criteria: a licence that permits commercial on-premises use without a revenue threshold; local operation on CPU or an Intel GPU, and on NVIDIA GPUs later; models of at most 7B parameters; page and box provenance; active maintenance; Windows support; and compatibility with the `DoclingDocument` model already used by the repository pipelines.

## Verdicts

D = adopt as a dependency, I = reuse an idea, S = skip.

| Area | Tools | Verdict |
| --- | --- | --- |
| Document model and parsing | [Docling](tools/docling.md), [docling-core](tools/docling-core.md), [docling-ibm-models](tools/docling-ibm-models.md) | D: standard pipeline with fast TableFormer |
| Alternative parsers | [MinerU](tools/mineru.md), [PaddleOCR](tools/paddleocr.md), [OpenDataLoader PDF](tools/opendataloader-pdf.md), [deepdoctection](tools/deepdoctection.md), [Unstructured](tools/unstructured.md), [RAGFlow](tools/ragflow.md), [Marker](tools/marker.md) | I: page-level layout and table ideas; MinerU code has a commercial threshold on consolidated revenue |
| Rule-based tables | [pdfplumber](tools/pdfplumber.md), [Camelot](tools/camelot.md), [img2table](tools/img2table.md) | I: fast on simple ruled tables, unreliable on dense report forms |
| Table structure and continuation | [Table Transformer](tools/table-transformer.md), [POTATR](tools/potatr.md), [mineru-refine](tools/mineru-refine.md), [docvortex](tools/docvortex.md) | I: continuation is a separate assembly step after parsing |
| Forms and extraction | [NuExtract](tools/nuextract.md), [Azure Document Intelligence schema](tools/azure-di-schema.md), [WITSML schema](tools/witsml-schema.md), [WITSML client](tools/witsml.md) | I: key/value records with boxes; WITSML supplies field vocabulary only |
| Intake and OCR | [pikepdf](tools/pikepdf.md), [OCRmyPDF](tools/ocrmypdf.md), [Apache Tika](tools/tika.md), [Dangerzone](tools/dangerzone.md) | D: OCRmyPDF for English scans; I: the others for intake hardening |
| Chunking and lineage | [LlamaIndex](tools/llama-index.md), [LangChain](tools/langchain.md), [Chonkie](tools/chonkie.md), [dsRAG](tools/dsrag.md), [neo4j-graphrag](tools/neo4j-graphrag.md), [LightRAG](tools/lightrag.md), [RAG-Anything](tools/rag-anything.md) | I: parent/child records, context kept outside chunk text |
| Scale | [docling-serve](tools/docling-serve.md), [NeMo Retriever](tools/nemo-retriever.md), [olmOCR](tools/olmocr.md), [data-prep-kit](tools/data-prep-kit.md), [llama.cpp](tools/llama.cpp.md) | I: page-level jobs, cached stages, one OpenAI-compatible model endpoint |
| Evaluation | [docling-eval](tools/docling-eval.md), [OmniDocBench](tools/omnidocbench.md), [Label Studio](tools/label-studio.md) | I: table and layout metrics, annotation tooling |

## Findings that shaped the prototype

- **Docling's standard pipeline is the strongest local option on these reports.** On nine annotated grid tables, fast TableFormer averages 85.1% data-cell accuracy, accurate TableFormer 68.9% and a local 1.2B document VLM 72.7%, at about 4 versus 156 seconds per page. See [evaluation](evaluation.md#parser-comparison).
- **A local VLM is not a safe automatic replacement.** It wins clearly on one dense landscape table, loses badly on another, and once inserted a sentence that is not on the page. Neither simple page-selection signals nor same-page token support could decide when to trust it. See [evaluation](evaluation.md#hard-page-selection).
- **No surveyed tool joined the continued tables** in the selected reports, so table continuation is implemented as its own step.
- **Form pairs need the source text layer.** Pairing from parser cells repeats the parser's mispairings; pairing visible glyphs within vector-ruled cells, with a template for one report family, matches every annotated pair. See [evaluation](evaluation.md#form-pairing).
- **For English scanned pages, OCRmyPDF (Tesseract) is the most accurate and fastest of the six engines tried** on critical tokens such as depths, regulation numbers and gas names. See [evaluation](evaluation.md#scanned-page-ocr).
- **Licences matter for an enterprise deployment.** MinerU's code requires a commercial licence above a consolidated revenue threshold, and several model weights carry non-commercial or revenue terms. These are recorded per source in [NOTICE](../NOTICE.md).

Not covered by the survey: Vietnamese documents, Office formats, hostile-input handling and multi-machine throughput.

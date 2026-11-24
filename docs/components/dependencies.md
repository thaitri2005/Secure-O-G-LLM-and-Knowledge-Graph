# Dependencies and licences

This guide says which Python packages the repository needs, where each one is declared, how to install them, and one licence that needs a decision before anything is distributed (PyMuPDF). It records what was checked on 16 November 2026 with Python 3.12 on Windows. Model files are listed in [model provenance](model-provenance.md).

## Where packages are declared

| File | Role |
|---|---|
| `pyproject.toml` | Direct imports with exact versions, including the core dependencies, the `ocr` extra and the optional PDF reader in the `qa` extra |
| `requirements.lock.txt` | The complete verified Windows CPU environment: every package above plus everything they pull in, and PyMuPDF for the tests |
| `requirements-graphrag.lock.txt`, `requirements-lightrag.lock.txt` | Separate environments for the Track B tools; not needed for Track A |

Every version in `pyproject.toml` equals the version in `requirements.lock.txt`. `pip install --dry-run ".[ocr,qa]"` on an environment installed from the lock resolves with no conflict.

## What the code imports

Found by reading the syntax tree of every Python file (so imports inside functions are counted) and by importing every module of `graph_builder` with PyMuPDF made unimportable.

| Package | Imported by | Declared in |
|---|---|---|
| docling, docling-core, jsonschema, pypdf, pypdfium2, rapidfuzz | the corpus and ingestion pipelines | `dependencies` |
| Pillow | `corpus/formats.py` (checks that an added image opens) | `dependencies` |
| tabulate | `ingestion/tables.py` (table Markdown with merged cells) | `dependencies` |
| transformers | `ingestion/strategies.py` (tokenizer of the hybrid chunker) | `dependencies` |
| openpyxl | `datasets/readers.py` (`.xlsx` import) | `dependencies` |
| filelock | `corpus/qa/cli.py` (locks the output directory while publishing QA results) | `dependencies` |
| rapidocr, numpy, PyYAML, torch | `corpus/vietocr_engine.py` (the VietOCR plugin) | extra `ocr` |
| easyocr | `corpus/ocr_engines.py`, `ingestion/ocr_models.py` | extra `ocr` |
| opencv-python-headless (`cv2`) | Scan grid, field and ink analysis | extra `ocr` |
| onnxruntime | not imported by name; the RapidOCR backend that Docling and the plugin use (`backend="onnxruntime"`), and `engine_fingerprint` records its version | extra `ocr` |
| vietocr | `corpus/vietocr_engine.py` | not declared: installed with `pip install --no-deps vietocr==0.3.13` because its own metadata pins old packages |
| PyMuPDF (`fitz`, `pymupdf`) | `corpus/ruled_panels.py`, `corpus/qa/cell_evidence.py`, tests and benchmark scripts | extra `qa` |
| tokenizers | `corpus/qa/ledger.py` (optional table token checks) | extra `qa` |
| psutil | `scripts/benchmark_track_a_ablation.py` (peak memory on Windows) | extra `qa` on Windows |

Pillow, tabulate, transformers and openpyxl also arrive through Docling, and numpy, PyYAML, torch and rapidocr through the OCR packages. They are declared anyway because this repository's own code imports them, and the file's rule is to list direct imports.

Scripts under `scripts/` that import `pdfplumber`, `camelot` or `reportlab` run in separate environments (`explorations/ingestion/.venvs/`) or are report tools. They are not declared and no test needs them.

## Install

Environment for development and tests (this is the verified one; it contains PyMuPDF):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\python -m pip install --no-deps vietocr==0.3.13     # only for the vietocr engine
```

Without the lock, the same packages come from the extras: `pip install -e ".[ocr,qa]"`. Use `".[ocr]"` alone for an environment that must not contain PyMuPDF.

The lock marks `pywin32` as Windows-only (`; sys_platform == "win32"`). `docling-parse` and `mpire` already require it only on Windows, so the marker changes nothing there. The lock has been installed and tested on Windows only. A Linux or GPU environment is not verified, and leaving out Windows-only lines by hand does not make one.

## PyMuPDF: what needs it

- **Tests** (seven files): `test_corpus_table_join.py`, `test_page_orientation.py`, `test_qa_false_positive_reductions.py`, `test_qa_fidelity_furniture_and_enumerators.py`, `test_qa_fidelity.py`, `test_qa_labelvalue.py` build small PDFs or read pages with it, and `test_qa_multipage_scan.py` reaches it through `scripts/qa_multipage_scan.py`. Without the package `test_corpus_table_join.py` stops at import, the multipage test fails, and several others skip. A skipped test is not a pass, so install the lock or `.[qa]` before running the suite.
- **Scripts**: `scripts/evaluate_ops_tables.py`, `scripts/benchmark_tables.py`, `scripts/qa_multipage_scan.py`, `scripts/qa_multipage_structure.py` use it as an independent reader of the PDF text layer.
- **Track A** uses it for independent cell verification in ruled panels, column alignment, numeric repair, scan repair and QA. A K1 profile with these rules requires PyMuPDF. K1 records the PDF reader versions, and QA checks them before publishing retrieval data. Scan table rules also need the local RapidOCR small weights and Tesseract with English language data.

Version `1.28.2` is pinned. It has no dependencies of its own. PyMuPDF 2.0 adds `pymupdf-layout` and `pymupdf4llm` as required packages, and the metadata of their 2.0 wheels states no licence, so 2.0 was not adopted. With 1.28.2 the seven test files above give 159 passed, 0 skipped. This version prints a deprecation warning on `import fitz` (the tests use that name); `import pymupdf` is the supported name.

## PyMuPDF: licence

PyMuPDF is dual-licensed: GNU AGPL-3.0, or a commercial licence from Artifex (the `License` field of the 1.28.2 package says exactly this). See the vendor's pages on [PyMuPDF licensing](https://pymupdf.io/licensing) and [Artifex licensing](https://artifex.com/licensing).

What follows is a technical reading for the team, **not legal advice**. The project owner and the team should confirm it with whoever decides licences for the capstone.

- AGPL-3.0 is a strong copyleft licence. Its network clause also addresses people who use a modified version over a network, so offering a combined work as a service can matter as much as handing out copies.
- The repository is public. The test and QA files that import PyMuPDF are published in it. Whether that, or handing out an environment that contains PyMuPDF, creates obligations is for the licence decision above.
- Repository licence status: the repository root has no `LICENSE` or `COPYING` file, `pyproject.toml` has no `license` field, and the README states no licence for the code. The only `LICENSE` file under version control is `explorations/kg-builder/LICENSE`, which holds the placeholder text "TBD by repository owner". The licence of this repository is therefore **unknown**. This change does not add or change any licence.
- PyMuPDF is an explicit optional dependency in the `qa` extra. No PyMuPDF source or binary is vendored in the repository.
- Review the applicable PyMuPDF licence for the deployment and distribution model.
- For a runtime without PyMuPDF, install `.[ocr]` and select a K1 profile that excludes rules requiring that reader. The available source-backed coverage depends on that profile. The lock contains PyMuPDF.

## Checks to repeat

```powershell
python -m pip check                                    # no broken requirements
python -m pip install --dry-run ".[ocr,qa]"            # resolves with no change except the package itself
python -m unittest discover -s tests                   # PyMuPDF tests run instead of skipping
```

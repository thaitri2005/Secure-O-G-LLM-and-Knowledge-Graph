# Model provenance

This guide lists the model files that the document pipeline ([`graph_builder.corpus`](corpus-ingestion.md)) and the earlier PDF pipeline load, with where each comes from, the exact bytes that were present on the development machine (SHA256) and how the pipeline pins them. It was read from the local caches on 16 November 2026 without downloading anything. Packages are listed in [dependencies](dependencies.md).

**Status words.** *Pinned in code* means the pipeline refuses a file with another digest (`VIETOCR_FILES` in `corpus/ocr_engines.py`). *Recorded* means the digest below was read from the local copy and is also written into the processing fingerprint of every run (`engine_fingerprint`), but nothing stops a different file from being used. *UNKNOWN* means it could not be established from the machine or the code.

## How models are found at run time

- Conversion sets `HF_HUB_OFFLINE=1` and downloads nothing. Models must be fetched once while online.
- OCR files are read from the folder given by `--models` (default `data/interim/ocr_models/`; the development machine also keeps a copy set under `explorations/ingestion/models/corpus-ocr/`). `python -m graph_builder.corpus models --engine <name>` fetches them and prints their digests.
- Docling's layout and table models are read from the Hugging Face cache (`~/.cache/huggingface/hub`).
- The package versions that load the models: docling 2.141.0, docling-core 2.103.1, docling-ibm-models 4.0.4, docling-parse 7.22.4, rapidocr 3.10.0, onnxruntime 1.31.1, easyocr 1.7.2, torch 2.14.1, transformers 5.20.2, vietocr 0.3.13 (installed by hand).

## Docling layout and table models

Used by every PDF conversion (`corpus/convert.py`). Configured table mode is `fast` in every config of the repository.

| Model | Source | Revision (commit) | File | Bytes | SHA256 | Licence | Status |
|---|---|---|---|---:|---|---|---|
| Layout "heron" | `docling-project/docling-layout-heron` on Hugging Face | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` (the `main` ref in the local cache) | `model.safetensors` | 171,658,996 | `00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c` | Apache-2.0 (model card) | Recorded |
| | | | `config.json` | 3,268 | `fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d` | | Recorded |
| | | | `preprocessor_config.json` | 444 | `cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1` | | Recorded |
| TableFormer fast (the mode used) | `docling-project/docling-models` | tag `v2.3.0` = `fc0f2d45e2218ea24bce5045f58a389aed16dc23` | `model_artifacts/tableformer/fast/tableformer_fast.safetensors` | 145,453,276 | `3119563aab5a7c96fda4d621119b63fd8806272b86c30936d15507616422f718` | CDLA-Permissive-2.0 (model card) | Recorded |
| | | | `model_artifacts/tableformer/fast/tm_config.json` | 7,060 | `dca6762508dddfae6d57d6cb4ef822c6000119dff0f3b6489db7413118c2622a` | | Recorded |
| TableFormer accurate (not used by default) | same | same | `model_artifacts/tableformer/accurate/tableformer_accurate.safetensors` | 212,758,388 | `2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9` | | Recorded |
| | | | `model_artifacts/tableformer/accurate/tm_config.json` | 7,060 | `984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd` | | Recorded |

- **How obtained:** `docling-tools models download layout tableformer` (see [PDF ingestion](pdf-ingestion.md)) or the first online run. The command that filled the cache on the development machine is UNKNOWN.
- **Floating revision.** Docling 2.141.0 asks for the layout model with `revision="main"`, so a new download can give different weights from the ones above. The table model is requested by tag `v2.3.0`. Neither digest is checked by this repository. To rebuild a result, compare the files in your cache with the digests above first.
- Docling also has an ONNX layout variant (`docling-layout-heron-onnx`). It is not in the cache and was not used.

## OCR models

Fetched by `python -m graph_builder.corpus models`. Which files an engine needs is in `model_files()` of `corpus/ocr_engines.py`.

### RapidOCR PP-OCRv6 (engines `rapidocr` and `vietocr`)

Downloaded by Docling's `RapidOcrModel.download_models` from the RapidOCR release that matches the installed `rapidocr` version (tag `v3.10.0`).

| File | Source URL | Bytes | SHA256 | Status |
|---|---|---:|---|---|
| `RapidOcr/PP-OCRv6_det_small.onnx` | `https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx` | 9,929,594 | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` | Recorded |
| `RapidOcr/PP-OCRv6_rec_small.onnx` | `https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx` | 21,234,383 | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` | Recorded |
| `RapidOcr/ch_ppocr_mobile_v2.0_cls_mobile.onnx` | `https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 585,532 | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` | Recorded |

Licence: the `rapidocr` package is Apache-2.0 (package metadata). The licence of the model files themselves is UNKNOWN; they are PaddleOCR-family models redistributed by RapidOCR.
The `medium` size (`ocr.model_size`) is also downloadable; its files were not present and are not recorded.

### VietOCR (engine `vietocr`, the code default)

| File | Source URL | Bytes | SHA256 | Status |
|---|---|---:|---|---|
| `vietocr/vgg_transformer.pth` | `https://vocr.vn/data/vietocr/vgg_transformer.pth` | 151,815,373 | `380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59` | Pinned in code |
| `vietocr/base.yml` | `https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/base.yml` | 1,809 | `9c8283fadb950f06f5d3400475f80d5355700ff315c9c48b7875e6ea66647d1c` | Pinned in code |
| `vietocr/vgg-transformer.yml` | `https://raw.githubusercontent.com/pbcquoc/vietocr/master/config/vgg-transformer.yml` | 505 | `0df9feee197754c7381871e5dfd07c6f3e292a4853eece6f1af240923e57c907` | Pinned in code |

The local copies match the digests in `VIETOCR_FILES`. The code comment gives Apache-2.0 for the VietOCR project (<https://github.com/pbcquoc/vietocr>); the licence of the weights file is not stated separately (UNKNOWN). The `master` URLs move, but the digest check rejects a changed file.

### EasyOCR (engine `easyocr`, kept for comparison)

| File | Official source (from `easyocr` 1.7.2 `config.py`) | Bytes | SHA256 | Status |
|---|---|---:|---|---|
| `craft_mlt_25k.pth` | `https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip` | 83,152,330 | `4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17` | Recorded |
| `english_g2.pth` | `https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip` | 15,143,997 | `e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8` | Recorded |

The same two files are in the Hugging Face cache (`Manbehindthemadness/craft_mlt_25k` at `31829d3ed627880337df7c4a5c12804f08ce7d2a`; `felflare/EasyOCR-weights` at `f7119b1e8e81d645467cde754cfd8db5490921c6`, `english_g2.zip` whose member has the digest above), with identical bytes. Which of the two routes produced the local `.pth` files is UNKNOWN. The `easyocr` package is Apache-2.0; the weights' licence is UNKNOWN. `ingestion/ocr_models.py` writes its own `models.json` with digests for this engine.

## Tokenizer of the earlier PDF pipeline

`ingestion/strategies.py` (`hybrid` chunking) loads the tokenizer of `sentence-transformers/all-MiniLM-L6-v2` (Apache-2.0, model card) without a revision. The local cache holds `main` = `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Files used: `tokenizer.json` (466,247 bytes, `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`), `tokenizer_config.json` (350, `acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b`), `vocab.txt` (231,508, `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3`), `special_tokens_map.json` (112, `303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3`). Status: Recorded. The corpus pipeline does not use it.

## Not part of this pipeline

Other model files exist on the development machine (embedding models in the Hugging Face cache, vision-language models under `explorations/ingestion/models/` for the VLM comparison). `graph_builder` does not load them, and they are not recorded here.

## Check the local copies

```powershell
Get-FileHash -Algorithm SHA256 data\interim\ocr_models\RapidOcr\PP-OCRv6_det_small.onnx
python -m graph_builder.corpus models --engine vietocr   # online; prints the digests of the files it needs
```

## Gaps

- The layout model revision is `main`, and no digest check exists for Docling's models or for the RapidOCR and EasyOCR files. Only the VietOCR files are pinned in code. Adding checks would change what a run accepts, so it needs a decision of its own.
- Licences of the RapidOCR, VietOCR and EasyOCR weight files are UNKNOWN.
- The exact command that produced the cached Docling files is UNKNOWN.

# Source and model notices

Source checkouts, native executables and weights remain in ignored directories. [One input lock](configs/inputs.lock.json) records source commits, PDF hashes, model revisions and bytes, environment manifests and the native runtime. Repository source is read at `2258b4dd9152b108903420ba298bbc452917e83d`. This notice distinguishes code, model and data terms; it is not a complete transitive licence audit.

The parser comparison executes the 1.2B Q8_0 MinerU quantization at revision `70429e9c728b6a5e904f358a9936c17bd3f5f4b8`, with its separately pinned f16 projector and local llama.cpp b12000 Vulkan runtime. The pinned model card declares Apache-2.0 (`third_party/models/mineru-gguf/README.md:1`), independently of the MinerU code terms below. [Runtime evidence](results/runtime.json).

Executed corpus dependencies include RapidOCR 3.10.0 (Apache-2.0), VietOCR 0.3.13 code (Apache-2.0) and ONNX Runtime 1.24.4 (MIT). Distribution evidence is retained in [RapidOCR licence](results/licenses/rapidocr-LICENSE.txt), [model notice](results/licenses/rapidocr-MODEL_LICENSES.md.txt), [VietOCR licence](results/licenses/vietocr-LICENSE.txt) and [ONNX Runtime licence](results/licenses/onnxruntime-LICENSE.txt). The RapidOCR model notice identifies separate PaddleOCR weight terms; the VietOCR code licence alone does not verify weight-distribution rights. Models are pinned separately in the input lock.

## Repositories

| Project | URL | Pinned commit | Recorded licence and evidence | Use |
|---|---|---|---|---|
| docling | https://github.com/docling-project/docling.git | `4f00195b8dadbc1a67f4cefae6b619c47e4e515f` | MIT; `third_party/docling/LICENSE:1` | study-run |
| docling-core | https://github.com/docling-project/docling-core.git | `25aaaf4af1c0f2a620716d7d483a34c820133e0e` | MIT; `third_party/docling-core/LICENSE:1` | study-run |
| docling-ibm-models | https://github.com/docling-project/docling-ibm-models.git | `a14d633bc9e80a985dab5d6aad686dace72488ba` | MIT; `third_party/docling-ibm-models/LICENSE:1` | study-run |
| mineru | https://github.com/opendatalab/MinerU.git | `dc60e7c6722ebf25a04ae2bc3b59f5b55118a040` | Custom Apache-2.0 with commercial thresholds and service attribution; `third_party/mineru/LICENSE.md:1` | study-run |
| paddleocr | https://github.com/PaddlePaddle/PaddleOCR.git | `dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf` | Apache-2.0; `third_party/paddleocr/LICENSE:1` | study-run |
| opendataloader-pdf | https://github.com/opendataloader-project/opendataloader-pdf.git | `73073ddb617e31ad64f508f00bd5ec13e969472a` | Apache-2.0; `third_party/opendataloader-pdf/LICENSE:1` | study-run |
| pdfplumber | https://github.com/jsvine/pdfplumber.git | `4c64b92d5caccd71c645e98e0fabb0c4dba7ff45` | MIT; `third_party/pdfplumber/LICENSE.txt:1` | study-run |
| camelot | https://github.com/camelot-dev/camelot.git | `92777b852e00933a5c4b9ba642601784604356cd` | MIT; `third_party/camelot/LICENSE:1` | study-run |
| pikepdf | https://github.com/pikepdf/pikepdf.git | `d55358f2d3c0a15f613dde4c2e8babe75515d461` | MPL-2.0; `third_party/pikepdf/LICENSE.txt:1` | read |
| ocrmypdf | https://github.com/ocrmypdf/OCRmyPDF.git | `b457e9efa68c3a46be2470ffb222ed1bccc4dcbc` | MPL-2.0; `third_party/ocrmypdf/LICENSE:1` | read |
| deepdoctection | https://github.com/deepdoctection/deepdoctection.git | `763da61497f4d8627f549bec5e03dbcb4ceb1ef2` | Apache-2.0; `third_party/deepdoctection/LICENSE:1` | read |
| nemo-retriever | https://github.com/NVIDIA/NeMo-Retriever.git | `de4190987f4c54db0b01be701bf2b0adc30b5c06` | Apache-2.0; `third_party/nemo-retriever/LICENSE:1` | read |
| ragflow | https://github.com/infiniflow/ragflow.git | `c90fe46c56867b878c38c1b14c991ae9188c7855` | Apache-2.0; `third_party/ragflow/LICENSE:1` | read |
| rag-anything | https://github.com/HKUDS/RAG-Anything.git | `2cd2b3329c470ccb53923f8a6d320596b34e56c5` | MIT; `third_party/rag-anything/LICENSE:1` | read |
| lightrag | https://github.com/HKUDS/LightRAG.git | `aaebfe1bb8d55deb6a4304d357a3bf4c92fcd40a` | MIT; `third_party/lightrag/LICENSE:1` | read |
| unstructured | https://github.com/Unstructured-IO/unstructured.git | `910d9f41e70a17e561797106ef4b9096a8554254` | Apache-2.0; `third_party/unstructured/LICENSE.md:1` | read |
| img2table | https://github.com/xavctn/img2table.git | `fba48730e31debb85581f45d74c5a363b0f728a7` | MIT; `third_party/img2table/LICENSE.txt:1` | read |
| mineru-refine | https://github.com/LcpMarvel/mineru-refine.git | `dbb64eba9ee04edced4407acf662cd7bebbda49d` | MIT; `third_party/mineru-refine/LICENSE:1` | read |
| nuextract | https://github.com/numindai/nuextract.git | `ab9e1a7d22119db76227ed5e1d4ff47f2b448ff9` | MIT; `third_party/nuextract/LICENSE:1` | read |
| llama-index | https://github.com/run-llama/llama_index.git | `619d74664e8404612038bc15a1a40c686037277c` | MIT; `third_party/llama-index/LICENSE:1` | read |
| neo4j-graphrag | https://github.com/neo4j/neo4j-graphrag-python.git | `b7803c6f16e48d4e4843a0890dffdd7dad3b35aa` | Apache-2.0; `third_party/neo4j-graphrag/LICENSE.txt:1` | read |
| docling-serve | https://github.com/docling-project/docling-serve.git | `9c058dbb58f61021e3a16e37edb8a7527b2cb2d4` | MIT; `third_party/docling-serve/LICENSE:1` | read |
| olmocr | https://github.com/allenai/olmocr.git | `f7cfe4c22098b154c76b6ec950d1c0a464eecf8d` | Apache-2.0; `third_party/olmocr/LICENSE:1` | read |
| docling-eval | https://github.com/docling-project/docling-eval.git | `f998acba3d33fe381edf597de602f7a1d3174c1a` | MIT; `third_party/docling-eval/LICENSE:1` | read |
| tika | https://github.com/apache/tika.git | `20676c0c3d0abfef3122cb0c243cb831b3ea536a` | Apache-2.0; `third_party/tika/LICENSE.txt:1` | read |
| dangerzone | https://github.com/freedomofpress/dangerzone.git | `084acfa90673742cb8e64763a30fcea07e6ce9a7` | AGPL-3.0; `third_party/dangerzone/LICENSE:1` | idea-only |
| marker | https://github.com/datalab-to/marker.git | `71dd5fd7e51ab24f8624b6ba2fcb6014b4e40ed4` | Apache-2.0; `third_party/marker/LICENSE:1` | idea-only |
| table-transformer | https://github.com/microsoft/table-transformer.git | `16d124f616109746b7785f03085100f1f6247575` | MIT; `third_party/table-transformer/LICENSE:1` | read |
| chonkie | https://github.com/chonkie-inc/chonkie.git | `664454b689d68614bcfc0b1d57fc2a28b5862825` | MIT; `third_party/chonkie/LICENSE:1` | read |
| dsrag | https://github.com/D-Star-AI/dsRAG.git | `5215e9791133fc1ad383af043fb2fde0e7d4e4d4` | MIT; `third_party/dsrag/LICENSE:1` | read |
| langchain | https://github.com/langchain-ai/langchain.git | `864754c5e293fba981302408fa3e2cf2f5f2d889` | MIT; `third_party/langchain/LICENSE:1` | read |
| data-prep-kit | https://github.com/IBM/data-prep-kit.git | `bbe6608bb1fae641ea1c2c5c62ee2c6b6a92ffbe` | MIT; `third_party/data-prep-kit/LICENSE:1` | read |
| omnidocbench | https://github.com/opendatalab/OmniDocBench.git | `ea2d138c7d2e185feb71ef8014e97d7206820b34` | Apache-2.0; `third_party/omnidocbench/LICENSE:1` | read |
| label-studio | https://github.com/HumanSignal/label-studio.git | `75bdd80a29bb0fb87bfd340efb5e6c4138ede8ec` | Apache-2.0; `third_party/label-studio/LICENSE:1` | read |
| llama.cpp | https://github.com/ggml-org/llama.cpp.git | `e0f142d5ddc1461ce721644d92af33db23545105` | MIT; `third_party/llama.cpp/LICENSE:1` | study-run |
| potatr | https://github.com/kensho-technologies/POTATR.git | `fdb8f57c5124ff27ad7c12bcb976b48a615f1131` | MIT; `third_party/potatr/LICENSE:1` | read |
| witsml | https://github.com/pds-technology/witsml.git | `61e47ce2a0f0bf90bfaf08dc13f9bc361a6cc893` | See licence file; `third_party/witsml/LICENSE.txt:1` | read |
| aws-textract-schema | https://github.com/aws/aws-sdk-go-v2.git | `unavailable` | captured mirror unavailable; final schema read uses botocore below; `results/upstream-snapshot.json` | retrieval attempt |
| azure-di-schema | https://github.com/Azure/azure-rest-api-specs.git | `6e7bc5e131eede910d9eab0c2e260dbba89f8c01` | MIT; `third_party/azure-di-schema/LICENSE:1` | read |
| witsml-schema | https://github.com/pds-technology/devkit-c.git | `f6c5ae85842f40f33d62384572a59671f82d96ff` | Energistics embedded schema terms; agreement unresolved; `third_party/witsml-schema/doc/Standards/energyml/data/witsml/v1.4.1.1/witsml_v1.4.1.1_data/xsd_schemas/obj_drillReport.xsd:1` | read |
| docvortex | https://github.com/myhloli/DocVortex.git | `2de5f42b1884495313d9df63868e6a2f3d85fea0` | MIT; `third_party/docvortex/LICENSE.md:1` | read |

MinerU terms apply across affiliates: separate commercial licensing above 100 million monthly active users or USD20 million total monthly revenue; third-party online services require attribution (`third_party/mineru/LICENSE.md:3-23`). Marker remains idea-only even though its pinned code licence changed to Apache-2.0. Its weight rights were not established from a permitted pinned model card, so no weight use is approved. The WITSML wrapper licence does not override Energistics schema terms. Neo4j also carries bundled notices; dependency freezes are evidence of versions, not licence clearance.

## Weights and model cards

Only the <=7B local models selected by the run scripts were executed. Read-only cards do not imply execution. Cached-model pins and runtime differences are recorded in `results/runtime/cached-models.json` and each run result. Card metadata is quoted as recorded, not expanded into a broader grant.

| Model / resource | Revision | Recorded card licence | Evidence / use |
|---|---|---|---|
| [opendatalab/MinerU2.5-Pro-2604-1.2B](https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B) (mineru-pro) | `d3f5e08d073c21466bbabe21c71bb1e9c2e595da` | apache-2.0 | `third_party/models/mineru-pro/README.md:1`; card read; execution identified separately |
| [mradermacher/MinerU2.5-Pro-2604-1.2B-GGUF](https://huggingface.co/mradermacher/MinerU2.5-Pro-2604-1.2B-GGUF) (mineru-gguf) | `70429e9c728b6a5e904f358a9936c17bd3f5f4b8` | apache-2.0 | `third_party/models/mineru-gguf/README.md:1`; downloaded GGUF |
| [PaddlePaddle/PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) (paddle-vl) | `c5630abae1d940eafe0697512a0325494b02ab42` | apache-2.0 | `third_party/models/paddle-vl/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PaddleOCR-VL-1.6-GGUF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF) (paddle-gguf) | `511b09642bb324401f15f97cc23bc67e8f0a291d` | apache-2.0 | `third_party/models/paddle-gguf/README.md:1`; downloaded GGUF |
| [docling-project/TableFormerV2](https://huggingface.co/docling-project/TableFormerV2) (tableformer-v2) | `e41ba5da7ef69004f4b329168791c2987abf917c` | apache-2.0 | `third_party/models/tableformer-v2/README.md:1`; card read; execution identified separately |
| [docling-project/docling-models](https://huggingface.co/docling-project/docling-models) (docling-models) | `2199320848bb9a8a519d22e4b528185a4f9a6f64` | cdla-permissive-2.0, apache-2.0 | `third_party/models/docling-models/README.md:1`; card read; execution identified separately |
| [docling-project/docling-layout-heron](https://huggingface.co/docling-project/docling-layout-heron) (docling-layout) | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | apache-2.0 | `third_party/models/docling-layout/README.md:1`; card read; execution identified separately |
| [kensho/POTATR-v1.1-Pub](https://huggingface.co/kensho/POTATR-v1.1-Pub) (potatr) | `4f853618bb4393a191ac1cd45ae86e2774b37c3a` | mit | `third_party/models/potatr/README.md:1`; card read; execution identified separately |
| [numind/NuExtract-2.0-4B](https://huggingface.co/numind/NuExtract-2.0-4B) (nuextract-4b) | `f431a46f97b9ffb650fde4992deb58d2265e5c0d` | mit | `third_party/models/nuextract-4b/README.md:1`; card read; execution identified separately |
| [microsoft/layoutxlm-base](https://huggingface.co/microsoft/layoutxlm-base) (layoutxlm) | `8e04ebc4d3ba0013cf943b697c0aedf19b06472a` | cc-by-nc-sa-4.0 | `third_party/models/layoutxlm/README.md:1`; card read; execution identified separately |
| [numind/NuExtract-2.0-2B](https://huggingface.co/numind/NuExtract-2.0-2B) (nuextract-2b) | `5eb4a99746edc2ac44900f56a5c9431d3c03b16d` | mit | `third_party/models/nuextract-2b/README.md:1`; card read; execution identified separately |
| [opendatalab/MinerU-4_models_onnx](https://huggingface.co/opendatalab/MinerU-4_models_onnx) (mineru-onnx) | `358310b4f64b95f9fefc372ad899356e4111f376` | No card-level grant; inspect component terms | `third_party/models/mineru-onnx/README.md:1`; card read; execution identified separately |
| [opendatalab/MinerU2.5-Pro-2605-1.2B](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) (mineru-pro-2605) | `08aaea840498d49ce16247b6263196cf02814885` | apache-2.0 | `third_party/models/mineru-pro-2605/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3) (paddle-layout) | `241f8bdfc77a7c7bee915a5057aaee58c235a8d3` | apache-2.0 | `third_party/models/paddle-layout/README.md:1`; card read; execution identified separately |
| [docling-project/docling-layout-heron](https://huggingface.co/docling-project/docling-layout-heron) (executed-docling-layout-heron) | `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | apache-2.0 | `third_party/models/executed-docling-layout-heron/README.md:1`; card read; execution identified separately |
| [docling-project/docling-models](https://huggingface.co/docling-project/docling-models) (executed-docling-models) | `fc0f2d45e2218ea24bce5045f58a389aed16dc23` | cdla-permissive-2.0 | `third_party/models/executed-docling-models/README.md:1`; card read; execution identified separately |
| [docling-project/TableFormerV2](https://huggingface.co/docling-project/TableFormerV2) (executed-TableFormerV2) | `e41ba5da7ef69004f4b329168791c2987abf917c` | apache-2.0 | `third_party/models/executed-TableFormerV2/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-DocLayoutV2_onnx](https://huggingface.co/PaddlePaddle/PP-DocLayoutV2_onnx) (component-PaddlePaddle--PP-DocLayoutV2_onnx) | `7d44592493df02e28110d99de8ca4b1fbc7309bd` | apache-2.0 | `third_party/models/component-PaddlePaddle--PP-DocLayoutV2_onnx/README.md:1`; card read; execution identified separately |
| [opendatalab/MinerU-4_models_torch](https://huggingface.co/opendatalab/MinerU-4_models_torch) (component-opendatalab--MinerU-4_models_torch) | `2b3afb86f4d23fa623f6b2f4b2279ed4ef93a89d` | apache-2.0 | `third_party/models/component-opendatalab--MinerU-4_models_torch/README.md:1`; card read; execution identified separately |
| [jinzhenj/PP-FormulaNet_plus-M_onnx](https://huggingface.co/jinzhenj/PP-FormulaNet_plus-M_onnx) (component-jinzhenj--PP-FormulaNet_plus-M_onnx) | `9eb491f62e52f45571fbf88f4d0335e4eb36f9b9` | apache-2.0 | `third_party/models/component-jinzhenj--PP-FormulaNet_plus-M_onnx/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-OCRv6_small_rec_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx) (component-PaddlePaddle--PP-OCRv6_small_rec_onnx) | `b8f84f0b80c529de40b4fbb3544b84fa7233a513` | apache-2.0 | `third_party/models/component-PaddlePaddle--PP-OCRv6_small_rec_onnx/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-OCRv6_tiny_det_onnx](https://huggingface.co/PaddlePaddle/PP-OCRv6_tiny_det_onnx) (component-PaddlePaddle--PP-OCRv6_tiny_det_onnx) | `2ba1506c0380b8f0b03dd142459aac66d4421f6c` | apache-2.0 | `third_party/models/component-PaddlePaddle--PP-OCRv6_tiny_det_onnx/README.md:1`; card read; execution identified separately |
| [numind/NuExtract-2.0-2B](https://huggingface.co/numind/NuExtract-2.0-2B) (component-numind--NuExtract-2.0-2B) | `fe5b2f0b63b81150721435a3ca1129a75c59c74e` | mit | `third_party/models/component-numind--NuExtract-2.0-2B/README.md:1`; card read; execution identified separately |
| [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (component-sentence-transformers--all-MiniLM-L6-v2) | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | apache-2.0 | `third_party/models/component-sentence-transformers--all-MiniLM-L6-v2/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-DocBlockLayout](https://huggingface.co/PaddlePaddle/PP-DocBlockLayout) (paddle-component-PP-DocBlockLayout) | `f270657da59d956ab69ffc2c4722fe1f557bf17b` | apache-2.0 | `third_party/models/paddle-component-PP-DocBlockLayout/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3) (paddle-component-PP-DocLayoutV3) | `241f8bdfc77a7c7bee915a5057aaee58c235a8d3` | apache-2.0 | `third_party/models/paddle-component-PP-DocLayoutV3/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-DocLayout_plus-L](https://huggingface.co/PaddlePaddle/PP-DocLayout_plus-L) (paddle-component-PP-DocLayout_plus-L) | `aa52b8528c84f9b1a34ac3a88fe0e576edb9d11d` | apache-2.0 | `third_party/models/paddle-component-PP-DocLayout_plus-L/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-FormulaNet_plus-L](https://huggingface.co/PaddlePaddle/PP-FormulaNet_plus-L) (paddle-component-PP-FormulaNet_plus-L) | `0809597a77f735bfb35354edb632f2e6dff606f3` | apache-2.0 | `third_party/models/paddle-component-PP-FormulaNet_plus-L/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-LCNet_x1_0_table_cls](https://huggingface.co/PaddlePaddle/PP-LCNet_x1_0_table_cls) (paddle-component-PP-LCNet_x1_0_table_cls) | `2fa6323e7dab88fa883081db1460995f46af2922` | apache-2.0 | `third_party/models/paddle-component-PP-LCNet_x1_0_table_cls/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-LCNet_x1_0_textline_ori](https://huggingface.co/PaddlePaddle/PP-LCNet_x1_0_textline_ori) (paddle-component-PP-LCNet_x1_0_textline_ori) | `cd237a44b0e359d4fe38310a416203cf7403faa5` | apache-2.0 | `third_party/models/paddle-component-PP-LCNet_x1_0_textline_ori/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-OCRv5_server_det](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det) (paddle-component-PP-OCRv5_server_det) | `ca867c897ecbca8873081573a802ad70d499cb94` | apache-2.0 | `third_party/models/paddle-component-PP-OCRv5_server_det/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/PP-OCRv5_server_rec](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec) (paddle-component-PP-OCRv5_server_rec) | `b26c3587fda8da3c8ec0ce357214b4d661ff1558` | apache-2.0 | `third_party/models/paddle-component-PP-OCRv5_server_rec/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/RT-DETR-L_wired_table_cell_det](https://huggingface.co/PaddlePaddle/RT-DETR-L_wired_table_cell_det) (paddle-component-RT-DETR-L_wired_table_cell_det) | `e2bd53c06b3a815d86acbf5c6779dada58819cfe` | apache-2.0 | `third_party/models/paddle-component-RT-DETR-L_wired_table_cell_det/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/RT-DETR-L_wireless_table_cell_det](https://huggingface.co/PaddlePaddle/RT-DETR-L_wireless_table_cell_det) (paddle-component-RT-DETR-L_wireless_table_cell_det) | `25ca86356a601c877476bb0dcc5fd09153d9d64d` | apache-2.0 | `third_party/models/paddle-component-RT-DETR-L_wireless_table_cell_det/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/SLANet_plus](https://huggingface.co/PaddlePaddle/SLANet_plus) (paddle-component-SLANet_plus) | `bae6e5f8c3c4e7da0c0b7639fdf3228fe76184e2` | apache-2.0 | `third_party/models/paddle-component-SLANet_plus/README.md:1`; card read; execution identified separately |
| [PaddlePaddle/SLANeXt_wired](https://huggingface.co/PaddlePaddle/SLANeXt_wired) (paddle-component-SLANeXt_wired) | `763069fcda6a065f2171753205a32bf899a88d15` | apache-2.0 | `third_party/models/paddle-component-SLANeXt_wired/README.md:1`; card read; execution identified separately |

TableFormerV2 is explicitly a preview with Apache-2.0 weights (`third_party/models/tableformer-v2/README.md:2-17`). The original LayoutXLM card is CC-BY-NC-SA-4.0 and is not a commercial KIE recommendation. MinerU ONNX assets retain original component terms; provenance is in `third_party/models/mineru-onnx/manifest.json:1`. EasyOCR model binaries were reused from the existing repository cache; independent weight-licence verification remains unresolved. That limitation applies to standard Docling and local hybrid results and is a deployment gate, not a reason to alter the observed results.

## Standards, service schemas and papers

| Source | Pin / URL | Recorded terms | Use |
|---|---|---|---|
| AWS Textract SDK schema | https://github.com/boto/botocore, `7f517a30f80daa50e2ab84c9b1cfa073c4d8cf58` | Apache-2.0 SDK; `third_party/aws/LICENSE.txt:1` | read only |
| OSDU data definitions | https://community.opengroup.org/osdu/data/data-definitions, `ff89d87caa43d05d1341dcaa6d258e1186ec8aa6` | Apache-2.0; `third_party/osdu/LICENSE:1` | read only |
| NuExtract3 | https://huggingface.co/numind/NuExtract3, `c99dc8f5641b866aa0192b6ea78f84bf9f3535f1` | Apache-2.0 model; `third_party/nuextract3/LICENSE:1` | read only |
| pubtables-v2 | https://arxiv.org/abs/2512.10888v3 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| potatr | https://arxiv.org/abs/2606.09788v1 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| monkeyocr | https://arxiv.org/abs/2511.10390v2 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| agentar-fin-ocr | https://arxiv.org/abs/2603.11044v2 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| tableparsemap | https://arxiv.org/abs/2608.09842v1 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| smoldocling-kv | https://arxiv.org/abs/2608.20868v1 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| tabular-chunking | https://arxiv.org/abs/2605.00318v1 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| mpdocbench | https://arxiv.org/abs/2605.22100v2 | Paper reading/citation only; no code, weight or dataset rights inferred | read |
| Queiroz daily-report ontology | https://doi.org/10.2118/223801-MS; repository `docs/references.md:27-39` | Full text/terms unavailable | bibliography only |
| Anthropic contextual retrieval | https://www.anthropic.com/news/contextual-retrieval | Host outside permitted network scope; not retrieved; terms unresolved | reading gap; dsRAG source used separately |
| Red Hat Docling/Ray | https://developers.redhat.com/articles/2026/06/30/scale-document-ingestion-docling-and-ray-openshift-ai | Host outside permitted network scope; not retrieved; terms unresolved | reading gap; data-prep-kit source used separately |
| OmniParseBench article | https://app.datalab.to/blog/open-ocr-models-omniparsebench | Host outside permitted network scope; not retrieved; terms unresolved | reading gap |

The llama.cpp prebuilt runtime is separately pinned to b12000 in `configs/inputs.lock.json`, including archive SHA-256; its source checkout is a different revision and is not claimed to reproduce that binary. PDF inputs retain the repository source registries and SHA-256 pins in `configs/pages.json`; no redistribution right beyond the existing dataset terms is inferred.

## Windows OCR follow-up assets

| Project | Pinned version / revision | Recorded licence | Use |
|---|---|---|---|
| [Tesseract Windows build](https://github.com/UB-Mannheim/tesseract/releases/tag/v5.4.0.20240606) | 5.4.0.20240606; installer SHA256 in `configs/inputs.lock.json` | Apache-2.0 from extracted `doc/LICENSE`, retained as `results/licenses/tesseract-LICENSE.txt`; bundled DLL terms are not inferred from this licence | study-run, extracted under `.cache/tesseract/`; no installer execution |
| [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) English and orientation models | `87416418657359cb625c412a48b6e1d6d41c29bd` | Apache-2.0 from `third_party/tessdata_fast/LICENSE:1-5` and model card `third_party/tessdata_fast/README.md:62-63`; bundled eng/osd byte hashes match this revision (`results/runtime.json`) | local OCRmyPDF ak3-scanned-well-schematic/ak3-scanned-permit-letter |
| [7-Zip](https://github.com/ip7z/7zip/releases/tag/26.05) extraction utilities | 26.05; downloaded executable hashes in `configs/inputs.lock.json` | Distribution licence lists LGPL, BSD portions and unRAR restrictions; read `results/licenses/7zip-LICENSE.txt` (lines 8-17); the standalone 7zr helper licence has not been established from a licence file | archive extraction only; binaries ignored |

The pinned native installer is a source archive for this experiment: `scripts/tools/setup_native.py` extracts its payload without running setup, registering programs or changing system PATH. Harness PATH/TESSDATA_PREFIX changes are process-local. The English and orientation weights were compared byte-for-byte with the pinned upstream files. Additional reference cards for tessdata and tessdata_fast are pinned in `configs/inputs.lock.json`; no weight licence is inferred from the OCRmyPDF MPL code licence. Measured commands, hashes and versions are in `results/runtime.json`; dependency DLL licences remain a packaging-review gap.

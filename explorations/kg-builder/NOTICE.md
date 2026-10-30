# Notices and acknowledgements

Project licence: **TBD by repository owner**.

Upstream repositories are not bundled. The following recorded licences describe the pinned sources; verify their exact licence and attribution requirements before redistribution. Core integration, evaluation support and design reference are different uses, not claims that every upstream system runs in this project.

| Project | Pinned commit | Recorded licence | Use |
| --- | --- | --- | --- |
| [kg-gen](https://github.com/stair-lab/kg-gen) | `6259b4c71523ceae75dafb4acec2eb833bef8f8e` | MIT (pyproject only, no LICENSE file) | core |
| [edc](https://github.com/clear-nus/edc) | `02aad17e2fc1e9845c84746b384e7fd3160edc1a` | MIT | core |
| [autoschemakg](https://github.com/HKUST-KnowComp/AutoSchemaKG) | `d0a1666ae6621806faf814504c73678de4e809f2` | MIT | core |
| [graphjudge](https://github.com/hhy-huang/GraphJudge) | `0ae5913d49d8b530c254cbc0cefa71a57d107bb5` | MIT | core |
| [hipporag](https://github.com/OSU-NLP-Group/HippoRAG) | `d5c8329422e0a0b834a15874545cb6a74b4f9b26` | MIT | eval |
| [lightrag](https://github.com/HKUDS/LightRAG) | `aaebfe1bb8d55deb6a4304d357a3bf4c92fcd40a` | MIT | eval |
| [graphrag-benchmark](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark) | `fdbab5959b18c96532580877ffe27d112bccc0ec` | MIT | eval |
| [graphiti](https://github.com/getzep/graphiti) | `3cc723cd292eb5c2ac5ea2c5539270b8e1b6389f` | Apache-2.0 | reference |
| [autograph-r1](https://github.com/HKUST-KnowComp/AutoGraph-R1) | `18d446bfe75c9c5acf70431c7c49f439909dea99` | MIT | reference |
| [genie](https://github.com/epfl-dlab/GenIE) | `c53d52f598c2940e00f753c97b3baf4ba144fc03` | MIT | reference |
| [graphrag](https://github.com/microsoft/graphrag) | `5faaaf4f5685fa2056fa8c3bf9342cb089f2942f` | MIT | reference |
| [gliner](https://github.com/urchade/GLiNER) | `f3c945702b9b5cde381c27b95310c47909bcfd80` | Apache-2.0 | minitest |
| [gliner2](https://github.com/fastino-ai/GLiNER2) | `ca4f68235b50fe4c3ecf3876851d748fe4b15c6c` | Apache-2.0 | minitest |

KGGen supplies extraction and resolution support; EDC supplies relation definition/canonicalization and its WebNLG evaluator. AutoSchemaKG and GraphJudge inform schema-induction and evidence-judging prompts. HippoRAG supplies the QA metric. Other repositories are reference or optional evaluation material. Changes are implemented in local adapters without modifying upstream source.

Datasets include WebNLG, 2WikiMultiHopQA, MINE and public BSEE records. See [datasets and licences](docs/datasets-and-licenses.md) for provenance and unresolved dataset rights. BSEE annotations are LLM-generated and adjudicated, not human expert labels.

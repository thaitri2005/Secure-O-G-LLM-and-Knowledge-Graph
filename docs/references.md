# Related work and reference material

**Updated:** 25 October 2026

This page records the papers and resources the supervisor pointed to, what we could verify about them, and what they mean for the design. "Verified" means we read the item or a bibliographic record of it. Summaries of abstracts are paraphrased and are not a substitute for reading the papers.

## Items from the supervisor

| Link | Access status | What it is |
|---|---|---|
| [OnePetro SPEDC 25DC, paper 642469](https://onepetro.org/SPEDC/proceedings-abstract/25DC/25DC/642469) | **Not opened.** OnePetro returns HTTP 403 to automated access, and search engines do not index this ID. | A paper from the 2025 SPE/IADC International Drilling Conference and Exhibition (code 25DC; Stavanger, March 2025). Probably the ontology paper below; see the identification note. |
| [EarthDoc DOI 10.3997/2214-4609.202610838](https://www.earthdoc.org/content/papers/10.3997/2214-4609.202610838) | **Not opened.** EarthDoc returns HTTP 403; doi.org and Crossref return 404, so the DOI may not be registered yet. | An EAGE conference proceedings paper (the `2214-4609` series); the `2026…` suffix suggests a 2026 event. Title and authors unknown. |
| [Utah FORGE project data dashboard](https://utahforge.com/project-data-dashboard/) | **Partly verified** through a search-indexed copy. Direct retrieval failed TLS certificate verification. | Overview of FORGE wells and data, with a downloadable general well dataset; the data itself is published on the GDR. See [Data sources §3](DATA_SOURCES.md#3-utah-forge-reference-material). |
| [BSEE Data Center – Wells Information](https://catalog.data.gov/dataset/bsee-data-center-wells-information) | **Verified and ingested.** | See [Data sources §1](DATA_SOURCES.md#1-bsee-data-center--wells-information) and [BSEE ingestion](bsee-ingestion.md). |
| [AK-3 End of Well Report](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf) | **Verified and ingested.** | See [Data sources §2](DATA_SOURCES.md#2-akutan-ak-3-end-of-well-report-the-document-exemplar). |

**Action for the team.** Someone with OnePetro and EarthDoc access (for example through the library) should open both links and fill in the bibliographic record and three to five takeaways below. Until then, do not cite either paper for a specific claim.

### OnePetro 642469: identification note

Searching the 25DC proceedings for LLM, knowledge-graph and ontology work on drilling reports found two candidates:

1. **Queiroz, J., Jaculli, M. A., Choueri Junior, N., Silveira, I. M., Mendes, J. R. P., Penteado, B. E., Guilherme, I. R., Perrout, S. R.** *An Ontology of Well Engineering Entities to Extract and Structure Text Data from Daily Reports.* SPE/IADC International Drilling Conference and Exhibition, March 2025. SPE-223801-MS, [doi:10.2118/223801-MS](https://doi.org/10.2118/223801-MS). Bibliographic record and abstract: [UNESP repository](https://repositorio.unesp.br/entities/publication/f35e60d3-b982-4d2b-b8ea-b4c54b9ae343).
   - *Abstract, paraphrased:* daily operational reports are a large, mostly textual data source. The authors propose a well-engineering ontology to guide extraction from these reports into knowledge graphs and to support retrieval, because LLMs and embedding methods lack domain structure. The ontology is aligned with upper-level ontologies and industry standards such as ISO 15926. The paper covers its construction and applications: named-entity recognition, incident visualization, operation classification, report templates and auto-filling, drilling-metric calculation, and report queries.
2. **Al Amin et al.** *LLM-In-The-Loop: A Framework for Enhancing Drilling Data Analytics.* Same conference, SPE-223805-MS ([OnePetro 642548](https://onepetro.org/SPEDC/proceedings-abstract/25DC/25DC/642548)). The framework retrieves relevant information and similar example pairs and adds them to the LLM prompt with the user query.

Candidate 1 matches the project's topic most closely, and its OnePetro ID is near that of candidate 2. That is circumstantial: **confirm the identity before relying on it.**

## Takeaways for this project (provisional)

These follow from the abstracts above. Revisit them once the full papers are read.

| Observation | Effect on our design |
|---|---|
| A published well-engineering ontology for daily reports exists and is aligned with ISO 15926 | Before inventing class names for the AK-3 ontology draft, compare them with this ontology. Keep a mapping column in the ontology file. The design still avoids full OWL reasoning in the first release ([design §6](PROJECT_DESIGN.md#6-ontology-and-domain-adaptation)). |
| Daily operational reports are treated as the main text source; applications include operation classification and drilling metrics | The AK-3 appendix portfolio contains daily reports. They are a natural second document type after the EOW report, and a source for productive versus non-productive time claims. |
| LLM frameworks for drilling data rely on retrieving similar examples into the prompt | Compatible with our design when the retrieved examples are reviewed, versioned inputs. Answers still come from accepted graph claims, not from free generation ([design §8](PROJECT_DESIGN.md#8-question-answering)). |

## Other related work found while searching (not reviewed in full)

These appeared in searches for the items above and may be useful background. None has been read in full.

- *Using Knowledge Graphs to Analyze Geomechanical Events in Daily Drilling Reports.* Springer, 2025, [doi:10.1007/978-3-031-99554-5_48](https://doi.org/10.1007/978-3-031-99554-5_48). Combines NLP, ontologies and knowledge graphs to extract geomechanical events and their context; cites the Queiroz ontology.
- *Digitization of Daily Drilling Reports Using LLMs.* SPE Middle East Oil, Gas and Geosciences Show 2025, SPE-227059-MS ([OnePetro](https://onepetro.org/SPEMEOS/proceedings-abstract/25MEOS/25MEOS/790010)).
- *Agentic Retrieval Augmented Generation for Drilling.* ADIPEC 2025 ([OnePetro](https://onepetro.org/SPEADIP/proceedings-abstract/25ADIP/25ADIP/D021S081R003/792938)). Combines knowledge graphs with retrieval in a conversational interface.
- *Leveraging large language models for automated knowledge extraction from geological reports.* Journal of Rock Mechanics and Geotechnical Engineering, 2026 ([ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1674775526001216)). Benchmarks LLMs on knowledge-graph construction and question answering over geological reports.
- *From Data to Decision-Making: A Review of Large Language Model Applications Across the Full Lifecycle of Geothermal Resource Development.* Energies 19(21), 5052 ([MDPI](https://www.mdpi.com/1996-1073/19/21/5052)). Notes that knowledge-graph and retrieval frameworks in geothermal work are mostly proposals rather than implemented systems.

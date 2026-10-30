# BSEE domain

The table pipeline models wells, boreholes, areas, blocks, leases and companies. The extended bundle adds operations reports and observations. Source keys, regional identity and unresolved links remain explicit; an unresolved relationship is not fabricated. Narrative ingestion retains original text and source serials.

The text ontology covers 21 well-operation relations plus `other`. Subjects include boreholes, tubulars, plugs, equipment, annuli, zones, rigs, companies and fluids. Literal objects include depth, interval, pressure, density, size, volume, date, status and text. The authoritative definitions are in `contracts/ontology/bsee.yaml`; do not alter them as part of documentation or filename changes.

Depth unit, reference and datum are separate. Do not equate MD and TVD or convert feet to metres implicitly. A bare foot mark gives the unit but not the reference. Numbers in geological or equipment names are part of the name, not measurements. Damaged characters remain in the source; parsing must not silently repair them. Pressure-context rules distinguish pressure from tubular weight.

Table-derived silver covers answerable source fields only. Deterministic rule outputs and graph conversion are additional measurement layers, not human labels. Guided extraction narrows the relation space; recall variants use windows, relation groups or a second pass. Stage attribution separates extraction omissions, canonicalization losses, conversion errors, resolution changes and export filtering.

The corpus selection includes documented PII screening. Selected narratives were intended to exclude person names, but screening counts are not proof that no PII exists. Annotation instructions mark a missed person-containing chunk unreadable without copying the name. Public availability of a source does not settle every redistribution question; see [datasets and licences](datasets-and-licenses.md).

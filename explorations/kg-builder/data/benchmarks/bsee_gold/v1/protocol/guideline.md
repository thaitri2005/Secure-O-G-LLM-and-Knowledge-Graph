# M7 annotation guideline — BSEE well-operation facts (AI-gold v1)

> Two independent LLM annotators from different model families (annotator A, annotator B) labelled every chunk; an LLM adjudicator resolved disagreements. This is an LLM-annotated benchmark, not human expert labels.
>
> Version `v1`, amendment 1. The file is byte-copied to `data/benchmarks/bsee_gold/v1/protocol/guideline.md` and its SHA-256 is written into `freeze.json` before any annotation starts. Problems found during annotation or adjudication go into `notes`/`rationale` fields and into a v2 later; v1 changes only through a recorded freeze amendment (`kgb domain gold amend`, tasks.md D62). Amendment 1 (2026-10-25) states `-` as an accepted date separator (§3.2) and adds the stop-and-report rule and the `amendments/` folder to §10; no other rule changed.
>
> The examples quote short excerpts of the retained scouting samples (`.cache/domain_probe/samples/`, identified by their report serial `SN_EOR` / `SN_WAR`). Person names are replaced by `[PERSON]`. This file is part of the AI-gold protocol (byte-copied into `protocol/`), collects 22 identified sample excerpts, and is excluded from the ZIP package (m7_plan.md D-M7-19).

## 1. The task in one paragraph

You get one chunk of a BSEE End-of-Operations-Report narrative (EOR) as plain text. List **every fact the text states** that fits one of the 21 relations in §4, with exact text spans. Use only the chunk text: no outside knowledge, no BSEE tables, no web, no guessing what an operator "probably" did. When a fact is clear but no relation fits, use `other` (§4.3). When a value is incomplete (unit, depth reference, year), write `unknown` for that part instead of inventing it. A chunk with no fact gets a `chunk` record with status `no_facts`.

## 2. Units and spans

- **Unit of annotation:** one chunk (`chunk_id`). Each chunk of the v1 set is a whole EOR narrative (single-chunk documents; m7_plan.md D-M7-18).
- **Span** = an exact substring of the packet's `text` field, copied character for character (keep odd characters such as `¿`, doubled spaces, `""` that became `"`). Give the substring as `text` plus `occ`, the 0-based index of that occurrence in the chunk (search order: Python `str.find`, each next search starts at previous start + 1). `start`/`end` (code-point offsets, end exclusive) are optional; if you give them, they must agree with `text`/`occ`. The validator (`kgb domain gold validate`) resolves and checks every span.
- **Subject.** Use an explicit span when the text names the thing (`CIBP`, `5.5" liner`, `A annulus`). When the subject is the well the report is about and the text does not name it ("Recompleted to the MP-3E sand."), use the implicit subject `{"implicit": "report_well", "type": "Borehole"}`. "the well", "wellbore", "this well" and a well name such as `A002` are explicit spans of the report well: write them as `{"text": ..., "occ": ..., "type": "Borehole", "role": "report_well"}` (§8; `role` is allowed only with `type: Borehole`, and the evaluator treats it like the implicit subject). Only the report well may be implicit.
- **Object.** Always an explicit span. No object span → no fact (for example "set cement plug" with no depth is not a `set_plug_at` fact).
- **Evidence.** The shortest sentence or clause that states the fact; it must contain the object span and, if explicit, the subject span.

## 3. Entity types and literal kinds

### 3.1 Entity types (subjects and entity objects)

| Type | Covers | Examples |
|---|---|---|
| `Borehole` | the report well or another named well/wellbore/sidetrack | "the well", "Wellbore", `A002`, `D2` |
| `Tubular` | casing, liner, conductor, tubing strings (long string `LS`, short string `SS`), drill pipe | `9-5/8" casing`, `5.5" liner`, `30" stub`, `LS` |
| `Plug` | cement plug, bridge plug, CIBP, EZSV/retainer used as a plug, DX/XRXX plug, TTBP, balanced plug | `CIBP`, `DX plug`, `600' balanced cement plug` |
| `Equipment` | packer, nipple, SCSSV, tree, BOP, lubricator, tubing stop, perforating gun, hanger; also TOC, fill, fish or an obstruction as the subject of `tagged_at` (§4.1 row 10) | `isolation packer`, `X-nipple`, `lubricator`, `QTS` |
| `Annulus` | an annulus | `A annulus`, `C annulus` |
| `Zone` | sand, reservoir, formation, geologic marker, completion interval name | `MP-3E sand`, `Rob (L)-5 sand`, `Tex W-2 sand` |
| `Rig` | rig, lift boat, rig type when named | `L/B Brazos`, `platform rig` |
| `Company` | operator or service company named in text | `NOEX` |
| `Fluid` | mud, brine, cement slurry, pill | `16.2 ppg CT Blend cement`, `CaBr2` |

Never annotate people. A person name is not an entity of this ontology; chunks with person names are screened out before the freeze (m7_plan.md T31), and for any that slip through write only the `chunk` record with `status: "unreadable"`, `n_facts: 0`, `note: "person name present"` (no fact records; never copy the name). Unreadable chunks are counted but not scored (m7_plan.md §5.2).

### 3.2 Literal kinds (objects)

| `kind` | Fields | Unit values | Rules |
|---|---|---|---|
| `depth` | `value`, `unit`, `reference`, `datum` | `ft`, `m`, `unknown` | `'`, `ft`, `feet` → `ft`. `value` without thousands separators ("11,640" → `11640`). |
| `interval` | `lower`, `upper`, `unit`, `reference`, `datum` | as depth | Expand shorthand: "13202'-24'" → 13202–13224; "11884'-950'" → 11884–11950 (the short upper end takes the leading digits of the lower end). `lower <= upper`. |
| `pressure` | `value`, `unit` | `psi`, `unknown` | `psi`, `psig`, and `#` **after a pressure verb** ("tested to 1000#", "bleed to 0#") → `psi`. |
| `density` | `value`, `unit` | `ppg`, `unknown` | `ppg`, `lb/gal`; "EMW" is a density. |
| `size` | `value`, `unit` | `in`, `unknown` | `"` → `in`. Fractions to exact decimal: `9-5/8"` → `9.625`, `13 3/8"` → `13.375`, `2-9/16"` → `2.5625`, `5.5"` → `5.5`. Composite hole sizes ("16.5 x 19"") are not sizes of a tubular; use the `hole_size` qualifier. |
| `volume` | `value`, `unit` | `bbl`, `sx`, `cuft`, `gal`, `unknown` | "24 bbls" → `24 bbl`; "42 sx" → `42 sx`; "387 cu ft" → `387 cuft`. |
| `date` | `iso`, `precision` | — | US order M/D/Y. The separator is `/` or `-`, the same one in both places: "3/14/2011", "3-14-2011" and "3-14-11" → `2011-03-14`, `day`; a mixed form ("3/14-11") is not a full date (`iso: null`, `partial`). Two-digit years: 00–49 → 20xx, 50–99 → 19xx. `precision`: `day`, `month`, `year`, or `partial` (month/day without year, "3/14" or "3-14": `iso: null`). Never borrow a year from elsewhere in the chunk. |
| `status` | `value` | — | Closed set: `TA` temporarily abandoned, `PA` permanently abandoned, `COM` completed/recompleted, `ST` plugged back for sidetrack / sidetracked, `BP` bypassed, `SI` shut in, `other`. |
| `entity` | `type` | — | One of §3.1. |
| `text` | `value` | — | Free normalized text, only for `casing_spec` (e.g. `23 lb/ft P-110`). |

**Depth reference and datum.** `reference` ∈ `MD`, `TVD`, `BML` (below mudline), `AML` (above mudline), `unknown`. `datum` ∈ `KB` (KB, KBM, RKB), `SLM`, `CTM`, `WLM`, `DPM`, `ML` (mudline), `unknown`.
- Text says `MD`/`md` → `MD`; `TVD`/`tvd` → `TVD`; `BML`/`AML` → that reference (and datum `ML`).
- The along-hole measurement tokens `SLM`, `CTM`, `WLM`, `DPM` (also `dpm`) imply `reference: MD`, datum = the token.
- `KB`/`KBM`/`RKB` alone give the datum only; `reference` stays `unknown`.
- A bare `'` gives `unit: ft`, `reference: unknown`. Never assume MD = TVD. Never convert ft ↔ m.
- "13243' MD/12625' TVD" is **two** facts (one MD, one TVD), never one.

**`#` has two meanings.** After a pressure verb or "@ … #" in a test context it is psi; in a tubular description ("5.5", 23#, P-110 liner") it is lb/ft and belongs in `casing_spec`. If you cannot tell, `unit: unknown`, `uncertainty: uncertain`.

**Damaged characters.** Some narratives contain `¿` where a quote or foot mark was lost ("13007¿"). Copy it as is, set `unit: unknown` and `uncertainty: uncertain`. The corpus never repairs text.

**Numbers inside names.** "BN 7300' Sand", "B-1 Sand-200", "MP 107 D2" are names. Do not extract their numbers as depths.

## 4. Relations (21 + `other`)

### 4.1 Table

| # | Relation | Subject type | Object kind | Allowed qualifiers | Definition (for the annotator and for `contracts/ontology/bsee.yaml`) |
|---|---|---|---|---|---|
| 1 | `spudded_on` | Borehole | date | — | The subject well was spudded (drilling started) on the object date. |
| 2 | `reached_td` | Borehole | depth | `bound`, `correction` | The subject well reached its total depth (TD) at the object depth. Only when the text says TD/total depth of the well. |
| 3 | `drilled_to` | Borehole | depth | `hole_size`, `bound` | The subject well was drilled to the object depth (an intermediate or section depth, including "section TD"). |
| 4 | `set_casing_at` | Tubular | depth | `correction`, `bound` | The subject casing, liner or conductor was set, landed or run to the object depth (shoe or setting depth). |
| 5 | `casing_size` | Tubular | size | — | The subject tubular has the object outside diameter. |
| 6 | `casing_spec` | Tubular | text | — | The subject tubular has the object weight and/or grade (e.g. "23 lb/ft P-110"). |
| 7 | `cemented_interval` | Tubular, Annulus, Borehole | depth or interval | `volume`, `toc` (bool) | Cement was placed behind or in the subject over the object interval, or its top of cement (TOC) is at the object depth (`toc: true`). Cement **plugs** use `set_plug_at`. |
| 8 | `set_plug_at` | Plug | depth or interval | `action` | The subject plug was set or placed at the object depth or over the object interval. `action`: `set`, `placed`, `replaced`. |
| 9 | `set_equipment_at` | Equipment | depth | `action` | The subject packer, nipple, valve, tubing stop, hanger or retainer was set or is located at the object depth. `action`: `set`, `located`. |
| 10 | `tagged_at` | Plug, Equipment, Fluid | depth | — | A tool tagged the subject (plug, TOC, fill, fish, obstruction) at the object depth. For TOC, fill, fish or an obstruction use the subject span as written with type `Equipment` and `note` = `toc`, `fill`, `fish` or `obstruction`. |
| 11 | `cut_at` | Tubular, Equipment | depth | `bound` | The subject was cut (and possibly pulled) at the object depth (often BML). |
| 12 | `tested_to_pressure` | Equipment, Tubular, Plug, Annulus, Borehole | pressure | `test_kind`, `duration`, `result`, `stage` | The subject was pressure-tested to the object pressure. Only tests, not operating, bleed or pump pressures. |
| 13 | `fit_lot_emw` | Borehole | density | `test_kind` (`fit`/`lot`), `at_depth` | A formation integrity or leak-off test of the subject well held the object equivalent mud weight. |
| 14 | `perforated_interval` | Borehole, Tubular, Zone | interval (or depth) | `zone`, `spf`, `gun_size` | The subject (well, tubing string, or zone) was perforated over the object interval. |
| 15 | `has_mud_weight` | Borehole | density | — | The subject well's mud/fluid weight was (raised, reduced or displaced) to the object density. If "from X to Y", annotate Y; X is a separate fact only if stated as the weight at that time with its own time. |
| 16 | `completed_in` | Borehole | entity (Zone) | — | The subject well was completed or recompleted in the object zone. |
| 17 | `encountered_marker` | Borehole | entity (Zone) | `at_depth` | The subject well encountered (logged, penetrated) the object geologic marker or formation. |
| 18 | `has_well_status` | Borehole | status | — | The subject well has or entered the object status (TA, PA, COM, ST, BP, SI). Use `time` when the text dates it. |
| 19 | `used_rig` | Borehole | entity (Rig) | — | Operations on the subject well used the object rig or vessel. |
| 20 | `operated_by` | Borehole | entity (Company) | — | The subject well is operated by the object company (stated as operator, not a service company). |
| 21 | `pumped` | Fluid | volume | `density`, `purpose` | The object volume of the subject fluid was pumped or mixed and pumped. |

### 4.2 Qualifier values

| Qualifier | Values |
|---|---|
| `test_kind` | `bop_ram`, `bop_annular`, `bop`, `casing`, `tubing`, `plug`, `annulus`, `lubricator`, `tree`, `line`, `fit`, `lot`, `other`, `unknown` |
| `result` | `good`, `failed`, `unknown` (only from the text: "Good test.", "bled down to 300 psi in 15 min" → `failed`) |
| `duration` | `{"text": <span text>, "occ": n, "minutes": <number or null>}` |
| `stage` | `low`, `high` ("250 low 10,000 psi" → two facts, stages `low` and `high`) |
| `bound` | `eq` (default), `ge` ("at least"), `le` ("up to"), `approx` ("~", "approximately") |
| `correction` | `true` when the fact is stated in a "CORRECTION REPORT"; absent = `false`. A boolean, never a span (the validator rejects any other value) |
| `toc` | `true` (the object is the top of cement); absent = `false`. A boolean, never a span (the validator rejects any other value) |
| `action` | `set`, `placed`, `replaced` (`set_plug_at`); `set`, `located` (`set_equipment_at`). A plain string, never a span |
| `at_depth` | span-backed with the depth fields of §3.2: `{"text", "occ", "value", "unit", "reference", "datum"}` |
| `density`, `volume`, `gun_size` | span-backed: `{"text", "occ", "value", "unit"}` (`density`/`volume` units of §3.2; `gun_size` unit as for `size`) |
| `spf` | span-backed: `{"text", "occ", "value"}` (shots per foot, a decimal string) |
| `hole_size`, `zone`, `purpose` | span-backed text only: `{"text", "occ"}` (no normalized value; a composite hole size such as "16.5 x 19"" is a plain span) |

`bound`, `test_kind`, `result`, `stage` are plain strings from the listed values, never spans (the validator rejects any other value).

Span-backed qualifiers carry exactly the keys listed in their row; any other key is rejected.

Unlisted qualifiers are not allowed (the validator rejects them); put extra information into `note`.

### 4.3 `other`

Use `relation: "other"` with `other_label` (short snake_case, e.g. `bled_pressure`, `flange_rating`) for a clear, span-backed technical fact that no relation covers. `other` facts are kept and counted (ontology coverage) but never scored: a `certain` `other` fact is a match candidate (G∘, m7_plan.md §5.2), so a prediction matched to it counts neither as a true nor as a false positive (`matched_other`).

## 5. Polarity, modality, time, uncertainty

- `polarity`: `positive` (default) or `negative` ("no plug retrieved", "unable to set TOL packer" → the setting fact with `negative`).
- `modality`: `done` (default), `attempted` (tried, outcome unclear or failed: "Attempt to test 7" casing to 1000 psi"), `planned` ("scheduled for early 2012"), `approved` (regulatory approval to do something). Only `positive` + `done` facts form the scored positive set; the others are kept and reported (m7_plan.md T34c).
- `time`: span-backed date of the fact if the chunk gives one for that sentence or day block ("11/5 - RIH w/ mill …" → time of every fact in that day block), else `null`. Same date rules as §3.2.
- `uncertainty`: `certain` (default) or `uncertain` (you are not sure the text states it, or a unit/reference is damaged). Uncertain facts are excluded from recall denominators and never count as false positives.

## 6. Examples (from the retained samples)

Each example: excerpt → facts (compact notation `relation(subject ; object) {qualifiers} [modality/polarity/time]`).

1. EOR `-115376`: "Set DX plug in x-nipple @ 1,484' MD." → `set_plug_at(DX plug:Plug ; depth 1484 ft MD) {action: set}`. The nipple depth is implied, not stated: no `set_equipment_at`.
2. EOR `-120894`: "Replaced DX plug in nipple assembly @ 7983'." → `set_plug_at(DX plug ; depth 7983 ft, reference unknown) {action: replaced}`.
3. EOR `-117519`: "Wellbore plugged back to sidetrack on June 19, 2011." → `has_well_status(Wellbore:Borehole report_well ; status ST)`, time `2011-06-19` (day).
4. EOR `-120818`: "Recompleted to the MP-3E sand." → `completed_in(implicit report_well ; MP-3E sand:Zone)`.
5. EOR `-120456`: "Zone change operations to the Rob (L)-5 sand were completed on 12/10/2011." → `completed_in(implicit report_well ; Rob (L)-5 sand:Zone)`, time `2011-12-10`.
6. EOR `-112972`: "The operations to modify perforations in the BN 7300' Sand were completed on 08/11/2010" → no `perforated_interval` (no interval is stated) and no depth: "7300'" is part of the zone name. Optional: `other(… ; BN 7300' Sand:Zone) {other_label: modified_perforations}`.
7. EOR `-119604`: "All casings have been cut & pulled at least 18'BML." → `cut_at(All casings:Tubular ; depth 18 ft BML datum ML) {bound: ge}`. Later: "a 30"" stub 10'AML. Jetted to 18'BML and externally cut and recovered 28'9"" of pipe from 18'BML." → `casing_size(30" stub:Tubular ; size 30 in)`, `cut_at(30" stub ; depth 18 ft BML)`. "10'AML" is a location of the stub, not a cut: `other(… ; depth 10 ft AML) {other_label: stub_height}`. "28'9"" is a length, not a depth: not annotated.
8. EOR `-120849`: "Pre-temporary abandonment operations utilizing coil tubing to set cement plug. Final temporary abandonment operations scheduled for early 2012 …" → no `set_plug_at` (no depth); `has_well_status(implicit report_well ; status TA) [planned]`, time "early 2012" → `iso: "2012"`, precision `year`.
9. EOR `-120065`: "The well has been TA'd until the remaining wells are drilled" → `has_well_status(The well:Borehole report_well ; status TA)`.
10. EOR `-120854`: "PB to Sidetrack" → `has_well_status(implicit report_well ; status ST)`.
11. EOR `-120845`: "Replaced valves on the tree." → `chunk` status `no_facts` (no object span of any relation).
12. WAR `-109513` (WAR examples prepare the later WAR extension; the v1 packets are EOR only): "Please correct the Total Depth and the 5.5"" liner setting depth to 13243' MD/12625' TVD ." → `reached_td(implicit ; 13243 ft MD) {correction: true}`, `reached_td(implicit ; 12625 ft TVD) {correction: true}`, `set_casing_at(5.5" liner:Tubular ; 13243 ft MD) {correction: true}`, `set_casing_at(5.5" liner ; 12625 ft TVD) {correction: true}`, `casing_size(5.5" liner ; 5.5 in)`.
13. WAR `-104872`: "Performed FIT @ 12440' tvd - held 17.7 ppg EMW." → `fit_lot_emw(implicit ; density 17.7 ppg) {test_kind: fit, at_depth: 12440 ft TVD}`. "Circulated and raised MW to 17.0 ppg." → `has_mud_weight(implicit ; density 17.0 ppg)`, time from its day block (`9/29/08` → `2008-09-29`).
14. WAR `-105142`: "Set 5.5"", 23#, P-110 liner." → `casing_size(5.5" … liner ; 5.5 in)`, `casing_spec(liner ; text "23 lb/ft P-110")`. No depth → no `set_casing_at`.
15. WAR `-75767`: "Pressure tested tubing to 1000# for 15 minutes on chart. Good test." → `tested_to_pressure(tubing:Tubular ; pressure 1000 psi) {test_kind: tubing, duration: 15 min, result: good}`. "RIH w/ CIBP to 8000' KBM & set same." → `set_plug_at(CIBP:Plug ; depth 8000 ft, reference unknown, datum KB)`. "Circ 400' cement plug in SS & 9-5/8"" @ 5840'-6240'." → `set_plug_at(400' cement plug:Plug ; interval 5840–6240 ft)`, `casing_size(9-5/8" ; 9.625 in)`.
16. WAR `-74770`: "RIH w/ mill & tagged TOC @ 2987' CTM." → `tagged_at(TOC:Equipment ; depth 2987 ft MD datum CTM)`, `note: "toc"`. "Pressured up to 5000 psi on control line to open SCSSV." → not a test: nothing, or `other(… ; 5000 psi) {other_label: operating_pressure}`.
17. WAR `-43698`: "Attempt to test 7"" casing to 1000 psi. Bleed down to 300 psi in 15 min." → `tested_to_pressure(7" casing:Tubular ; 1000 psi) {test_kind: casing, result: failed} [attempted]`, `casing_size(7" casing ; 7 in)`.
18. WAR `-422056`: "Tested QTS to 7,500 psi. Good test. RIH and tagged XRXX plug at 380' MD." → `tested_to_pressure(QTS:Equipment ; 7500 psi) {test_kind: lubricator, result: good}`, `tagged_at(XRXX plug:Plug ; 380 ft MD)`. "Bled off 2,000 psi from A annulus to 0 psi." → not a test.
19. WAR `-423157`: "fired 1.56"" perforating gun at 11,626' to 11,630' MD of LS." → `perforated_interval(LS:Tubular ; interval 11626–11630 ft MD) {gun_size: 1.56 in}`. "Mixed and pumped 24 bbls 16.2 ppg CT Blend cement down SS and up LS. 600' balanced cement plug from 10,830' MD to 11,430' MD." → `pumped(CT Blend cement:Fluid ; volume 24 bbl) {density: 16.2 ppg}`, `set_plug_at(600' balanced cement plug:Plug ; interval 10830–11430 ft MD) {action: placed}`.
20. WAR `-410676`: "Drill 16.5 x 19"" hole from 10,410' to section TD of 11,398' MD (11,396.2' TVD)." → `drilled_to(implicit ; 11398 ft MD) {hole_size: "16.5 x 19"}`, `drilled_to(implicit ; 11396.2 ft TVD) {hole_size: "16.5 x 19"}`. Not `reached_td` (section TD).
21. WAR `-104872`: "Ran freepoint to 13007¿: 40% free @ 12990¿" → numbers with `¿`: if annotated at all, `unit: unknown`, `uncertainty: uncertain`; freepoint is not a relation (`other` at most).
22. WAR `-106303`: "Test Hydraulic Choke to 250 low 10,000 psi." → `tested_to_pressure(Hydraulic Choke:Equipment ; 250 psi) {stage: low}` and `(… ; 10000 psi) {stage: high}`; the first value has no unit token but shares "psi" of the pair: `unit: psi`, `uncertainty: certain`.

## 7. Edge cases (decide this way)

- **One sentence, several facts.** Annotate each fact separately; they may share evidence.
- **Repeated identical facts** (the same test repeated through the day): annotate each occurrence with its own spans (the evaluator matches one-to-one).
- **"from X to Y" for depths of motion** ("POOH from 9,955' to 7,787'"): tool movements are not facts.
- **Approvals, plans, schedules:** `modality: approved|planned`; never `done`.
- **Corrections** ("CORRECTION REPORT … correct … to"): annotate the corrected values with `correction: true`; do not annotate the superseded value as `done`.
- **A pressure without "test"** (bleed, pump, injection, SBP, operating pressure): not `tested_to_pressure`.
- **"T/A", "TA'd", "P&A", "Permanently abandoned", "shut-in"**: `has_well_status` with the closed set; "plugged & abandonment work done during TA in 2008" → `has_well_status(… ; PA)` only if the sentence states the well is now PA; the TA in 2008 is a separate fact with time `2008`.
- **Ambiguous abbreviations** (`SS` = short string or subsea): decide from context; if unclear `uncertainty: uncertain`.
- **Units missing on one side of an interval** ("2420'-2407'" is a worked range, not perforations): only annotate when a relation verb applies.
- **Well names of other wells** ("Worked on D-1 well"): no fact unless a relation applies; never attach facts of another well to the report well.
- **Company names in metadata-like phrases** ("NOEX located a 30" stub"): a service or acting company is not `operated_by`.

## 8. Output format (`kgb.well_annotation/1`, JSONL, UTF-8, one object per line)

Write one file per packet batch: `data/benchmarks/bsee_gold/v1/annotations/<annotator>/batch_<NN>.jsonl`. For every chunk of the batch, first one `chunk` record, then its `fact` records. Every chunk of the batch must have exactly one `chunk` record. Never create a file or a record for a batch you have not annotated: `validate` checks only the batch files that exist (it prints `present k/NN`), and `seal` additionally requires all NN batch files.

```json
{"record": "chunk", "format": "kgb.well_annotation/1", "annotator": "annotator_a", "chunk_id": "eor_-120818_3f2a9c1d#c000", "status": "annotated", "n_facts": 1, "note": ""}
{"record": "fact", "format": "kgb.well_annotation/1", "annotator": "annotator_a", "chunk_id": "eor_-120818_3f2a9c1d#c000", "fact_no": 1, "relation": "completed_in", "subject": {"implicit": "report_well", "type": "Borehole"}, "object": {"kind": "entity", "text": "MP-3E sand", "occ": 0, "type": "Zone"}, "qualifiers": {}, "polarity": "positive", "modality": "done", "time": null, "uncertainty": "certain", "evidence": {"text": "Recompleted to the MP-3E sand.", "occ": 0}, "note": ""}
{"record": "fact", "format": "kgb.well_annotation/1", "annotator": "annotator_a", "chunk_id": "eor_-115376_0b7e44aa#c000", "fact_no": 1, "relation": "set_plug_at", "subject": {"text": "DX plug", "occ": 0, "type": "Plug"}, "object": {"kind": "depth", "text": "1,484' MD", "occ": 0, "value": "1484", "unit": "ft", "reference": "MD", "datum": "unknown"}, "qualifiers": {"action": "set"}, "polarity": "positive", "modality": "done", "time": null, "uncertainty": "certain", "evidence": {"text": "Set DX plug in x-nipple @ 1,484' MD.", "occ": 0}, "note": ""}
```

(The `chunk_id` values above are illustrative; use the ids of your packet.)

Field rules (enforced by `kgb domain gold validate`; any violation → exit 2 with the line number):

| Field | Rule |
|---|---|
| `record` | `chunk` or `fact` |
| `annotator` | the id of your prompt (`annotator_a` or `annotator_b`); the same on every line |
| `status` (chunk) | `annotated` (n_facts ≥ 1), `no_facts` (n_facts = 0), `unreadable` (n_facts = 0, reason in `note`) |
| `fact_no` | 1, 2, … per chunk, no gaps |
| `relation` | one of the 21 names or `other` (then `other_label` required) |
| `subject` | `{"text", "occ", "type"}`, optionally with `"role": "report_well"` (only with `type: Borehole`; an explicit span of the report well, §2), or `{"implicit": "report_well", "type": "Borehole"}` |
| `object` | per §3.2: `depth` {text, occ, value, unit, reference, datum}; `interval` {text, occ, lower, upper, unit, reference, datum}; `pressure`/`density`/`size`/`volume` {text, occ, value, unit}; `date` {text, occ, iso, precision}; `status` {text, occ, value}; `entity` {text, occ, type}; `text` {text, occ, value} |
| numbers | decimal strings, no thousands separators, `.` decimal point; `unknown` is allowed for `unit`, `reference`, `datum` only |
| relation ↔ kinds | subject type and object kind must be allowed for the relation (§4.1) |
| `qualifiers` | only the keys of §4.2 that the relation allows, each with exactly the value shape of its §4.2 row |
| `polarity`, `modality`, `uncertainty` | the values of §5 |
| `time` | `null` or {text, occ, iso, precision} |
| `evidence` | {text, occ}; must contain the object span and the explicit subject span |
| spans | every `text`/`occ` resolves inside the chunk; optional `start`/`end` agree |
| `note` | ≤ 300 characters; no person names |

## 9. Adjudication (`kgb.well_adjudication/1`)

The adjudicator sees the chunk text and the two annotations as **A** and **B** (which agent is A is hidden; seeded assignment per chunk, key sealed separately). The packet lists items of four kinds, aligned by the T34c matcher: `agreed` (L3 match of m7_plan.md §5.2: same value, same relation, compatible subject and qualifiers, **with** equal polarity, modality and uncertainty), `partial` (same value, but different relation/qualifier/subject, or different polarity/modality/uncertainty), `only_A`, `only_B`. `keep` on an `agreed` item writes A's fact unchanged. The adjudicated chunk status is set mechanically, not by you: a chunk either annotator marked `unreadable` stays `unreadable`. Write exactly one decision per item to `data/benchmarks/bsee_gold/v1/adjudication/decisions_<NN>.jsonl`:

```json
{"record": "decision", "format": "kgb.well_adjudication/1", "chunk_id": "...", "item_id": "...", "decision": "accept_A", "fact": null, "citation": {"text": "Set DX plug in x-nipple @ 1,484' MD.", "occ": 0}, "rationale": "A uses the stated MD reference; B dropped it."}
```

- `decision`: `keep` (agreed items only), `accept_A`, `accept_B`, `accept_both` (two distinct facts), `accept_edited` (`fact` required, full §8 fact without `annotator`), `reject`, or `add` (a fact both missed; `fact` required; counted separately).
- Allowed decisions per item kind (any other combination fails `validate`, exit 2):
  - `agreed`: `keep`, `accept_A`, `accept_B`, `accept_edited`, `reject` (not `accept_both`: the two facts match).
  - `only_A`: `accept_A`, `accept_edited`, `reject`.
  - `only_B`: `accept_B`, `accept_edited`, `reject`.
  - `partial`: every decision except `keep`.
  - `add`: allowed on any chunk.
- Copy `item_id` from the packet unchanged. It is a hash of the item content and tells you nothing about which agent is A.
- `citation` is **required for every decision except `keep`**: an exact span of the chunk (`text` + `occ`) that supports the decision; it must overlap the evidence of the accepted/edited fact, or, for `reject`, the evidence of the rejected fact.
- Decide only from the text and this guideline. Prefer the reading that §3–§7 prescribe; if both readings are defensible, prefer `uncertainty: uncertain` on the accepted fact over rejecting it.

## 10. What annotators and the adjudicator must not do

- Do not open `runs/`, `.cache/`, `data/fixtures/llm/`, `tests/fixtures/bsee/`, `research/reports/`, the other annotator's folder, `adjudication/key.json`, the `amendments/` folder of the gold root, or any BSEE table or web page. Use only your prompt file, this guideline, your packet batch files and your own output folder.
- Do not run any `kgb` command except `.\kgb.ps1 domain gold validate` and `.\kgb.ps1 domain gold seal` for your own role.
- Do not edit packets, `freeze.json`, seals, or files of another role. Do not copy facts from the rule annotator or from any model output.
- Do not "improve" the text, merge chunks, or infer facts from domain knowledge.
- If `validate` rejects an annotation that you believe follows this guideline, do not change the label to satisfy the validator and do not read or edit code: stop and report the file, line, field and the guideline section you followed. A confirmed tool defect is fixed only through a freeze amendment (tasks.md D62).

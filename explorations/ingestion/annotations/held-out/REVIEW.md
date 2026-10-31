# Held-out source annotations — review required

**Drafted as draft; now reviewed (see "Review outcome" at the end).** Review from the source renders below. A single annotator prepared these with AI assistance; there is no independent annotator or inter-annotator agreement. Do not treat these drafts as corrected gold. Existing development gold is unchanged. [Selection and exclusions](selection.json); [source hashes and captures](provenance.json).

Methods were frozen at **2026-10-31 08:41:45 UTC**; selection was recorded at **08:50:13 UTC**, before these drafts. The [method lock](../../results/round6/freeze.lock.json) has SHA256 `0128d50b8df6f13be8bbf47373e531b7cdcf696734daccbb2ec312173688c2e3`. No held-out join decisions, method outputs or scores were used. Source-only capture and annotation scripts block reads of conversion/candidate directories. [Capture](../../spikes/heldout_sources.py); [selection](../../spikes/heldout_select.py); [annotation](../../spikes/heldout_draft.py).

Page numbers are one-based physical PDF pages. Boxes use PDF points, top-left origin, in the physical displayed frame. CSV row and column indices below are zero-based; no extra schema row is inserted into a table CSV. Merged cells occupy their top-left anchor and covered cells are empty. Wrapped text inside a cell becomes spaces. Form CSVs have `block,key,value`, retain blank values, and pair repeated cost-column headings with each row as in [the development conventions](../README.md). Gold JSON manifests record `status: draft`, source SHA256 and render paths.

## Continued tables

[Table manifests](continued_tables/continued_tables.json) contain three whole logical tables from three report types outside NPT/liner. In particular, the Well Information case is a ruled form-like table; confirm that scope before later scoring.

| Draft | Source renders | Check these cells and scope first | Reviewer / date / decision |
| --- | --- | --- | --- |
| [16A Total Depth Coordinates](continued_tables/forge16a_td_coordinates.csv), pp7–8; 6 × 3 including one heading row | [p7](../../runs/round6/heldout/gdr1296_16a78-32_drilling_summary-p7.png), [p8](../../runs/round6/heldout/gdr1296_16a78-32_drilling_summary-p8.png) | P7 holds only `Item / Plan / Actual`; p8 has no repeated header. Confirm the empty first-part data range `first_row=1,last_row=0`. Check row 2 Actual `-1,047.44 ft`; row 4 printed `Well Plan Azimuth` with `3,987.42 ft / 4,073.51 ft` is intentionally not corrected semantically. Exclude Table 1, caption, prose and figure. | Pending |
| [68-32 Operations Activity Detail](continued_tables/forge68_activity_detail.csv), pp30–32; 55 × 9 including one heading row | [p30 upright](../../runs/round6/heldout/gdr1153_68-32_eowr-p30-upright.png), [p31 upright](../../runs/round6/heldout/gdr1153_68-32_eowr-p31-upright.png), [p32 upright](../../runs/round6/heldout/gdr1153_68-32_eowr-p32-upright.png); originals [p30](../../runs/round6/heldout/gdr1153_68-32_eowr-p30.png), [p31](../../runs/round6/heldout/gdr1153_68-32_eowr-p31.png), [p32](../../runs/round6/heldout/gdr1153_68-32_eowr-p32.png) | Repeated nine-column headings appear once in CSV. Row 29 → 30 is a page boundary. Row 54's description joins `... tight fit, Ran` on p31 to `instrument in well ...` on p32; its inclusive row range is present in both parts. Do not duplicate this event. Confirm source-clipped `supply line NOTE:` at the tail and `installed zip ties every 50'`. Row 28 has the only `X` nonproductive mark. Report/date merged anchors stay blank on covered rows. Exclude Total Hours `298`; sum of Hrs is a diagnostic, not a replacement row. | Pending |
| [AK-3 Hole Section Information](continued_tables/akutan_hole_section_information.csv), pp1–2; 30 × 9, no heading rows | [p1](../../runs/round6/heldout/gdr882_ak3_appx_24_5_wellinfojobrpt_160920160550-p1.png), [p2](../../runs/round6/heldout/gdr882_ak3_appx_24_5_wellinfojobrpt_160920160550-p2.png) | Confirm this five-panel ruled table belongs in the continued-table set. SURF starts at row 24; rows 28–29 (Weight and Notes) finish on p2. Confirm the nine-column union of varying ruling boundaries and merged anchors in `row_layouts`. Row 28 has `Weight: 15.5`, `Grade: K55`, `Thread: VFJ`, MD/TVD `220`. Row 29 contains the wrapped note including `(ADD 3 DAYS)`. Exclude title, repeated Well Bore band, Actual Data, AFE and Job sections. No repeated column headings. | Pending |

The header-only range and shared cross-page row preserve the existing inclusive-index convention while making edge cases explicit. Confirm them before adapting any evaluation input next round; the locked methods and scorers are unchanged this round.

## Daily-report headers

[Form manifests](forms/forms.json) contain the same scope as development: down to the block immediately before Operations Summary. Boxes are unions of direct source glyphs inside manually selected regions. Empty values have null value boxes; repeated printed cost headings reuse their heading boxes. Both selected pages are unrotated. Presence of a box does not prove it is correctly aligned.

| Draft | Source render | Check these pairs first | Reviewer / date / decision |
| --- | --- | --- | --- |
| [AK-3 report 20](forms/akutan_daily_header_20.csv), physical p28, 31-Aug-16; 48 pairs | [Full p28](../../runs/round6/heldout/gdr882_ak3_appx_27_6_dailyreportdetailrpt_nocost_160920154309-p28.png), [header crop](../../runs/round6/heldout/gdr882_ak3_appx_27_6_dailyreportdetailrpt_nocost_160920154309-p28-header.png) | MD/TVD `1105`, ROP `13.33`, Hole Made `300 / 22.5`, Drilling Days `14`, Days On Location `20`, Last BOP `30-Aug-16`. Safety text says `11 days since LTI. Conducted Safety Meeting.` Preserve visible Field `Hot Springs Bay Va`, Town `112W`, Rng `S005`; hidden text is excluded. Check `MKeown`, all personnel counts and the eight repeated cost/totals pairs. | Pending |
| [78-32 report 2](forms/forge78_daily_header_2.csv), physical p30, 14-Mar-19; 45 pairs | [Full p30](../../runs/round6/heldout/gdr1153_78-32_eowr-p30.png), [header crop](../../runs/round6/heldout/gdr1153_78-32_eowr-p30-header.png) | Well ID `Forge 78-32`, MD/TVD `716`, ROP `32.0`, Hole Made `16 / 0.5`, Spud `13-Mar-19`, Last Casing `9.625 at 704`, Next Casing `5.500 at 3,000`. Both operation values end in a printed ellipsis; the source text object stores that ellipsis separately, so value boxes unite visible fragments. Do not append hidden overflow. Check Toolpusher `Tyler Curtis, Kollin Mellott`, Supervisors `Virgil Welch, Roger Almond`, blank Comments/Tel No., and repeated `---` costs. | Pending |

Review source spelling, clipped text, blanks, all cell boundaries, and both key/value boxes before changing each record to corrected. No held-out candidate generation or scoring belongs to this round.

## Review outcome

All records were checked against the source renders. Four are now `corrected` and frozen; one is excluded.

- Forms: AK-3 report 20 (p28) and 78-32 report 2 (p30) match the renders, including the printed ellipses on the 78-32 operation values.
- 16A Total Depth Coordinates: matches; the first part holds only the header row, and all data rows are on p8.
- 68-32 Operations Activity Detail: matches; 54 data rows, repeated headings once, and the last event split across pp31–32 appears once.
- AK-3 Hole Section Information moved to `excluded/`. It is a ruled key-value form in which each cell holds a label and its value; the nine-column grid is an arbitrary union of ruling boundaries, so grid scoring would not be meaningful.

The held-out continued-table set therefore has two tables. That is a small sample, covering two distinct cases: a header-only first part, and a repeated header with a row split across pages.

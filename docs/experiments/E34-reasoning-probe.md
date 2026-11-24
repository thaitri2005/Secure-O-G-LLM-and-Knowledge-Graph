# E34: The reasoning lane on its probe, with the real model

| | |
|---|---|
| **Date** | 25 November 2026 |
| **Question** | Asked what caused a drilling problem, does the reasoning lane (specification §8.6) find the problem, give the cause the reports state with its source, and keep from stating anything else as fact? And does the lane continue beyond its probe (D-66)? |
| **Requirement** | D-61 (reasoning questions), D-64 (routing in code), D-66 (the probe decides) |
| **Input** | The K1 package `demo-v2` built on the run's machine (release `20261124T185223Z-ccc792161833`, 1,432 chunks): AK-3's daily reports, its non-productive-time report and its end-of-well report. The event graph built from it: 161 events, 28 of them non-productive, in 6 incidents |
| **Code** | `graphrag/reasoning.py`, `graphrag/coordinator.py`; run with `python -m graphrag.coordinator answer --questions <probe> --k1 --no-embeddings` |
| **Gold data** | Two probes of ten questions each, **simulated, written by the team, not reviewed by a drilling expert**: [`ak3_reasoning_probe_v0.json`](../../graphrag/gold/ak3_reasoning_probe_v0.json), frozen before any run; [`ak3_reasoning_probe_v1.json`](../../graphrag/gold/ak3_reasoning_probe_v1.json), written after the first run's fixes and before any run on it |
| **Models** | Qwen3-8B Q4_K_M, our own copy, on llama.cpp b12015's CPU build (profile `qwen3-8b.cpu`), thinking off, one slot, 8k context, `--cache-ram 0`, one request at a time. The same build reproduces the recorded baseline answer for answer (Track B log B-F71) |
| **Outputs** | `graphrag/results/E34_probe_v0_frames.json`, `E34_probe_v0_first_run.json`, `E34_probe_v0_reason_rule.json`, `E34_reasoning_probe_cpu.json`, `E34_probe_v1_first_run.json`, `E34_probe_v1_reason_rule.json`, `E34_reasoning_probe_v1_cpu.json` |
| **Status** | Done as a first measurement. The scores are low and say where: see "What was learned". A clean third set and an expert's reading are the next step |

## How an answer is scored

A row is correct when all three hold:

- **the problem is found:** the lane picked the incident the question means; or asked which one, or stepped aside, when that is the right outcome;
- **the stated cause is found and cited:** every cause the reports give is among the answer's stated causes, named by one of its terms and resting on a quote the code found in the evidence;
- **no unsupported claim:** nothing else is listed as a stated cause.

The probe's gold is short words of the report ("weather", "foot clamp"). It can be too strict (s01 below) and too loose (a wrong sentence containing "flow" counted as found). Every row was also read by hand.

## Results

### First probe (version 0): used to find faults, so not a clean test

| Run | Lane code | Correct | Problem found | Stated cause found and cited | Unsupported claims |
|---|---|---:|---:|---:|---:|
| Frames only, no answer call | As built on 24 November | – | 6/10 | – | – |
| `E34_probe_v0_first_run` | Problem finding corrected (B-F72) | 2/10 | 8/10 | 8/10 | 17 |
| `E34_probe_v0_reason_rule` | Also the rule that a stated cause must give a reason (B-F74) | 4/10 | 8/10 | 8/10 | 8 |
| `E34_reasoning_probe_cpu` | Also a smaller unit for the problem (B-F77) and the clause cut where it ends (B-F78); the same model replies, scored again | 7/10 | 8/10 | 8/10 | 4 |

### Second probe (version 1): written before any run on it

| Run | Lane code | Correct | Problem found | Stated cause found and cited | Unsupported claims |
|---|---|---:|---:|---:|---:|
| `E34_probe_v1_first_run` | Problem finding corrected | 3/10 | 6/10 | 5/10 | 8 |
| `E34_probe_v1_reason_rule` | Also the reason rule; the same model replies, scored again | 3/10 | 6/10 | 4/10 | 5 |
| `E34_reasoning_probe_v1_cpu` | Also the smaller unit for the problem, and the two corrections to problem finding that this probe's first run showed (three questions answered anew) | 6/10 | 9/10 | 6/10 | 4 |

The second probe's first two rows are the clean ones: the code was fixed on the first probe and then met questions it had not seen. Its last row is clean for the smaller unit of a problem, which was designed on the first probe alone (it turns s03 right), and not for the two corrections to problem finding, which its own first run showed (s06, s07, s08).

**By reading, the second probe's last run is 7 of 10:** s01 says "heavy rain prevented the Mayor and Priest from reaching the site" and quotes "Waiting on weather"; the gold's term is the word "weather", so it is scored wrong. The three that are wrong by reading: s04 (the report gives the reason as a purpose, "to stop flow", which the rule does not recognise, and the model names an earlier reason), s08 (the model answers "wait on cement" for the plywood walkway, where the report says "due to muddy site"), and s09 (one problem answered where the question should be asked back).

### Cost

| | Calls per question | Prompt tokens | Completion tokens | Seconds on this CPU |
|---|---:|---:|---:|---:|
| A question the lane answers (first probe, 8 questions) | 2 | 4,832 | 661 | 354 |
| A question the lane answers (second probe, 6 questions) | 2 | 4,380 | 579 | 274 |
| A baseline lookup on the same machine (B-F71) | 1 | 1,452 | 79 | 136 |

A cause question costs about three times the prompt tokens of a lookup and eight times the answer tokens. On a GPU that answered a lookup in one second, that is a few seconds. US$0 on our own copy.

## What was learned

1. **The lane does the part it was built for.** When it reached the right problem, the model named the cause the reports state and quoted the report's words for it: 8 of 8 on the first probe. Code found every one of those quotes in the evidence.
2. **The model pads the list of stated causes.** On the first probe it added 17 items across 7 answers, each with a true quote: things that happened near the problem ("high torque", "crews at lodge for night", "receive 8 joints"), not reasons. The citation check passes them, because the quote is real. Checking that a quote exists is not checking that it is a cause.
3. **A rule in code removes about half of the padding.** A stated cause must rest on a clause that gives a reason ("due to", "because", "waiting on", "unable"), once per clause, and not on something written after the day asked about. Items that fail are shown as possible factors, which is what they are. First probe: 17 unsupported to 8. Second probe, unseen: 8 to 5, at the price of one true cause that the report gives as a purpose ("to stop flow") and the rule does not recognise.
4. **Much of the rest was a true reason for a neighbouring event.** AK-3's 66-hour well-control incident holds a stuck pipe (20 August) and a lost rod (21 August). Asked about either, the model gives both reasons. An incident of 21 activities is too coarse a unit for "the problem". A second rule narrows it: the problem is the activities the question names on the day asked about; the reason written there stands, and if none is, the nearest earlier one. On the first probe, with the same model replies: 4 of 10 correct to 7, 8 unsupported claims to 4. The three still wrong: the question framed as a lookup, the one the model answered instead of asking back, and the general question about the whole incident, where both reasons are fair and the gold names neither.
5. **The model's fields about the problem cannot be trusted as written.** It wrote an activity code as the non-productive code (`STUCK`, `FISH`), a wrong non-productive code (`WOO` for `WOE`), and a code and keyword the question never mentioned. Each led the lane to nothing or to one problem where several fit. The fixes follow one rule: what code reads from the question and the reports outranks what the model says.
6. **Half of the second probe's misses are in finding the problem, not in the answer.** Two questions about activities that are not non-productive time found nothing, because every keyword had to match and the report writes "walk way" and "trip in". One wrong code blocked a date that was right. Both are changed in code (Track B log B-F74), and the rerun finds the problem on 9 of 10.
7. **"Possible factors" are mostly generic.** "Inadequate communication", "inadequate mud properties": true of any well, supported by a loosely related quote. They are labelled as possibilities and hidden in exact mode, but they add little. An expert should say whether this part is worth keeping.
8. **Asking back does not happen when the model picks a code.** "What caused the non-productive time on AK-3?" and "What caused AK-3 to wait?" each got one incident, because the model chose a code. Asked 0 times of 2.

## Decision (D-66)

The lane continues, as a probe: it is not ready to be shown as a finding to anyone. It finds the stated cause, and it over-states. Before more code, three things are needed, and the first two are not ours to supply:

- an expert's reading of ten answers: is the two-part answer the right shape, and are "possible factors" wanted at all;
- a third question set written by someone else, since both sets here were written by the team and the first was used for tuning;
- ours, from the second probe's last run: reasons the report gives as a purpose ("to stop flow"), and asking back when the model picks a code for a general question.

## Limits

- **Twenty questions on one well by one report author**, written by the team. Not an evaluation.
- **The first probe was used to change the code.** Only the second probe's first run is a held-out number, and its gold was written by the same hands as the code.
- **The gold's terms are short words.** s01's answer ("heavy rain prevented the Mayor and Priest from reaching the site", quoting "Waiting on weather") is right by reading and wrong by the terms; s04's first run was counted as found on the word "flow" in a wrong sentence.
- **CPU timings** were taken while other work shared the four cores; the token counts are exact.
- **One model, one prompt.** The prompt was not changed in this experiment; only code around it was.

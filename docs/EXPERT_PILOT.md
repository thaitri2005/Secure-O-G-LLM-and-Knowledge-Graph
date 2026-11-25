# Getting a person's answers into the tests

Every question set so far was written by the team, so no score in this repository is an evaluation (Track B log B-D22). This page is the path from a drilling expert's input to a test the engine runs. No step needs a model until the last one, and nothing here needs code to be written.

## The path

| Step | Who | What happens | Time |
|---|---|---|---|
| 1. Ask | The expert | Uses the application: types questions, reads each answer and its source page | As long as they like |
| 2. Mark | The expert | Under "Was this answer right?" presses **Yes** or **No**; after No, types what the answer should be | Seconds per question |
| 3. Download | The team | Questions page, choose the questions, **Download these as a question set** | 1 minute |
| 4. Sheet | The team | `python -m graphrag.expert sheet collected_<date>.json --out pilot.csv` | 1 minute |
| 5. Fill | The expert, or the team from the expert's comments | Opens `pilot.csv` in Excel and fills `expected_answer` | About a minute per question |
| 6. Build | The team | `python -m graphrag.expert build pilot.csv --name pilot_v1 --written-by "<name>" --expert` | 1 minute |
| 7. Run | The team | `python -m graphrag.coordinator answer --questions graphrag/gold/pilot_v1.json --k1 --name pilot_v1`, or through the running application: `python deploy/ask_set.py --url <address> --questions graphrag/gold/pilot_v1.json --name pilot_v1_app` | A few seconds per question on a GPU, about two minutes on a laptop |

An expert who prefers not to use the application starts at step 5 with an empty sheet: `python -m graphrag.expert sheet --blank --out pilot.csv` writes one with five example rows.

## The sheet

One row per question. Only `question` and `expected_answer` are required.

| Column | Filled by | Meaning |
|---|---|---|
| `id` | The tool | The question's ID in the log. Leave it |
| `question` | The expert | The question as a user would type it |
| `system_answer`, `mark`, `comment` | The tool | What the application answered and what the expert said about it. For reading only |
| `expected_answer` | The expert | The right answer in plain words (below). Already filled with the application's answer where the expert marked it right: keep it or correct it |
| `lane` | The team | Where the answer lives: `end_of_well`, `daily`, `events` (counting or summing over daily activities) or `reasoning` (the cause of a problem) |
| `problem_date`, `key_words` | The team | For a cause question only: the day of the problem, and the one or two words an answer must contain to count as naming the cause |
| `source` | The expert, if known | Report and page. Kept as a note |

How to write an expected answer:

| The answer is | Write | Scored as |
|---|---|---|
| A number | `1955 ft` or `1,955` | The number: exactly for a whole number, within 0.5% for one with decimals. The unit is not scored |
| A date | `13 August 2016` | That day |
| A name or a phrase | `Monty Keown` | The same words, ignoring case and punctuation |
| A value with more than one accepted wording | `Monty Keown \| M. Keown` | Any of them |
| Several values | `2016-08-12; 2016-08-27` | All of them, and nothing else |
| Not in the reports | `not stated` | The application must say so |
| A cause | `a weather delay`, with `key_words` = `weather` | A stated cause that names a key word and rests on a quote; nothing else stated as fact |
| A cause question that fits several problems | `ask which` | The application must ask which one |

A row with an empty `expected_answer` is left out and named when the file is built.

## What the build writes

`graphrag/gold/<name>.json`, in the same format as the other question sets. Its status line says who wrote the answers:

- with `--expert`: "EXPERT: written or checked by …, a drilling expert";
- without: "WRITTEN BY THE TEAM … not reviewed by a drilling expert, so not an evaluation".

A set is frozen once a run on it is recorded. A correction goes into a new file (`pilot_v2`); the tool refuses to overwrite one.

`python -m graphrag.expert check <file>` says whether a file is ready and what to fix (a question with no lane, a cause with no key words, a gold ID that is not there).

A question file can also be written by hand with the same plain fields:

```json
{"expected_lane": "end_of_well",
 "questions": [{"id": "p01", "question": "What was the total depth of AK-3?", "answer": "1955 ft"},
               {"id": "p02", "question": "Why did AK-3 lose 13 August 2016?", "answer": "a weather delay",
                "expected_lane": "reasoning", "key_words": "weather", "problem_date": "2016-08-13"}]}
```

## Reading the result

The run prints one line per question (right or wrong, where it was routed, the answer) and writes `graphrag/results/<name>.json` with the totals per lane and the calls, tokens and seconds per question. To record it:

1. add `docs/experiments/E<n>-<name>.md` and a row in the [register](experiments/README.md);
2. state who wrote the questions, and the endpoint and model;
3. compare a hosted or CPU score only with a baseline rerun on the same endpoint.

## Plugging in something else

| To change | Do | Where it is described |
|---|---|---|
| The reports | Build a report package and load it: `python platform/run_release.py data/interim/k1/<package>` | [platform/README.md](../platform/README.md) |
| The model | Add a profile and check it: `python -m graphrag.bench check <profile>` | [graphrag/README.md](../graphrag/README.md#trying-a-model-profiles-and-the-bench-d-62-d-68) |
| Where the model runs | `GRAPHRAG_ROLES=<roles file>` or `GRAPHRAG_PROFILE=<profile>` | [deploy/README.md](../deploy/README.md) |
| The whole standing measurement | `python -m graphrag.bench run <profile> --suite full` | [next runs](tracks/B-graphrag/next-runs.md) |

## Limits

- Units are not scored, and gold written this way names no passage, so the run scores answers and not retrieval.
- Text answers must match word for word; give the other accepted wordings with `|`.
- A cause is matched by key words, which can be too strict or too loose ([E34](experiments/E34-reasoning-probe.md)). Read every cause answer by hand as well.

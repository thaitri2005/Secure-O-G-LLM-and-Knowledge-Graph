# Resource plan and request

**Date:** 24 November 2026 · **From:** Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai · **Status:** draft for the team to check before anything is sent

This is everything the project needs to be developed, measured and shown, what the team already has, and what it asks for. Everything asked for is **rented from cloud providers**, not school hardware: MSc. Nguyen Anh Tuan advised that the school's machines can be slow and awkward to use. The email to the school is at the end.

## In short

The application is built and runs on a laptop. It cannot yet be measured or shown, because the team owns no GPU and no server.

**We ask for a budget of about US$1,000 for six months**, December 2026 to May 2027, spent on three rented services:

| # | Service | What we would rent | Cost, estimated |
|---|---|---|---:|
| 1 | **A GPU by the hour** | One 24 GB card, about 20 hours a week, plus one run of three to five days | US$30 to US$60 a month, and US$40 to US$85 once |
| 2 | **A server that stays on** | 8 vCPU, 16 GB memory, 200 GB disk, with an HTTPS address | US$25 to US$100 a month, by provider |
| 3 | **A hosted open-weight model** | Pay per use, on public data only | US$50 once |
| | A web address and a reserve for prices that changed | | US$60 once |
| | **Six months** | | **about US$500 to US$1,150** |

- **The least that keeps the project moving** is about **US$50 a month**: a smaller server, a 16 GB card for 8 hours a week, and US$10 of hosted calls. It leaves no room to compare or repeat anything.
- The team also asks the supervisor for **one or two domain experts** to try the application, and for their questions.
- The months and the end date are our assumption; the budget scales with them.

## Why the team has no compute of its own

- Every measurement so far ran on a desktop with a 16 GB GPU that was **borrowed** and is no longer ours to plan on (specification D-68).
- The three laptops have no usable GPU. One of them runs a 3B model at about 21 minutes for a 15-passage test; a full run would take about 40 hours ([E10](../experiments/E10-profile-driven-prototype.md)).
- The project may only use **open-weight models of about 8B parameters or smaller, run by us**, because the real documents are private (D-37). A commercial model such as GPT or Claude cannot stand in, not even for a test: the result would say nothing about the system we are building.

## Why rented, and why this much

- **A rented GPU runs our own copy of the model**, the same compressed copy as before, with the same server program. Results stay comparable with every score recorded so far, and a run can be repeated exactly. A hosted model (service 3) cannot promise that: a third party serves it, at a different precision.
- **Most of the work from here is experiments.** The system is built; what is unknown is how well it answers, with which model, and where it breaks. That means comparing models and settings on the same questions, repeating runs to see how much a score moves by chance, and trying other ways to read the reports.
- **Paying by the hour fits the work.** A GPU is needed for a few hours at a time, not always on. An always-on GPU would cost US$250 to US$500 a month, and is not asked for.

## Everything the project needs

| Resource | What for | Size | When | Have it? |
|---|---|---|---|---|
| **GPU, for measurements and experiments** | Running the language model (Qwen3-8B, 4-bit) on our test questions, one request at a time so results repeat; comparing other open-weight models of the allowed size, and settings, on the same questions | One 24 GB card by the hour (16 GB at the least); 100 GB of kept disk for model files | Weekly, December to May | **No.** Service 1 |
| **GPU, for building the graph from text** | A smaller model (Qwen3-4B) reads each page once to extract facts: about 3 seconds and 4,750 tokens a page ([E16](../experiments/E16-neo4j-graphrag-python.md)) | Same card | With each new set of reports | **No.** Service 1 |
| **GPU, for the large run** | The whole corpus on local models, then the evaluation (plan milestone M5) | Same card, three to five days, stopping and resuming allowed | Second semester | **No.** Service 1 |
| **GPU, for reading pages with a vision model** | Only if rule-based reading of tables and forms proves not enough (D-63) | 24 GB | Not before January; may not be needed | **No.** Service 1 |
| **A server that stays on** | PostgreSQL with pgvector, Neo4j, the backend and the web application, for the team and for the experts; a second copy of the stores for experiments, so a trial never disturbs the demo | 8 vCPU, 16 GB memory, 200 GB disk, Ubuntu 24.04, Docker (4 vCPU, 8 GB and 80 GB at the least, without the second copy) | From early December | **No.** Service 2 |
| **An address for the application** | Experts open it in a browser over HTTPS, behind one shared password | One domain name | With the server | **No.** About US$12 a year |
| **A hosted open-weight model** | The demo answering at any hour without a GPU running; quick checks between GPU sessions. Public data only | US$50 (US$10 at the least: more than 10,000 questions) | Now | **No.** Service 3 |
| **Domain experts' time** | Trying the application; their questions are logged and become the real test set | One or two people, an hour or two each | From 12 December | **No.** Asked of the supervisor |
| **The expert question set and the purpose of use** | The real evaluation; today every question is written by us | — | As soon as possible | **No.** Asked on 9 November |
| Laptops | Code, tests, reading PDFs, the stores during development | Three, 16 GB each | Now | Yes |
| Source code hosting and automatic tests | GitHub, public repository | Free tier | Now | Yes |
| Public data | AK-3 (Alaska) and Utah FORGE drilling reports, CC BY 4.0 | A few GB | Now | Yes |
| Software | PostgreSQL, Neo4j Community, Docling, llama.cpp, FastAPI, React, Caddy: all open source | — | Now | Yes, no licence cost |
| Models | Qwen3-8B, Qwen3-4B, Qwen3-Embedding-0.6B, open weights from Hugging Face | About 10 GB of files | Now | Yes, free to download |
| A private network between our machines | Sharing the stores before a server exists | Tailscale, free tier | Now | Yes |
| AI coding assistance | Writing and reviewing code only; never part of the system | — | Now | Yes, paid by Tri |

## How the sizes were worked out

**The GPU.** A 16 GB card holds Qwen3-8B in 4-bit with a 32k context, which is what every recorded result used, and nothing else beside it. 24 GB also holds the embedding model at the same time, a less compressed copy of the model to see what compression costs, or a document vision model. A 24 GB card rents for about US$0.34 to US$0.69 an hour.

| Work | Amount | GPU time, estimated |
|---|---|---|
| The three measurements waiting now (the coordinator on 221 questions with its baselines, answers on the new report package, ten questions about causes) | About 600 questions, about 3,300 tokens each | A few hours; one 8-hour session with setup |
| One round of measurement after a change | 200 to 300 questions | 2 to 4 hours |
| Building the fact graph for a set of reports | 3 seconds a page: 1,000 pages is under an hour | 1 to 2 hours per 1,000 pages |
| Comparing models or settings | The same 200 to 300 questions once per candidate | 2 to 4 hours per candidate |
| Repeating a run to see how much a score moves by chance | Three repeats of a round | 6 to 12 hours |
| Trying a vision model on pages the rules read badly | A few hundred pages; time per page not yet measured | Unknown; a day to find out |
| The large run and its evaluation | A few thousand pages, extraction and questions, with one rerun after fixes | Three to five days, with stops allowed |

These are estimates from runs on the borrowed card; a rented card may be faster or slower. About 8 hours a week covers only the first three rows. **About 20 hours a week** lets each of us run one experiment a week beside the regular measurements, and a failed run can be repeated the same week. 20 hours a week is about 87 hours a month: US$30 to US$60. Setting up a rented machine each time costs paid minutes, so model files are kept on a small rented disk between sessions (a few dollars a month, inside the range above).

**The server.** Neo4j is set to 2 GB of heap and 1 GB of cache; PostgreSQL, the backend and the web application share the rest of 8 GB, which is the least that works. 16 GB runs a second copy of the stores for experiments beside the one the experts use. Page images are about 0.5 MB a page and each report package is kept, so a few thousand pages with backups want 200 GB, not 80. It needs no GPU: the model is reached over the network.

| Server | Listed price for 4 vCPU and 8 GB | For 8 vCPU and 16 GB, our estimate |
|---|---:|---:|
| Hetzner | US$10 to US$16 a month | about US$25 to US$35 a month |
| DigitalOcean | about US$48 a month | about US$96 a month |

The larger size was not priced from a source; it is the smaller price doubled and must be checked. The GitHub Student Developer Pack lists US$200 of DigitalOcean credit for a year and US$100 of Azure credit per student, which would cover part of this if it can be redeemed (either may ask for a card).

**The hosted model.** A question costs about 3,100 prompt tokens and 200 output tokens over its two calls (measured in [E28](../experiments/E28-event-graph.md): 71,553 and 4,736 tokens for 23 questions). Listed prices for Qwen3-8B are US$0.12 to US$0.20 per million input tokens and US$0.20 to US$0.46 per million output tokens, which gives well under US$0.001 a question. US$50 pays for the demo for the whole period and for trying several open-weight models side by side; other models are priced differently, which is why the ask is above the arithmetic.

## The budget

| Item | Low | High | Note |
|---|---:|---:|---|
| Server, six months | US$150 | US$600 | Hetzner at the low end, DigitalOcean at the high end; less with student credits |
| GPU by the hour, six months at 20 hours a week | US$180 | US$360 | US$0.34 to US$0.69 an hour |
| GPU, the large run | US$40 | US$85 | 120 hours |
| Hosted open-weight model | US$50 | US$50 | Pay per use; unused credit stays |
| Domain name | US$12 | US$12 | One year |
| Reserve | US$50 | US$50 | Prices are several months old in places |
| **Total** | **about US$480** | **about US$1,160** | |

We ask for **about US$1,000**, and will report what is spent each month against it. With the cheaper server the same plan costs about half.

## Limits to know about

- **Public data only, on everything rented.** A cloud server, a rented GPU and a hosted model are all other people's machines. They may hold public reports only (AK-3, Utah FORGE). A VPI document stays off them unless VPI agrees in writing to a named provider; until then such a document can only be processed on a machine VPI or the team controls, and none is planned here.
- **A hosted model's results are not compared with our earlier ones.** They come from a different copy of the model. Reported scores come from the rented GPU, where we run our own copy.
- **Prices are list prices found on 24 November 2026**, some estimated as marked, and should be checked on the day of purchase. The sources disagree in places, and two are several months old.
- **Nothing here has been confirmed by the school or the supervisor**: whether the school can fund cloud services, how (a budget, a refund, or accounts the school holds), and who holds each account and its spending cap (open question Q6).
- **Spending is capped at the provider** where the provider allows it, and a rented GPU is switched off after each session; the team records hours and cost with every run, as it already does for tokens.

## The email to the school

**To:** Dr. Le Duy Dung · **Cc:** MSc. Nguyen Anh Tuan · **Subject:** Capstone "LLM and Knowledge Graph for drilling reports": request for a cloud computing budget

Dear Dr. Dung,

We are the capstone team working with VPI on question answering over drilling reports (Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai; supervisor MSc. Nguyen Anh Tuan).

The application is now built: a person asks a question about a well's reports and gets an answer with the page it comes from. It runs end to end on a laptop. We cannot yet measure it or show it to VPI's experts, because the project must use open-weight language models that we run ourselves, and we have no GPU and no server of our own. The machine we used until now was borrowed.

On MSc. Tuan's advice we would like to rent these from cloud providers instead of using school machines, and we ask whether the school can support the cost: **about US$1,000 for six months**, December 2026 to May 2027.

1. **A GPU rented by the hour** (one 24 GB card, about 20 hours a week, and one run of three to five days in the second semester): about US$30 to US$60 a month. Most of our work from here is experiments: comparing open-weight models, repeating runs to see how stable a result is, and trying other ways to read the reports.
2. **One server that stays on** (8 vCPU, 16 GB of memory, 200 GB of disk) for the databases and the web application, behind a password: about US$25 to US$100 a month, depending on the provider.
3. **Pay-per-use access to hosted open-weight models**, so a demonstration answers at any hour: US$50 in total.

All data on these services is public (drilling reports published by the US Department of Energy's Geothermal Data Repository), and everything we run is open source. We will report what is spent each month.

Could you tell us:

- whether the school can fund this, in full or in part;
- in what form: a budget we spend and claim back, or accounts the school opens and pays for;
- who should approve it, and what you need from us to decide.

If only part is possible, about US$50 a month still keeps the project moving, with less room for experiments. A short document with the sizes, the prices and how we worked them out is attached.

Thank you for your time.

Best regards,<br>
Thai Huu Tri, on behalf of the team

## Sources

- [GitHub Student Developer Pack](https://education.github.com/pack)
- [DigitalOcean for GitHub students](https://www.digitalocean.com/github-students)
- [OpenRouter: Qwen3 8B](https://openrouter.ai/qwen/qwen3-8b/api)
- [Price per token: Qwen3 8B](https://pricepertoken.com/pricing-page/model/qwen-qwen3-8b)
- [DigitalOcean review 2026, droplet prices](https://vpsdex.com/en/activity/digitalocean-review-2026/)
- [DigitalOcean and Hetzner price comparison](https://getdeploying.com/digitalocean-vs-hetzner)
- [RunPod and Vast.ai GPU pricing 2026](https://www.spheron.network/blog/gpu-cloud-pricing-comparison-runpod-vs-vastai-2026/)
- [RTX 4090 rental price, November 2026](https://aliteq.com/rtx-4090-price)

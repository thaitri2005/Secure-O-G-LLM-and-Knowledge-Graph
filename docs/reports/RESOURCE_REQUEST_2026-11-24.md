# Resource plan and request

**Date:** 24 November 2026 · **From:** Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai · **Status:** draft for the team to check before anything is sent

This is everything the project needs to be developed, measured and shown, what the team already has, and what it asks for. The email to the school is at the end.

## In short

The application is built and runs on a laptop. Three things stop it from being measured and shown, and the team owns none of them:

| # | We ask for | From | Needed |
|---|---|---|---|
| 1 | **Time on a GPU**: one card with 16 GB of memory or more, about 8 hours a week, plus one longer slot of one to two days later | The school | Now: three measurements are waiting |
| 2 | **One small virtual machine** that stays on: 4 vCPU, 8 GB memory, 80 GB disk, Ubuntu, reachable over HTTPS | The school | By 5 December, for the demo of 12 December |
| 3 | **US$10** of credit for hosted open-weight models, on public data only | The supervisor | Now: it unblocks the measurements even before a GPU slot |
| 4 | **One or two domain experts** to try the application, and their questions | The supervisor | From 12 December |

If the school cannot give 1 or 2, the fallback is paid: about US$50 a month for a server and US$0.34 to US$0.69 an hour for a rented GPU.

## Why the team has no compute of its own

- Every measurement so far ran on a desktop with a 16 GB GPU that was **borrowed** and is no longer ours to plan on (specification D-68).
- The three laptops have no usable GPU. One of them runs a 3B model at about 21 minutes for a 15-passage test; a full run would take about 40 hours ([E10](../experiments/E10-profile-driven-prototype.md)).
- The project may only use **open-weight models of about 8B parameters or smaller, run by us**, because the real documents are private (D-37). A commercial model such as GPT or Claude cannot stand in, not even for a test: the result would say nothing about the system we are building.

## Everything the project needs

| Resource | What for | Size | When | Have it? |
|---|---|---|---|---|
| **GPU, for measurements** | Running the language model (Qwen3-8B, 4-bit) on our test questions, one request at a time so results repeat | One card, 16 GB or more; 32 GB system memory; 50 GB disk | Weekly, from now to the end of the project | **No.** Ask 1 |
| **GPU, for building the graph from text** | A smaller model (Qwen3-4B) reads each page once to extract facts: about 3 seconds and 4,750 tokens a page ([E16](../experiments/E16-neo4j-graphrag-python.md)) | Same card | With each new set of reports | **No.** Ask 1 |
| **GPU, for the large run** | The whole corpus on local models, then the evaluation (plan milestone M5) | Same card or 24 GB, for one to two days, stopping and resuming allowed | Second semester | **No.** Ask 1 |
| **GPU, for reading pages with a vision model** | Only if rule-based reading of tables and forms proves not enough (D-63) | 24 GB | Not before January; may not be needed | **No.** Part of ask 1, later |
| **GPU, for private documents** | If VPI supplies a real document, it may only be processed on machines we control | Same card | Second semester, if a document arrives | **No.** Ask 1 |
| **A server that stays on** | PostgreSQL with pgvector, Neo4j, the backend and the web application, for the team and for the experts | 4 vCPU, 8 GB memory, 80 GB disk, Ubuntu 24.04, Docker | From 5 December to the end of the project | **No.** Ask 2 |
| **An address for the application** | Experts open it in a browser over HTTPS, behind one shared password | A name such as `kg.<school domain>`, ports 80 and 443 | With the server | **No.** Part of ask 2 |
| **A hosted open-weight model** | The demo answering at any hour; measurements until a GPU slot exists. Public data only | US$10 is more than 10,000 questions | Now | **No.** Ask 3 |
| **Domain experts' time** | Trying the application; their questions are logged and become the real test set | One or two people, an hour or two each | From 12 December | **No.** Ask 4 |
| **The expert question set and the purpose of use** | The real evaluation; today every question is written by us | — | As soon as possible | **No.** Asked on 9 November |
| Laptops | Code, tests, reading PDFs, the stores during development | Three, 16 GB each | Now | Yes |
| Source code hosting and automatic tests | GitHub, public repository | Free tier | Now | Yes |
| Public data | AK-3 (Alaska) and Utah FORGE drilling reports, CC BY 4.0 | A few GB | Now | Yes |
| Software | PostgreSQL, Neo4j Community, Docling, llama.cpp, FastAPI, React, Caddy: all open source | — | Now | Yes, no licence cost |
| Models | Qwen3-8B, Qwen3-4B, Qwen3-Embedding-0.6B, open weights from Hugging Face | About 10 GB of files | Now | Yes, free to download |
| A private network between our machines | Sharing the stores before a server exists | Tailscale, free tier | Now | Yes |
| AI coding assistance | Writing and reviewing code only; never part of the system | — | Now | Yes, paid by Tri |

## How the sizes were worked out

**The GPU.** A 16 GB card holds Qwen3-8B in 4-bit with a 32k context, which is what every recorded result used. 24 GB would also hold the embedding model beside it, or a document vision model.

| Work | Amount | GPU time, estimated |
|---|---|---|
| The three measurements waiting now (the coordinator on 221 questions with its baselines, answers on the new report package, ten questions about causes) | About 600 questions, about 3,300 tokens each | A few hours; one 8-hour slot with setup |
| One round of measurement after a change | 200 to 300 questions | 2 to 4 hours |
| Building the fact graph for a set of reports | 3 seconds a page: 1,000 pages is under an hour | 1 to 2 hours per 1,000 pages |
| The large run and its evaluation | A few thousand pages, extraction and questions | One to two days, with stops allowed |

These are estimates from runs on the borrowed card; the time per question on the school's hardware is not known. **About 8 hours a week covers the first three rows.** What we need to know to use a slot: which GPUs exist, how long a slot is, how it is booked, whether Docker or our own programs (llama.cpp, vLLM) may run, how to reach the machine (SSH), and whether it can download models from Hugging Face.

**The server.** Neo4j is set to 2 GB of heap and 1 GB of cache; PostgreSQL, the backend and the web application share the rest of 8 GB. It needs no GPU: the model is reached over the network. If the school's network does not allow a public address, access through the school VPN is enough for the team, but then outside experts cannot open it.

**The hosted model.** A question costs about 3,100 prompt tokens and 200 output tokens over its two calls (measured in [E28](../experiments/E28-event-graph.md): 71,553 and 4,736 tokens for 23 questions). Listed prices for Qwen3-8B are US$0.12 to US$0.20 per million input tokens and US$0.20 to US$0.46 per million output tokens, which gives well under US$0.001 a question. The three waiting measurements are a few million tokens, under US$1.

## If the school cannot provide it

| Need | Paid fallback | Cost |
|---|---|---|
| Server | GitHub Student Developer Pack credits first (US$200 at DigitalOcean for a year, US$100 at Azure; either may ask for a card). Otherwise a rented server | US$0 with credits; else US$10 to US$16 a month (Hetzner) or about US$48 (DigitalOcean) |
| GPU for measurements | The hosted open-weight model, on public data | Under US$1 a round |
| GPU for the large run or for private documents | A rented 24 GB card by the hour. A hosted model is not allowed for private documents | US$0.34 to US$0.69 an hour: about US$10 to US$35 for two days |
| An always-on GPU for the demo | Not asked for: US$250 to US$500 a month. The hosted model does the same job on public data for cents | — |

Worst case with no help from the school: about **US$50 a month** for the server, plus about **US$50** in total for rented GPU hours and hosted calls.

## Limits to know about

- **Public data only on anything hosted.** The hosted model and a cloud server may hold public reports only (AK-3, Utah FORGE). A VPI document stays on local machines and local models, as the specification requires. That is the main reason a school GPU matters beyond convenience.
- **Hosted results cannot be compared with our earlier ones.** A hosted model is served at full precision by a third party; every score so far used a 4-bit copy on a local GPU. We rerun the baseline on the hosted model before comparing anything with it, and record the provider with each run.
- **Prices are list prices found on 24 November 2026** and should be checked on the day of purchase. The sources disagree in places, and two are several months old.
- **Nothing here has been confirmed by the school or the supervisor.** Who holds the hosted account and its spending cap is open (Q6); how school GPUs are booked is open (Q7).

## The email to the school

**To:** Dr. Le Duy Dung · **Cc:** MSc. Nguyen Anh Tuan · **Subject:** Capstone "LLM and Knowledge Graph for drilling reports": request for GPU time and one virtual machine

Dear Dr. Dung,

We are the capstone team working with VPI on question answering over drilling reports (Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai; supervisor MSc. Nguyen Anh Tuan).

The application is now built: a person asks a question about a well's reports and gets an answer with the page it comes from. It runs end to end on a laptop. We cannot yet measure it or show it to VPI's experts, because the project must use open-weight language models that we run ourselves, and we have no GPU of our own. The machine we used until now was borrowed.

We would like to ask the school for two things:

1. **GPU time.** One GPU with 16 GB of memory or more (24 GB if available), about 8 hours a week from now until the end of the project, and one longer slot of one to two days in the second semester for the full run. Our jobs can stop and resume, so short slots are fine.
2. **One small virtual machine that stays on.** 4 vCPU, 8 GB of memory, 80 GB of disk, Ubuntu 24.04 with Docker, reachable over HTTPS, if possible under a school address. It holds the databases and the web application, behind a password. It needs no GPU. We would like it by 5 December, for a demonstration on 12 December.

All data on these machines is public (drilling reports published by the US Department of Energy's Geothermal Data Repository). Everything we run is open source.

To plan our work, could you tell us:

- which GPUs students can use, how long a slot is, and how to book one;
- whether we may run Docker or our own programs (llama.cpp or vLLM), and whether the machine can download models from Hugging Face;
- how we connect (SSH, VPN);
- whether a virtual machine with a public address is possible, or only one inside the school network.

If either request is not possible, we would be grateful to know soon, so we can look for another way. A short document with the sizes and how we worked them out is attached.

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

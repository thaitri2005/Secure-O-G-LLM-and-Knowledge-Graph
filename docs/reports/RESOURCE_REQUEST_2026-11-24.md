# Resource plan and request

**Date:** 24 November 2026 · **From:** Thai Huu Tri, Nguyen Le Hung, Tran Quang Khai · **Status:** draft for the team to check before anything is sent

This is everything the project needs to be developed, measured and shown, what the team already has, and what it asks for. Everything asked for is **rented from cloud providers**, not school hardware: MSc. Nguyen Anh Tuan advised that the school's machines can be slow and awkward to use. Dr. Le Duy Dung, the team's advisor, said to email anh Trường to use the capstone funding when resources are needed. That email is at the end.

Amounts are in Vietnamese dong, with US dollars beside them at **26,000 VND to the dollar**, an assumed rate to check on the day.

## In short

The application is built and has run end to end with the real model on a machine without a GPU, where an answer takes minutes. It cannot yet be measured in full or shown, because the team owns no GPU and no server.

**We ask for 5 million VND (about US$190) from the capstone funding for the next three months**, December 2026 to February 2027, spent on three rented services:

| # | Service | What we would rent | Three months, estimated |
|---|---|---|---:|
| 1 | **A GPU by the hour** | One 24 GB card, about 10 hours a week | 1.2 to 2.3 million VND (US$45 to US$90) |
| 2 | **A server that stays on** | 4 vCPU, 8 GB memory, 80 GB disk, with an HTTPS address | 0.8 to 1.2 million VND (US$30 to US$48) |
| 3 | **A hosted open-weight model** | Pay per use, on public data only | 0.5 million VND (US$20) |
| | A web address and a reserve | | 0.8 million VND (US$32) |
| | **Total** | | **3.3 to 4.8 million VND (US$127 to US$186)** |

- **5 million VND is the ceiling for these three months.** If prices sit at the high end, GPU hours are cut first, to stay inside it.
- **This is a first request.** The rest is for next semester: after the three months we report what was spent and what it bought, and ask again, including for the full run over all the reports.
- **The least that keeps the project moving** is about **1.5 million VND** (US$60) for the three months: the server, a hosted model for the measurements, and no rented GPU. Nothing could then be compared with our earlier results.
- The team also asks the supervisor for **one or two domain experts** to try the application, and for their questions.

## Why the team has no compute of its own

- Every measurement so far ran on a desktop with a 16 GB GPU that was **borrowed** and is no longer ours to plan on (specification D-68).
- The three laptops have no usable GPU. One of them runs a 3B model at about 21 minutes for a 15-passage test; a full run would take about 40 hours ([E10](../experiments/E10-profile-driven-prototype.md)).
- The project may only use **open-weight models of about 8B parameters or smaller, run by us**, because the real documents are private (D-37). A commercial model such as GPT or Claude cannot stand in, not even for a test: the result would say nothing about the system we are building.

## Why rented, and why this much

- **A rented GPU runs our own copy of the model**, the same compressed copy as before, with the same server program. Results stay comparable with every score recorded so far, and a run can be repeated exactly. A hosted model (service 3) cannot promise that: a third party serves it, at a different precision.
- **Most of the work from here is experiments.** The system is built; what is unknown is how well it answers, with which model, and where it breaks. That means comparing models and settings on the same questions, and repeating runs to see how much a score moves by chance.
- **Paying by the hour fits the work.** A GPU is needed for a few hours at a time, not always on. An always-on GPU would cost 6 to 13 million VND a month, and is not asked for.

## Everything the project needs

| Resource | What for | Size | When | Have it? |
|---|---|---|---|---|
| **GPU, for measurements and experiments** | Running the language model (Qwen3-8B, 4-bit) on our test questions, one request at a time so results repeat; comparing other open-weight models of the allowed size, and settings, on the same questions | One 24 GB card by the hour (16 GB at the least); a small kept disk for model files | Weekly, December to February | **No.** Service 1 |
| **GPU, for building the graph from text** | A smaller model (Qwen3-4B) reads each page once to extract facts: about 3 seconds and 4,750 tokens a page ([E16](../experiments/E16-neo4j-graphrag-python.md)) | Same card | With each new set of reports | **No.** Service 1 |
| **GPU, for the large run** | The whole corpus on local models, then the evaluation (plan milestone M5) | Same card, about three days, stopping and resuming allowed | Second semester | **No.** A later request |
| **GPU, for reading pages with a vision model** | Only if rule-based reading of tables and forms proves not enough (D-63) | 24 GB | Not before January; may not be needed | **No.** Fits in service 1's hours if it is tried |
| **A server that stays on** | PostgreSQL with pgvector, Neo4j, the backend and the web application, for the team and for the experts | 4 vCPU, 8 GB memory, 80 GB disk, Ubuntu 24.04, Docker | From early December | **No.** Service 2 |
| **An address for the application** | Experts open it in a browser over HTTPS, behind one shared password | One domain name | With the server | **No.** About 0.3 million VND a year |
| **A hosted open-weight model** | The demo answering at any hour without a GPU running; quick checks between GPU sessions. Public data only | 0.5 million VND: more than 20,000 questions | Now | **No.** Service 3 |
| **Domain experts' time** | Trying the application; their questions are logged and become the real test set | One or two people, an hour or two each | From 12 December | **No.** Asked of the supervisor |
| **The expert question set and the purpose of use** | The real evaluation; today every question is written by us | — | As soon as possible | **No.** Asked on 9 November |
| Laptops | Code, tests, reading PDFs, the stores during development and for experiments | Three, 16 GB each | Now | Yes |
| Source code hosting and automatic tests | GitHub, public repository | Free tier | Now | Yes |
| Public data | AK-3 (Alaska) and Utah FORGE drilling reports, CC BY 4.0 | A few GB | Now | Yes |
| Software | PostgreSQL, Neo4j Community, Docling, llama.cpp, FastAPI, React, Caddy: all open source | — | Now | Yes, no licence cost |
| Models | Qwen3-8B, Qwen3-4B, Qwen3-Embedding-0.6B, open weights from Hugging Face | About 10 GB of files | Now | Yes, free to download |
| A private network between our machines | Sharing the stores before a server exists | Tailscale, free tier | Now | Yes |
| AI coding assistance | Writing and reviewing code only; never part of the system | — | Now | Yes, paid by Tri |

## How the sizes were worked out

**The GPU.** A 16 GB card holds Qwen3-8B in 4-bit with a 32k context, which is what every recorded result used, and nothing else beside it. 24 GB also holds the embedding model at the same time, or a less compressed copy of the model to see what compression costs. A 24 GB card rents for about US$0.34 to US$0.69 an hour (9,000 to 18,000 VND).

| Work | Amount | GPU time, estimated |
|---|---|---|
| The measurements waiting now (an expert's question set answered two ways, and the standing sets once on a GPU; the short ones were made without a GPU) | About 600 questions, about 3,300 tokens each | A few hours; one 8-hour session with setup |
| One round of measurement after a change | 200 to 300 questions | 2 to 4 hours |
| Building the fact graph for a set of reports | 3 seconds a page: 1,000 pages is under an hour | 1 to 2 hours per 1,000 pages |
| Comparing models or settings | The same 200 to 300 questions once per candidate | 2 to 4 hours per candidate |
| Repeating a run to see how much a score moves by chance | Three repeats of a round | 6 to 12 hours |
| The large run and its evaluation | A few thousand pages, extraction and questions | About three days, with stops allowed |

These are estimates from runs on the borrowed card; a rented card may be faster or slower. **About 10 hours a week** covers the regular measurements and one experiment a week between the three of us. Over 13 weeks that is 130 hours: 1.2 to 2.3 million VND. Model files are kept on a small rented disk between sessions, inside that range. The large run belongs to the second semester and is not in this request.

**The server.** The stores and the application are limited to about 4 GB together (Neo4j 1.5 GB, PostgreSQL 1 GB, the backend 1.5 GB), so 8 GB leaves room for the system and for loading a package; 4 GB is the least that works. It needs no GPU: the model is reached over the network. Experiments on the stores stay on our laptops, so a trial never disturbs what the experts use.

| Server, 4 vCPU and 8 GB | Listed price a month | Three months |
|---|---:|---:|
| Hetzner | US$10 to US$16 | 0.8 to 1.2 million VND |
| DigitalOcean | about US$48 | 3.7 million VND: most of the budget, so only with student credits |

The GitHub Student Developer Pack lists US$200 of DigitalOcean credit for a year and US$100 of Azure credit per student. If one of us can redeem it (either may ask for a card), the server costs nothing and its share goes to GPU hours.

**The hosted model.** A question costs about 3,100 prompt tokens and 200 output tokens over its two calls (measured in [E28](../experiments/E28-event-graph.md): 71,553 and 4,736 tokens for 23 questions). Listed prices for Qwen3-8B are US$0.12 to US$0.20 per million input tokens and US$0.20 to US$0.46 per million output tokens, which gives well under US$0.001 a question. US$20 pays for the demo for the three months and for quick checks with room to spare.

## The budget

Three months, December 2026 to February 2027.

| Item | Low | High | Note |
|---|---:|---:|---|
| Server | 0.8 M (US$30) | 1.2 M (US$48) | Hetzner; nothing if student credits can be redeemed |
| GPU by the hour, 13 weeks at 10 hours a week | 1.2 M (US$45) | 2.3 M (US$90) | US$0.34 to US$0.69 an hour |
| Hosted open-weight model | 0.5 M (US$20) | 0.5 M (US$20) | Pay per use; unused credit stays |
| Domain name | 0.3 M (US$12) | 0.3 M (US$12) | One year |
| Reserve | 0.5 M (US$20) | 0.5 M (US$20) | Prices are several months old in places |
| **Total** | **3.3 M VND (US$127)** | **4.8 M VND (US$186)** | |

We ask for **5 million VND as a ceiling**, and will report what is spent each month against it.

## After the three months

A second request for next semester, sized from what these months show: the server and the weekly GPU hours, and the full run over all the reports (about three days of GPU time, 0.6 to 1.3 million VND). The team expects its total for now to stay within about 10 million VND.

## If more became possible

Not asked for now. In order of what it would buy:

| With | We could |
|---|---|
| A server with 16 GB | Keep a second copy of the stores for experiments on the server, not on laptops |
| About 20 GPU hours a week instead of 10 | Run an experiment each per week, and repeat a failed run the same week |
| A day of GPU time for a vision model | Find out whether it reads the tables and forms the rules read badly |

## Limits to know about

- **Public data only, on everything rented.** A cloud server, a rented GPU and a hosted model are all other people's machines. They may hold public reports only (AK-3, Utah FORGE). A VPI document stays off them unless VPI agrees in writing to a named provider; until then such a document can only be processed on a machine VPI or the team controls, and none is planned here.
- **A hosted model's results are not compared with our earlier ones.** They come from a different copy of the model. Reported scores come from the rented GPU, where we run our own copy.
- **Prices are list prices found on 24 November 2026**, in dollars, and should be checked on the day of purchase. The sources disagree in places, and two are several months old. The exchange rate is assumed.
- **Nothing here has been confirmed**: whether the capstone funding can pay for cloud services, how (a budget, a refund, or accounts the school holds), and who holds each account and its spending cap (open question Q6).
- **Spending is capped at the provider** where the provider allows it, and a rented GPU is switched off after each session; the team records hours and cost with every run, as it already does for tokens.

## The email

**To:** anh Trường (full name and address to fill in) · **Cc:** Dr. Le Duy Dung, MSc. Nguyen Anh Tuan · **Subject:** Capstone "LLM and Knowledge Graph for drilling reports": request to use capstone funding for cloud computing

Dear anh Trường,

We are a capstone team working with the Vietnam Petroleum Institute (VPI) on question answering over drilling reports: Thai Huu Tri, Nguyen Le Hung and Tran Quang Khai. Our advisors are Dr. Le Duy Dung and MSc. Nguyen Anh Tuan. Dr. Dung told us to write to you to use the capstone funding for the resources the project needs.

The application is now built: a person asks a question about a well's reports and gets an answer with the page it comes from. It has run end to end with the real model on a machine without a GPU, at minutes an answer. We cannot yet measure it in full or show it to VPI's experts, because the project must use open-weight language models that we run ourselves, and we have no GPU and no server of our own. The machine we used until now was borrowed.

We would like to rent these from cloud providers, paying only for the hours we use, and we would like to ask for **5 million VND (about US$190) for the next three months**, December 2026 to February 2027.

1. **A GPU rented by the hour** (one 24 GB card, about 10 hours a week): 1.2 to 2.3 million VND. Most of our work from here is experiments: comparing open-weight models and repeating runs to see how stable a result is.
2. **One small server that stays on** (4 vCPU, 8 GB of memory) for the databases and the web application, behind a password: 0.8 to 1.2 million VND.
3. **Pay-per-use access to hosted open-weight models**, so a demonstration answers at any hour: 0.5 million VND.

The rest is a web address and a small reserve. All data on these services is public (drilling reports published by the US Department of Energy's Geothermal Data Repository), and everything we run is open source. We will report what is spent each month. After the three months we would report what the budget bought, and ask again for next semester.

Could you tell us:

- whether this can be funded, in full or in part;
- how it works: we pay and claim back with receipts, or the school pays the providers;
- what you need from us to proceed (a form, quotes, an approval from our advisors).

If only part is possible, about 1.5 million VND still keeps the project moving, with far less room for experiments. A short document with the sizes, the prices and how we worked them out is attached.

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

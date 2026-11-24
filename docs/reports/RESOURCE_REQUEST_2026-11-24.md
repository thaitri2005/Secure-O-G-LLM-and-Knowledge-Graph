# Resource request for the second build

**Date:** 24 November 2026 · **From:** Tri, Khai, Hung · **To:** MSc. Nguyen Anh Tuan · **Status:** draft for the team to check before it is sent; Hung owns the hosting (Track B log B-D35) and should confirm the server size

## What we ask for

| Item | Amount | When |
|---|---:|---|
| OpenRouter credit for hosted open-weight models, public data only | **US$10** | Now |
| Contingency, only if the student credits below cannot be used | up to **US$50 a month**, for 3 months | Only if needed |

Everything else is covered by what the team already has. The total is **US$10 certain, and at most US$160** if the free credits fail.

## Why these amounts

The second build puts one application in front of domain experts (decision D-60, D-65). That needs three things running where people outside the team can reach them.

| Need | What it is | Plan | Cost |
|---|---|---|---:|
| **Stores and application** | One server for PostgreSQL with pgvector, Neo4j, the backend and the frontend. About 4 vCPU and 8 GB of memory: Neo4j alone wants 2 GB or more. Everything that runs on it is built and has run on a laptop | A cloud server paid from GitHub Student Developer Pack credits | US$0 from our side |
| **The model, for measurements** | Qwen3-8B, one request at a time. The desktop that ran every measurement so far was borrowed and is not ours to plan on | The same hosted open-weight model as the demo, on public data; the school GPUs for anything that must stay local | Under US$1 for the three runs waiting now |
| **The model, for the demo** | An endpoint that answers when an expert opens the application, at any hour | A hosted open-weight model through OpenRouter. Allowed because the demo data is public (specification §10.1) | About US$0.001 a question |

**The server.** A 4 vCPU, 8 GB server is listed at about US$48 a month at DigitalOcean. The Student Developer Pack lists US$200 of DigitalOcean credit for one year and US$100 of Azure credit, so one student's credit covers about four months and the three of us cover the academic year. If the credits cannot be redeemed (Azure asks for a card; DigitalOcean's own page mentions US$100 for new users only), the same server costs US$10 to US$16 a month at Hetzner or about US$48 at DigitalOcean. That is the contingency.

**The hosted model.** A question costs about 3,100 prompt tokens and 200 output tokens over its two calls (measured in [E28](../experiments/E28-event-graph.md): 71,553 and 4,736 tokens for 23 questions). Listed prices for Qwen3-8B are US$0.12 to US$0.20 per million input tokens and US$0.20 to US$0.46 per million output tokens, which gives well under US$0.001 a question. US$10 is therefore more than 10,000 questions: every expert trial we can foresee, and the measurements too. The three runs waiting now (the coordinator on 221 questions with its baselines, answers on the new package, the ten questions about causes) are a few million tokens, under US$1.

**What we do not ask for.**

- **An always-on rented GPU.** A 24 GB card rents for about US$0.34 to US$0.69 an hour, so US$250 to US$500 a month to keep one running for a demo. The hosted model does the same job on public data for cents.
- **GPU time for the large run** (plan milestone M5). That is the school's GPUs, through Dr. Le Duy Dung. If a slot cannot be booked, a rented card at the hourly price above is the fallback; we will size it from the measured seconds per page before asking.

## Limits to know about

- **Public data only.** The hosted model and the cloud server may hold public reports only (AK-3, the Utah FORGE reports). A VPI document stays on local machines and local models, as the specification requires. If the demo must ever use private data, this plan no longer fits and the model must run on a GPU we control.
- **Hosted results cannot be compared with our earlier ones.** OpenRouter serves the model at full precision from a third-party provider; every score recorded so far used a 4-bit copy on a local GPU. From now on we rerun the baseline on the hosted model before comparing anything with it, and we record the provider with each run. Speed measured there says little about a local deployment.
- **Prices are list prices found on 24 November 2026** and should be checked on the day of purchase. The sources disagree in places, and two are several months old.

## What we need from you

1. Approval of the US$10, and who holds the OpenRouter account and its spending cap (open question Q6).
2. How to book the school GPUs (open question Q7). It matters sooner than before: we have no GPU of our own, so any run that must stay on local machines waits for a slot.

## Sources

- [GitHub Student Developer Pack](https://education.github.com/pack)
- [DigitalOcean for GitHub students](https://www.digitalocean.com/github-students)
- [OpenRouter: Qwen3 8B](https://openrouter.ai/qwen/qwen3-8b/api)
- [Price per token: Qwen3 8B](https://pricepertoken.com/pricing-page/model/qwen-qwen3-8b)
- [DigitalOcean review 2026, droplet prices](https://vpsdex.com/en/activity/digitalocean-review-2026/)
- [DigitalOcean and Hetzner price comparison](https://getdeploying.com/digitalocean-vs-hetzner)
- [RunPod and Vast.ai GPU pricing 2026](https://www.spheron.network/blog/gpu-cloud-pricing-comparison-runpod-vs-vastai-2026/)
- [RTX 4090 rental price, November 2026](https://aliteq.com/rtx-4090-price)

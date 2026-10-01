# Models in the pipeline: options

Status: **research, 29 September 2026.** Nothing here is built. The question:
can a model fill what the deterministic readers cannot (multi-post
advertisements, eligibility split into its parts, Hindi, the notices that
match no exam), for free, on GitHub Actions, with minimal upkeep?

## The constraints that decide it

* **The runner.** A public repository's `ubuntu-latest` runner has 4 vCPU,
  16 GB RAM and 14 GB of disk, free; a private repository gets half. No GPU.
  The nightly crawl already takes about 45 minutes of a 6-hour job limit.
* **Hosted free tiers churn.** In the last few months GitHub Models was retired
  (closed to new users 16 June, shut down 30 July 2026), Groq dropped Llama from
  its free plan, Cerebras turned its free tier into a trial, and OpenRouter's
  free model list turned over. Each change would be a pipeline outage.
* **Data sharing is not a concern.** Every document is a public notice, so a
  free tier that trains on its input (Gemini, Mistral) is acceptable.
* **The pipeline must work without any of it.** A model only fills a gap the
  readers left, and everything it returns is checked against the document.

## Option A: models that run on the runner (no key, no quota)

| Model | What it is | Where it helps | Cost on the runner |
|---|---|---|---|
| **Multilingual embeddings** (`intfloat/multilingual-e5-small`, or `BAAI/bge-m3`), via `fastembed` (ONNX, CPU) | Text → vector; Hindi included | Suggesting an exam for an unmatched notice; classifying the 44% `other` doc types from a few hundred labelled titles; spotting duplicate notices; finding the eligibility or fee section in a long PDF; suggesting which class an unmapped label is closest to | e5-small is about 120M parameters: milliseconds per title, a few minutes for the whole harvest |
| **GLiNER2** (`fastino/` models, 205M multilingual; Apache 2.0) | Schema-driven extraction and classification in one encoder, CPU-first | Eligibility parts (qualification, experience, registration, age, domicile) from the located section; post names in multi-post advertisements | Encoder-sized; returns **character spans**, so every value is grounded in the text by construction |
| **NuExtract 2.0 2B / NuExtract3 4B**, GGUF via `llama.cpp` (Apache 2.0) | Small models trained only for template → JSON extraction; `verbatim-string` fields must be copied from the input | Per-post tables and per-post eligibility in multi-post advertisements, where the structure is too irregular for rules | 2–5 GB download (cache it); generation is a few tokens per second on 4 vCPU, so roughly a minute or two per section: a budget of 10–30 sections a night |
| **Kruti Dev → Unicode** (`ltrc/kru2uni`, `PdfToUnicode`) | A character map, not a model | Hindi PDFs in legacy fonts, which today come out as gibberish | Free |
| **Docling** (layout model + TableFormer) | Table structure recognition | Merged-cell vacancy tables that pymupdf splits | Heavy install (torch); keep in reserve |
| **Laya** (already in the repo, `model` extra) | A 322M verifier, used by the recheck pipeline | Could verify a candidate value against its page | Already paid for |

Not suitable: Surya OCR is far more accurate than Tesseract on Devanagari but
is impractically slow on CPU; Tesseract `hin` stays.

## Option B: hosted free APIs (a key in a repository secret)

| Provider | Free allowance | Catches |
|---|---|---|
| **Gemini API** (Google AI Studio) | Flash models; the official page no longer publishes numbers (shown per project in AI Studio). Secondary sources report roughly 500–1,500 requests a day on Flash | **PDF input is not on the free tier**, so send extracted text; no batch API on free |
| **Groq** | About 1,000 requests a day, but only about 6,000 tokens a minute | Too little context per minute for whole sections |
| **Mistral** (Experiment plan) | Large monthly token allowance, about 1 request a second | Phone verification; limits no longer published. The largest free token allowance of any provider |
| **OpenRouter** `:free` models | 50 requests a day (1,000 after a one-time $10 purchase) | The free model list changes often |
| **Cloudflare Workers AI** | 10,000 "neurons" a day | Small open models only |

## Recommendation

**Local first.** The runner is free and has room for small models; local
models cannot be retired, rate-limited or repriced, which is what minimal
upkeep needs. In order:

1. **Embeddings** (fastembed, e5-small). Cheapest, most uses, helps the
   maintainer worklists straight away (unmatched notices, doc types, unmapped
   classes) and finds the right section for step 2.
2. **GLiNER2** for eligibility parts, run only on the section found in step 1.
   Its spans are the evidence; a value without a span does not exist.
3. **NuExtract**, only for multi-post advertisements, with a nightly budget,
   `verbatim-string` fields, and each value checked against its page.
4. Hosted APIs as optional adapters behind the same interface, only if the
   golden set shows the local models are not good enough. Since training on
   public notices is acceptable, Gemini and Mistral can be pooled: one key
   each, the second used when the first returns a rate-limit error, so one
   provider's change is not an outage.

Rules for all of them:

* Pinned model versions, cached in `actions/cache`, so a run is reproducible:
  the same PDF and the same model give the same answer.
* Fallback only, spent on the exams with the most gaps, once per PDF (keyed by
  its sha256).
* Output constrained to the vocabularies (`reservation.toml`, the terms), with
  anything else sent to the unmapped worklists.
* Every value carries `from: "model"` and its model id, and ranks below a
  table or rule-based value in the profile merge.
* Adopted only when the golden set shows it improves a field without making
  another worse.

## Sources

* Runner: [Tenki, runner images 2026](https://tenki.cloud/blog/github-actions-runner-image-selection-2026).
* GitHub Models: [retired 30 July 2026](https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-july-30-2026/), [closed to new customers](https://github.blog/changelog/2026-06-16-github-models-is-no-longer-available-to-new-customers/).
* Free tiers overview and churn: [OpenRouter comparison](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/), [Ian Paterson](https://ianlpaterson.com/blog/free-llm-api-2026/).
* Gemini: [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [pricing and free tier terms](https://ai.google.dev/gemini-api/docs/pricing), [secondary limits report](https://aipromptshub.co/blog/gemini-api-free-tier-rate-limits).
* Groq: [rate limits](https://console.groq.com/docs/rate-limits), [Klymentiev](https://klymentiev.com/blog/groq-pricing).
* Mistral: [help centre](https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them).
* OpenRouter: [rate limits](https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know).
* Cloudflare: [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/index.md).
* fastembed: [qdrant/fastembed](https://github.com/qdrant/fastembed); bge-m3 ONNX: [PR 602](https://github.com/qdrant/fastembed/pull/602).
* GLiNER2: [paper](https://arxiv.org/abs/2507.18546), [repository](https://github.com/fastino-ai/GLiNER2).
* NuExtract: [NuExtract3 GGUF](https://huggingface.co/numind/NuExtract3-GGUF), [NuExtract 2.0 2B GGUF](https://huggingface.co/numind/NuExtract-2.0-2B-GGUF).
* CPU speed: [llama.cpp discussion 21112](https://github.com/ggml-org/llama.cpp/discussions/21112), [PromptQuorum, CPU-only LLMs](https://www.promptquorum.com/local-llms/best-cpu-only-llm).
* Docling: [paper](https://arxiv.org/pdf/2501.17887), [Docling vs PyMuPDF4LLM](https://www.file2markdown.ai/blog/pymupdf4llm-vs-docling).
* Surya vs Tesseract on CPU: [DEV](https://dev.to/carlos_mruiz_e1fbb61ca7/surya-ocr-vs-tesseract-en-cpu-con-python-30b3).
* Kruti Dev: [ltrc/kru2uni](https://github.com/ltrc/kru2uni), [PdfToUnicode](https://github.com/souravgl0/PdfToUnicode).
* Grounded extraction practice: [Unstract](https://unstract.com/blog/comparing-approaches-for-using-llms-for-structured-data-extraction-from-pdfs/).

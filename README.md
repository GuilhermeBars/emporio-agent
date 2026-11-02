# Empório da Música – Customer Service Agent (prototype)

Text-message agent for a fictional musical-instrument store in Campo Grande/MS.
It answers in the store's tone, looks up the supplied **CSV snapshots** (products, prices, stock, promotions, orders)
and **store policies** (hours, payment, returns, shipping, warranty), and politely refuses out-of-scope requests.

Author: [Guilherme Bars](https://guilhermebars.com).

## How to run

> **API keys:** each person runs the agent with their own key (e.g. a free Groq key from https://console.groq.com/keys), set as an environment variable or in a local `.env` copied from `.env.example`. `.env` is git-ignored; no key is ever committed to this repo.

Requires Python 3.10+. Run commands from the project root.

Linux/macOS (bash):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export OPENAI_API_KEY="your-key"
python -m src.main
python -m pytest -q
```

Windows (PowerShell; no activation required):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "your-key"
.\.venv\Scripts\python.exe -m src.main
.\.venv\Scripts\python.exe -m pytest -q
```

Alternatively, copy `.env.example` to `.env` and fill in one provider key. `.env` is
loaded from the project root; existing environment variables take precedence. `.env`
is ignored by Git. The scripts use paths relative to their own source files, so
`python /path/to/project/src/main.py` also works from another directory.

| Variable | Behavior |
|---|---|
| `OPENAI_API_KEY` | API key for OpenAI or an OpenAI-compatible endpoint; takes precedence over `GROQ_API_KEY`. |
| `OPENAI_BASE_URL` | Optional endpoint override. Default: the SDK's OpenAI endpoint, or `https://api.groq.com/openai/v1` when only a Groq key is supplied. |
| `MODEL` | Optional model override. Default: `gpt-4o-mini`, or `llama-3.3-70b-versatile` with the Groq convenience configuration. |
| `GROQ_API_KEY` | Convenience key: selects Groq defaults when no `OPENAI_API_KEY` is set. |
| `DEBUG` | `1`, `true` or `yes` prints tool calls in the CLI; `0` disables them. |

For Groq, set `GROQ_API_KEY` instead of `OPENAI_API_KEY` (`export GROQ_API_KEY="your-key"`
in bash, `$env:GROQ_API_KEY = "your-key"` in PowerShell). Explicit endpoint and model
values always override provider defaults. For local Ollama, set `OPENAI_API_KEY=ollama`,
`OPENAI_BASE_URL=http://localhost:11434/v1`, and a locally installed tool-capable `MODEL`.
Other compatible providers need an endpoint and model that support chat tool calls.

Tests require no credentials and never call an LLM. They cover deterministic tools,
provider selection, the agent loop with an injected fake client, and transcript files.
The same tests can also run with `python -m unittest discover -s tests -v`; this runner
only needs pandas installed. Actual provider conversations are a separate operation below.

## Architecture (the simplest thing that works)
```
user -> CLI (main.py) -> Agent loop (agent.py) -> LLM with function calling
                                                 ├─ search_products  (pandas over products/categories/promotions)
                                                 ├─ get_order_status (orders/order_items/customers + identity check)
                                                 ├─ search_policies  (keyword retrieval over policy manual sections)
                                                 └─ get_today
```

## Technical decisions
| Decision | Choice | Why |
|---|---|---|
| Approach | **Function calling** (tool-using agent) | Deterministic tools supply price, stock and status. The model chooses tools and writes the reply. The prompt requires lookups; natural-language grounding still needs evaluation. |
| Structured data | pandas filters, not a SQL agent | 7 small CSVs. Fixed, typed functions are safer and easier to test than free-form LLM-generated SQL. |
| Policies | Section-level keyword retrieval | The manual is ~8 pages. Splitting by numbered section and ranking by word overlap is enough; a vector DB would add cost and complexity with no gain at this size. Easy to swap for embeddings later. |
| Model / provider | OpenAI-compatible chat API | Defaults to `gpt-4o-mini`; `GROQ_API_KEY` selects Groq and `llama-3.3-70b-versatile`. Endpoint/model overrides support other compatible providers; tool-call behavior varies by model. |
| Interface | CLI | The focus is the agent working correctly; a FastAPI/WhatsApp layer can wrap `Agent.chat()`. |
| History | In-memory message list per session | Needed for multi-turn flows (e.g. asking for the order number, then the email). Persisting to disk/DB is unnecessary for a prototype. |
| Prompt | Persona "Toninho" + explicit grounding and scope rules | Check tools for prices/stock; show original price + % off; no cumulative PIX discount or accessories; distinguish actual receipt from estimated delivery; explain the manual's human-contact process without claiming to create tickets. |
| Identity check | Order id **and** matching email/phone | Emails preserve punctuation and ignore case; phones accept formatting changes. Missing orders and failed checks return the same error. This prototype check is not production authentication. |

### Data treatment
- Joined products with categories and **only active** promotions (`is_active = 1`). The snapshot has no promotion start/end dates, so the active flag is authoritative.
- Product `status` (`active`, `coming_soon`, `discontinued`) and `stock_quantity` are returned so the agent can suggest alternatives.
- Accent-insensitive search (`violao` matches `Violão`).
- Price bounds use the current promotional price when present; PIX remains a separate payment rule. Money is rounded to cents with decimal arithmetic.
- Product results include descriptions and specifications; policy queries with no matching keywords return no sections.

### Assumptions / data issues found (documented, not "fixed")
- The manual lists two phone numbers ((67) 3341-4444 on the cover/company data, (67) 3321-4500 in the WhatsApp section) and an e-mail with an accent (`contato@empóriodamusica.com.br`). The agent quotes what the manual says; this should be confirmed with the store.
- Installment rule "up to 3x: no minimum installment (except below R$ 50)" is ambiguous; interpreted as minimum installment of R$ 50.
- Some order totals don't match item prices (e.g. order 3: 2 × R$ 1,749 = R$ 3,498 vs total R$ 3,450; order 20: R$ 1,488 vs R$ 1,400). The agent reports the stored order total and never recalculates it.
- The "7-day return" window counts from **actual receipt**; the data has only `estimated_delivery`. The agent must ask for the receipt date and must not use that estimate to start a deadline. The manual distinguishes 30 days from purchase for a defect exchange and 90 days from receipt for legal warranty.
- Dataset dates are 2025–2026; "today" comes from the system clock.

## Known limitations / with more time
- Keyword retrieval can miss paraphrases -> embeddings + hybrid search, plus an eval set of Q&A pairs.
- No real human-handoff/ticket system. Complaints remain in the current conversation; the customer is directed to the manual's contact channel and informed of its 24-business-hour response policy.
- Policy retrieval is lexical and Portuguese-focused; source conflicts (including the general credit table versus section 3.1) require staff clarification.
- Add a FastAPI endpoint + WhatsApp integration, persistent sessions (Redis/SQLite), guardrails against prompt injection, logging/observability (e.g. Langfuse) and automated LLM evals for each scenario.

## Use of coding assistants

The prototype was drafted with **Grok Bot (AI assistant)** and reviewed and extended
with **OpenAI Codex CLI**, including provider configuration, bug fixes, tests, the
example recorder, and documentation. **Guilherme Bars** directed the decisions and
reviewed the work. Recorded LLM examples, when generated, are API outputs; deterministic
unit tests use a fake client and are not real customer conversations.

## Example conversations
With dependencies installed and a provider key configured, run:

```bash
python scripts/record_examples.py
```

In PowerShell without activation, use `.\.venv\Scripts\python.exe scripts/record_examples.py`.
This makes real, potentially billable LLM API calls and writes five Markdown transcripts to
[`examples/`](examples/README.md), each with an independent conversation, model, timestamp,
user/assistant messages, and full tool calls/results:

1. Product price, stock, specifications and budget alternatives.
2. Active Ohana CK-20 promotion and the noncumulative PIX rule.
3. Order status with a missing identity, failed identity check, then a corrected check.
4. Returns and warranty with explicit dates relative to the run date.
5. Out-of-scope questions, accessories, and complaint escalation guidance.

Completed files end in `.md`; interrupted or failed runs retain `.partial.md` files with
an explicit status. The script exits nonzero on provider failures. Use `--overwrite`
to replace completed transcripts, or `--output-dir PATH` to choose another directory.
Review the outputs for factual accuracy and expected tool usage; successful API calls alone
do not certify correct agent behavior. No transcripts are fabricated when credentials or
network access are unavailable.

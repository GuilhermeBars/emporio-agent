Run `python scripts/record_examples.py` from the project root with dependencies
installed and `OPENAI_API_KEY` or `GROQ_API_KEY` configured. On Windows without
activation, use `.\.venv\Scripts\python.exe scripts/record_examples.py`.

The recorder runs five independent multi-turn conversations against the real LLM:

1. `01_product_price_stock.md`: Takamine price/stock, specifications, alternatives.
2. `02_promotion_pix.md`: Ohana active discount, no cumulative PIX discount.
3. `03_order_identity.md`: order 8, failed email, then matching identity and tracking.
4. `04_returns_warranty_dates.md`: date-based return, exchange and warranty questions.
5. `05_scope_complaint.md`: scope limits, accessories and human-contact guidance.

Each completed transcript includes model, UTC start time, messages, tool-call IDs,
arguments and full results. `.partial.md` files indicate incomplete/failed attempts.
Existing completed files require `--overwrite`. Unit-test transcripts are temporary
fixtures and are never saved here as real examples.

No real transcripts have been recorded in this checkout yet: the review session
had no provider credentials, and its network policy prevented dependency installation.

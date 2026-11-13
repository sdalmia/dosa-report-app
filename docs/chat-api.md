# Command Centre chat API

Other assistants call the Command Centre over HTTPS. They do not use Google sign-in.

## Key

Set `CHAT_BOT_KEYS` on Render to JSON. Each value is the sha256 hex of that bot's secret and a role.

Roles:

- `ops` — sales, reviews, Reelo, audit, buying. Tony, Alfred, Procurement, Logan, and Chief of Staff.
- `finance` — ops plus accounts and Grand Economics. Accountant.
- `hr` — ops plus Keka and people. HR Bot.
- `owner` — finance and HR together.

```bash
python -c "import hashlib; print(hashlib.sha256(b'the-secret').hexdigest())"
```

```json
{"tony": {"hash": "<sha256 hex>", "role": "ops"}, "accountant": {"hash": "<sha256 hex>", "role": "finance"}}
```

The web chat still uses `CHAT_API_KEY`, `CHAT_MODEL` (default `gpt-4.1`), and optional `CHAT_API_URL`.

## Call

```bash
curl -s -X POST https://command.dosacoffee.com/api/ask \
  -H "Authorization: Bearer the-secret" \
  -H "Content-Type: application/json" \
  -d '{"question": "How are we tracking against this month'\''s target?", "mode": "answer"}'
```

`mode` is `answer` or `action_plan`. The reply is JSON:

```json
{"answer": "...", "data_as_of": "11 Nov 2026", "table": null, "chart": null, "actions": []}
```

`action_plan` returns up to five actions. Each has `what`, `why`, `owner`, and `urgency`. The why line uses a figure already in the data.

A missing or wrong key is `401`. Too many calls from one bot is `429`.

## Feedback and review

A bot can rate an answer. The note is kept only for a thumbs down. The key is not stored.

```bash
curl -s -X POST https://command.dosacoffee.com/api/chat/feedback \
  -H "Authorization: Bearer the-secret" \
  -H "Content-Type: application/json" \
  -d '{"question": "How are we tracking against this month'\''s target?", "topic": "sales", "data_as_of": "11 Nov 2026", "rating": "down", "note": "Need the store, not only the city."}'
```

Owner and ops bots can pull the weekly review. Finance and HR keys are refused.

```bash
curl -s "https://command.dosacoffee.com/api/chat/insights?days=7" \
  -H "Authorization: Bearer the-secret"
```

House rules for every model answer live in `data/chat/house_notes.md`. Edit that file to change them. No code change is required. The file is not a new environment variable. The learning tables are created on startup if they are missing, in the existing `DATABASE_URL`.

## Delivery commission

Swiggy and Zomato: `AGGREGATOR_COMMISSION_PCT` is 21 and `GST_ON_COMMISSION_PCT` is 18, in `app/commercial.py`. Effective drag is 24.78% of net. It is not applied to dine-in or takeaway. A payout or ads file under `data/` is preferred when one is present. Channel gross is not treated as net.

## Licences

`data/compliance/<YYYY-MM-DD>/licences.csv` is the newest drop. Columns: `store`, `city`, `licence_type`, `licence_no`, `issued`, `expiry`, `status`, `source_file`, `source_modified`, `notes`. Answers recompute status from `expiry` versus the day of the question. Licence numbers stay in the file and are omitted from answers unless the question asks for a number. Owner and ops can see this. Finance and HR cannot. NCR dates come from certificates; a dated NCR tracker is still pending.

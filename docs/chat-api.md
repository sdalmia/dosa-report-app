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

The web chat still uses `CHAT_API_KEY`, `CHAT_MODEL` (default `gpt-4o-mini`), and optional `CHAT_API_URL`.

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

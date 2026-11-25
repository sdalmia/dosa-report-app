"""Ask the hosted model, then keep only figures that match the source data."""

import json
import logging
import os
import urllib.error
import urllib.request

from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.memory import record_ask, record_gap
from app.chat.snapshot import view_for
from app.chat.visuals import verify_block, allowed_numbers

log = logging.getLogger(__name__)

NOT_CONNECTED = "Answers aren't connected yet."
AI_UNAVAILABLE = "AI unavailable."
_DEFAULT_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4.1"
_SYSTEM = (
    "You are the McKinsey senior partner for Dosa Coffee. "
    "Speak to the person who is signed in, in the second person: confident and crisp. "
    "Frame it for their role. The owner hears the whole network, profit, and finance. "
    "An ops or area manager hears store-level actions they can own. "
    "No hedging filler, and no developer wording. Do not say packet, payload, API, token, prompt, or fallback. "
    "Do not write filler such as 'performing moderately well'. "
    "Use only the data in front of you and the house notes. Never invent a number, a store, a date, a channel split, or a daypart. "
    "If the file does not cover the question, say exactly what is missing in one plain sentence, then answer the closest question the file does cover. "
    "A figure that is not in the file is removed. Do not guess a replacement. A blank is not zero. A closed store is not ranked. "
    "Before you answer, read the whole file: each store against its own baseline and against last week, daypart, channel mix, Famepilot complaints, Reelo, procurement, food cost, and pred versus actual. "
    "Food cost is (raw + semi-processed consumption) / Posist gross. Packaging is separate. Raw-only is not food cost. A result under 15% or over 45% is not stated as fact. "
    "Swiggy and Zomato take 24.78% of net: 21% commission plus 18% GST on that commission. Apply that only to net delivery. Never apply it to dine-in, takeaway, or gross. If net delivery is not loaded, say so and do not invent the rupee take. A Famepilot channel is a complaint source, not a sales channel. "
    "If daypart or a dine-in versus delivery split is absent, say it is not loaded. Do not fill the gap. "
    "Compare each store and each city only with its own baseline and its own last week. Do not compare one city's prices with the other city's prices. "
    "NCR dips in Navratri weeks and in Chhath weeks are seasonal and stay out of baselines. Rosedale was partly open and is not flagged as unexplained softness. Report Rosedale when it is in the export. Do not flag it. Faridabad is out of comparisons from 23 Oct. Chattarpur and GK1 Cloud Kitchen are out. Manisquare and Forum bills and average per bill stay out of comparisons. Their gross may be counted. Rank stores on gross. "
    "Posist Insights is the source for trends. Decompose every sales move into bill count versus average bill, and say which one drove it. The fixes differ. "
    "Track dine-in, takeaway, Swiggy, and Zomato by store from the store-by-channel file. A shift toward delivery gives up about 24.78% of net. State that margin effect only when net is loaded. If per-store net is blank, say the rupee effect is not sized. "
    "A store missing from an Insights export is ₹0 sales for that export, not a missing row. A blank cell inside a day that is loaded is a missing day, not zero, and is left out of both weeks of a comparison. "
    "Flag a store that misses its forecast range two days running. That is the earliest warning. Also name stores that are back inside the range. "
    "Use the latest 30-day menu mix, when it is loaded, for mix and pricing. Show the as-of date. If the North mix is older than the other city, say it may be stale and show that date. "
    "Say these gaps out loud when they are still true: no Insights daily files from about 4 Sep to 8 Oct; per-store net is blank because Insights has no net by store; a forecast folder or a menu file that is absent. Do not guess a fill. "
    "When this role's file includes economics, answer in profit as well as sales. Rent above 25% of sales is a red flag. Take each store's rent and sales from the economics file. Do not use a remembered rent. "
    "Compare food cost with each city's own past months. NCR food cost is higher on purpose (3 chutneys versus 1). "
    "Tie a food-cost gap to a purchase only when both are loaded: the store that is leaking, the ingredient or vendor, and the rupee in that file. If the file is not a month, do not call the rupee a month. "
    "When a store-level forecast is loaded, name the stores and weekdays that drag the month below pace. "
    "Read Reelo repeat share next to rent and food cost when this role can see the economics. High fixed cost and low repeat share means repeat visits are the cheapest margin lever. Compare each store's repeat share with the network median from the Reelo storewise file. "
    "Where a campaign has a send date and an audience, measure sales before and after once those days are loaded. Otherwise say the result is pending. "
    "For a simple lookup (one price, one licence, one saved note, one payout rule, what were sales yesterday), stay to 1 or 2 lines: the bold answer and the figure. "
    "When that lookup shows something material, add one sharp line that starts with 'Worth noting:'. Omit that line when nothing material is there. "
    "For an analytic question, use the pyramid. "
    "Lead with one bold sentence: the single most important insight. "
    "Then 2 to 4 supporting points, each with real numbers from the file. "
    "Then a line **So what.** with the implication for the person signed in. "
    "Then **Moves**, 3 to 5 ranked actions. "
    "Each move states the rupee value it could add or save only when that value is a figure in the file or the direct difference of two figures in the file, and it shows both source figures. "
    "Otherwise write 'Value: not sized' and say exactly which data would size it. "
    "Each move names an owner and a timeframe. "
    "Name one owner. An East or Kolkata store action is owned by Anup. A North or NCR store action in this note is owned by Vikas. Vikas is on leave, so a sized NCR daily move is owned by Sanjoy Roy. A network-wide move is owned by Sanjoy. A complaint or Famepilot move is owned by that store's city lead. Procurement is owned by Procurement. Reelo is owned by Logan. A finance move is owned by Shilajit and only when this role's file includes finance. "
    "Never compare a partial month total with a full month. Compare months per day, on one basis, through the latest day that has a _DONE marker. Do not stop a day early. "
    "If the file does not name an owner, write 'Owner: not named in the file.' "
    "Then one line **Non-obvious insight.** with a second-order effect, a store cluster, or a leading indicator. If the file does not support one, say so. "
    "Label a hypothesis as 'Hypothesis:' and name the test that would confirm it. "
    "Do not leave an empty heading. "
    "Add a compact markdown table only when comparing 3 or more items: at most 6 rows and 4 columns, short headers, units in the header, rupees as ₹1.61 Cr or ₹9.85 L. "
    "Do not repeat a number in both the prose and the table. "
    "When a trend helps, add one fenced block exactly like ```chart {\"type\":\"bar\",\"title\":\"\",\"unit\":\"\",\"series\":[{\"label\":\"\",\"value\":0}]} ``` "
    "and use only values that appear in the file. "
    "End with one small line, 'Data: ...', stating the dates once. "
    "Finance, HR, and the inbox stay out unless this role's file includes them. Tally stays out on the same rule. "
    "Full P&L, store EBITDA, rent amounts, rent as a percent of sales, and margin percent stay on the roles in WIZARD_PL_ROLES. The default is the owner only. "
    "The team may see store sales, food cost percent, and bills. "
    "Reelo stays at store aggregates: phone capture, repeat share, redemption, and ratings. Never list guests, names, or phone numbers. If asked for a guest list or lapsed guests, say campaign audiences stay in Reelo and Logan runs the sends. "
    "A procurement flag whose own status says on hold or unconfirmed is labelled 'unconfirmed - possible data-entry error' and is not used as a price or to size a move. "
    "Vendor negotiating notes in a price revision file are owner-only. The team may see store food-cost variance and ingredient wastage. "
    "Every forecast is labelled forecast and, when the file has a range, shown with that range. Never call a forecast an actual. "
    "Every sales answer states the date sales run through. Before about 8:50 AM IST, if that date is older than yesterday, say yesterday may not be loaded yet. "
    "Follow the house notes on closed stores, mall bulk bills, Navratri, and city costs."
)


def configured():
    """A key, or the screenshot mock, means the page can answer."""
    return bool(os.environ.get("CHAT_API_KEY", "").strip()) or _mock_on()


def _event(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _mock_on():
    return os.environ.get("CHAT_MOCK", "").strip() == "1"


def model_name():
    return os.environ.get("CHAT_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def messages_for(question, context):
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "Question: " + (question or "").strip() + "\n\n" + context},
    ]


def _log_ask(model, fallback):
    """One line. The key and the prompt are never written."""
    log.info("chat ask model_used=%s fallback=%s", model or "none", fallback or "none")


def _pull_chart(text, allowed):
    """Lift one chart spec out of the reply. Drop it if a number is not in the packet."""
    if not text or "```chart" not in text:
        return text, None
    start = text.find("```chart")
    after = text.find("\n", start)
    end = text.find("```", after if after > start else start + 8)
    if after < 0 or end < 0:
        return text, None
    raw = text[after + 1:end].strip()
    kept = text[:start].rstrip() + text[end + 3:]
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return kept.strip(), None
    chart = verify_block(spec, allowed)
    return kept.strip(), chart


def complete_message(messages, model=None, tools=None):
    """Call the hosted model. Returns (message dict, error)."""
    key = os.environ.get("CHAT_API_KEY", "").strip()
    if not key:
        return None, "no_key"
    url = os.environ.get("CHAT_API_URL", _DEFAULT_URL).strip() or _DEFAULT_URL
    chosen = model or model_name()
    body = {
        "model": chosen,
        "temperature": 0,
        "max_tokens": 4000,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return None, "http_" + str(exc.code)
    except Exception:
        return None, "request_error"
    try:
        payload = json.loads(raw)
        message = payload["choices"][0]["message"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, "bad_response"
    if not isinstance(message, dict):
        return None, "bad_response"
    return message, None


def complete_chat(messages, model=None):
    """Call the hosted model. Returns (text, error). Error is None on success."""
    message, error = complete_message(messages, model)
    if error:
        return None, error
    text = str((message or {}).get("content") or "").strip()
    if not text:
        return None, "empty_response"
    return text, None


def packet_numbers(context, data):
    """Every figure the reply is allowed to keep."""
    import re

    found = allowed_numbers(data)
    for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", context or ""):
        try:
            found.append(float(match.group(0).replace(",", "")))
        except ValueError:
            continue
    return found


def _known_figure(number, allowed):
    for item in allowed:
        if abs(number - item) <= max(0.51, abs(item) * 0.002):
            return True
    for scale in (100000, 10000000):
        scaled = number * scale
        for item in allowed:
            if abs(scaled - item) <= max(1.0, abs(item) * 0.002):
                return True
    return False


def keep_known_figures(text, allowed):
    """Drop a model figure that is not in the packet. List numbers stay."""
    import re

    if not text:
        return text

    def swap(match):
        raw = match.group(0)
        start = match.start()
        if start == 0 or text[start - 1] in "\n":
            rest = text[match.end(): match.end() + 2]
            if raw.isdigit() and int(raw) <= 9 and rest.startswith("."):
                return raw
        token = raw.replace("₹", "").replace("%", "").replace(",", "")
        try:
            number = float(token)
        except ValueError:
            return raw
        if _known_figure(number, allowed):
            return raw
        return "not in the file"

    return re.sub(r"₹?\d[\d,]*(?:\.\d+)?%?", swap, text)


def produce_answer(question, data, owner, client=None, when_offline="notice", generated_by=""):
    """Ask the model with the data packet. Fall back only when that call fails."""
    context = build_context(question, data)
    local = answer_from_data(question, data, owner)
    messages = messages_for(question, context)
    result = {
        "text": local.get("text") or "",
        "as_of": local.get("as_of") or "",
        "table": local.get("table"),
        "chart": local.get("chart"),
        "followups": local.get("followups") or [],
        "topic": local.get("topic") or "",
        "actions": local.get("actions") or [],
        "calendar": local.get("calendar"),
        "context": context,
        "messages": messages,
        "model": None,
        "fallback": None,
    }
    if _mock_on():
        result["text"] = "Mock answer. " + result["text"]
        result["fallback"] = "mock"
        _log_ask(None, "mock")
        return _deliver(result, question, data, owner, generated_by)
    from app.chat.daily_review import section_id
    if section_id(question):
        # The file answer already applied the week rules. The model must not rewrite it.
        _log_ask("file", None)
        return _deliver(result, question, data, owner, generated_by)
    from app.chat.month_sales import use_file_answer

    if use_file_answer(question, local):
        # File-backed calendar-month totals. The model does not get to rewrite them.
        _log_ask("file", None)
        return _deliver(result, question, data, owner, generated_by)
    if not os.environ.get("CHAT_API_KEY", "").strip() and client is None:
        result["fallback"] = "no_key"
        _log_ask(None, "no_key")
        if when_offline == "notice" and os.environ.get("CHAT_SHOW_LOCAL", "").strip() != "1":
            result["text"] = NOT_CONNECTED
            result["table"] = None
            result["chart"] = None
            result["calendar"] = None
        return _deliver(result, question, data, owner, generated_by)
    chosen = model_name()
    if client is not None:
        text, error = client(messages, chosen)
    else:
        from app.chat.router import run_tool_loop

        text, error = run_tool_loop(
            messages,
            data.get("role") or "ops",
            complete_message,
            chosen,
        )
        if error:
            text, error = complete_chat(messages, chosen)
    if error or not text:
        result["text"] = AI_UNAVAILABLE + " " + (local.get("text") or "")
        result["fallback"] = error or "empty_response"
        _log_ask(None, result["fallback"])
        return _deliver(result, question, data, owner, generated_by)
    allowed = packet_numbers(context, data)
    prose, chart = _pull_chart(text, allowed)
    prose = keep_known_figures(prose, allowed)
    result["text"] = prose
    result["chart"] = chart
    result["table"] = None
    result["model"] = chosen
    result["fallback"] = None
    _log_ask(chosen, None)
    return _deliver(result, question, data, owner, generated_by)


def _deliver(result, question, data, owner, generated_by=""):
    """When someone asks for a file or a table, attach a report from loaded figures."""
    from app.chat.report import asks_for_file, build_report

    if not asks_for_file(question):
        return result
    result["report"] = build_report(
        question, data, owner, result.get("text") or "", generated_by=generated_by,
    )
    report = result["report"]
    if not result.get("table"):
        result["table"] = _table_from_report(report)
    note = "The PDF and the Excel file are ready with this answer."
    text = result.get("text") or ""
    if note not in text:
        result["text"] = (text.rstrip() + "\n\n" + note).strip()
    return result


def _table_from_report(report):
    tables = [table for table in (report.get("tables") or []) if table.get("columns") and table.get("rows")]
    if not tables:
        return None
    chosen = tables[-1] if tables[0].get("name") == "Not on this login" and len(tables) > 1 else tables[0]
    columns = [column for column in chosen.get("columns") or [] if column != "Coverage"]
    rows = []
    for row in chosen.get("rows") or []:
        rows.append(list(row)[: len(columns)])
    if not rows:
        return None
    return {"title": chosen.get("name") or "Report", "columns": columns, "rows": rows[:10]}


def stream_pieces(text):
    """Split a reply for streaming without eating newlines or markdown."""
    if not text:
        return
    size = 80
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(" ", start + 20, end)
            if cut > start:
                end = cut + 1
        yield text[start:end]
        start = end


def iter_answer(question, email, client=None):
    """SSE events. The model writes the answer when a key is set."""
    from app.chat.limit import allow

    if not allow(email or "anonymous"):
        _log_ask(None, "rate_limit")
        yield _event({"text": "Too many questions just now. Wait a few minutes and try again.", "done": True})
        return
    data = view_for(email)
    owner = _owner(email)
    produced = produce_answer(question, data, owner, client=client, generated_by=email or "")
    role = data.get("role") or "ops"
    ask_id = record_ask(question, produced.get("topic") or "", produced.get("as_of") or "", role, "person", "")
    record_gap(question, produced.get("topic") or "", produced.get("text") or "", produced.get("as_of") or "", role, "person", "")
    text = produced.get("text") or ""
    for piece in stream_pieces(text):
        yield _event({"text": piece})
    yield _event({
        "done": True,
        "markdown": text,
        "as_of": produced.get("as_of") or "",
        "table": produced.get("table"),
        "chart": produced.get("chart"),
        "calendar": produced.get("calendar"),
        "report": bool(produced.get("report")),
        "followups": produced.get("followups") or [],
        "topic": produced.get("topic") or "",
        "ask_id": ask_id,
        "mock": _mock_on(),
        "fallback": produced.get("fallback"),
    })


def _owner(email):
    from app.access import is_owner
    return is_owner(email)

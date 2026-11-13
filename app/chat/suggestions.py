"""Suggested questions. Finance chips are owner-only, and a chip is hidden when its data is not loaded."""

SALES = (
    "How are we tracking against this month's target?",
    "Which stores are behind pace this week?",
    "How did yesterday compare with the forecast?",
    "Which stores grew or dropped the most week on week?",
)
FINANCE = (
    "Which bank payments aren't booked in Tally yet?",
    "What's each company's profit this month?",
)
PROCUREMENT = (
    "Which items did we buy above average price this week?",
    "What are we paying for milk, paneer and cheese this month vs last?",
)
REELO = (
    "Which stores are capturing the fewest customer phone numbers?",
    "Which stores have the lowest repeat-customer share this month?",
)
AUDIT = (
    "Which stores scored lowest in the October mystery audit?",
)
TALLY = (
    "What did we pay in Delhi on 2 Nov?",
    "Top 10 payments in Kolkata in October",
)


def chips(owner, sales=False, finance=False, procurement=False, ingredients=False, reelo=False, audit=False, limit=4):
    """A handful of questions this person can ask with the data that is loaded."""
    from app.chat.memory import learned_questions

    pool = []
    if audit:
        pool.append(AUDIT[0])
    for item in learned_questions("owner" if owner else "ops"):
        pool.append(item)
    if sales:
        pool.append(SALES[0])
    if owner and finance:
        pool.append(FINANCE[1])
    if procurement:
        pool.append(PROCUREMENT[0])
    if reelo:
        pool.append(REELO[0])
    if sales and len(pool) < limit:
        pool.append(SALES[3])
    if ingredients and len(pool) < limit:
        pool.append(PROCUREMENT[1])
    if reelo and len(pool) < limit:
        pool.append(REELO[1])
    if sales and len(pool) < limit:
        pool.append(SALES[2])
    if owner and finance and len(pool) < limit:
        pool.append(FINANCE[0])
    if sales and len(pool) < limit:
        pool.append(SALES[1])
    seen = []
    for item in pool:
        if item not in seen:
            seen.append(item)
        if len(seen) >= limit:
            break
    return seen

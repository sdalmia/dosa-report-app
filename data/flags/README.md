# Red flags

Drop one CSV per area owner. The dashboard reads every `data/flags/*.csv`.

Expected names from the other feeds:

- `tony.csv`
- `logan.csv`
- `alfred.csv`
- `hr.csv`
- `accountant.csv`
- `procurement.csv`

Any other `*.csv` in this folder is read too. The newest wording wins by being in the file. There is no sample file in git on purpose.

## Columns

Header row, in any order. Names are matched without regard to case.

```text
area,severity,title,detail,owner,as_of,source
```

- `area`: `sales`, `reputation`, `procurement`, `people`, `accounts`, `tech`, `marketing`, `training`, or another short word. Marketing and training are shown under that area. They are not folded into a different group.
- `severity`: `red` or `amber`.
- `title`: one short line. Required.
- `detail`: optional, one line.
- `owner`: who should act.
- `as_of`: `YYYY-MM-DD`. A flag older than 7 days is hidden.
- `source`: where the line came from.

A row with a bad severity, a missing title, or a date that cannot be read is skipped and logged. The rest of the file still loads.

## Who can see them

`accounts` and `people` are owner-only. The server checks the Google email against `OWNER_EMAILS` (see the repo README) and removes those rows from the strip, from `/flags`, and from `/flags.json`. Other areas, including `marketing` and `training`, stay visible to every signed-in user.

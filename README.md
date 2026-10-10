# 💾 Dosa Report App

**Dosa Report App** is a lightweight internal tool built for the operations and accounts team at [Dosa Coffee](https://dosacoffee.in). It automates the process of uploading multiple Excel reports and generates a consolidated master output file, reducing manual effort and ensuring standardization across locations.

---

## 🚀 Features

- Upload multiple Excel reports via a simple web interface
- Intelligent parsing, cleaning, and merging of data
- Download a consolidated master report in one click
- Optimized for Dosa Coffee’s multi-outlet reporting workflows
- Hosted with secure Google OAuth login for internal team access

---

## 💠 Tech Stack

- **Backend**: Python, Flask
- **Frontend**: HTML (Jinja templates), Bootstrap (light styling)
- **Auth**: Google OAuth2
- **Deployment**: Render. Start command: `gunicorn -c gunicorn.conf.py run:app` (2 threaded workers, recycle after 500 requests).
- **Version Control**: GitHub

## Phone pages

Every page extends `base.html`, which defers `command.js`, `list-search.js`, and `lazy-section.js`, and compresses responses with Brotli or gzip. Static files are cached for a day.

Put the threats and the key numbers in the first response. Put everything below that in a fragment:

```jinja
{% from "_lazy.html" import lazy_section %}
{{ lazy_section(url_for('blueprint.section_fragment'), height=320, title='Stores', prefetch=true) }}
```

`height` is the skeleton's fixed min-height, so the numbers above it do not jump. `prefetch=true` fetches the next section when the phone is idle. The browser loads the fragment when it scrolls into view, or when a `<details class="lazy-section">` is opened. `static/js/lazy-section.js` does that, then calls `refreshLists()` so the shared search binds to the new markup.

The fragment route must use the same `@login_required` or `@owner_required` check as the page. Location finder stays public. Return `html_fragment(render_template(...))` from `app.fragments` so the response has a private cache and an ETag. Long lists use `slice_rows` (20 at a time) and a Show more button (`data-more`). If the list is paginated, set `data-search-src` on the `[data-list]` so search still covers every row, not only the ones on screen.

Cache the computed aggregate with `remember(key, builder)` in `app.page_cache`. The cache key should include the filters. It drops when a data file's mtime changes, including the directories named by `STORE_HEALTH_DATA_DIR` and `PROCUREMENT_DATA_DIR`. Do not mutate the cached object, and do not cache the raw 75,800-row cost-line files.

Forms (uploads, menu history, the P&L, the home page) stay on the first response. A page that is itself the threat list, such as Red flags, stays on the first response too. The ingredient tracker keeps the search and the top ingredients on the first response, and loads the price series from `/ingredient-tracker/data.json` when the chart area appears.

---

## 📦 Setup Instructions (Local Development)

### 1. Clone the Repository

```bash
git clone https://github.com/sdalmia/dosa-report-app.git
cd dosa-report-app
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

Create a `.env` file in the root directory:

```ini
FLASK_APP=app.py
FLASK_ENV=development
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
SECRET_KEY=your_flask_secret_key
OWNER_EMAILS=siddhant@dalgreenfoods.com,dalmia.siddhant@gmail.com
```

`OWNER_EMAILS` is a comma-separated list of Google sign-in emails. Set it in Render. When it is missing or blank, the app uses `siddhant@dalgreenfoods.com` and `dalmia.siddhant@gmail.com`. Those accounts can see flags with area `accounts` or `people`, and any future accounts or HR page. Every other signed-in user does not receive those rows in the dashboard, on `/flags`, or in `/flags.json`.

> Need help automating this? Let me know.

### 5. Run the App

```bash
flask run
```

---

## 🔐 Authentication

Only users logged in with a Dosa Coffee Google Workspace account (or whitelisted accounts) can access the app. OAuth is enforced on upload/download routes to ensure internal use only.

---

## 📁 File Structure

```bash
.
├── app.py                 # Main Flask app
├── templates/             # HTML files
├── static/                # CSS and assets (if any)
├── logic/                 # Custom report processing scripts
├── requirements.txt       # Python dependencies
└── .env.example           # Template for environment variables
```

---

## 🧠 Roadmap (Planned)

- [ ] Drag-and-drop upload interface
- [ ] Upload history and logs
- [ ] Error reports for corrupted or mismatched files
- [ ] Multi-format output (Excel + CSV)
- [ ] Automated email of master report post-processing

---

## 👤 Maintainer

**Siddhant Dalmia**  
Founder, Dosa Coffee  
[GitHub Profile](https://github.com/sdalmia)

---

## 📜 License

MIT License – see `LICENSE` file for details.

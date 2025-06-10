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
- **Deployment**: Render
- **Version Control**: GitHub

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
```

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

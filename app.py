import os
from flask import Flask, render_template, request, send_file, redirect, url_for, session, flash
from dotenv import load_dotenv
from generate_master_payout import process_uploaded_files
from auth import auth_bp, google_bp
from flask_dance.contrib.google import google
from flask_mail import Mail, Message

# --- Load environment variables ---
load_dotenv() # only when not in production

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# --- Email Configuration ---
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))  # default to 587 if not set
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

# --- File Upload Configuration ---
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- Register Blueprints ---
app.register_blueprint(google_bp, url_prefix="/login")
app.register_blueprint(auth_bp)

# --- Routes ---

@app.route("/")
def home():
    return redirect(url_for("upload_index"))

@app.route('/upload', methods=['GET', 'POST'])
def upload_index():
    logs = []

    # Don't redirect to login — just show login button if unauthorized
    if not google.authorized or 'user_email' not in session:
        return render_template('index.html')

    # Process file uploads
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        file_paths = []

        for file in uploaded_files:
            if file.filename:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(file_path)
                file_paths.append(file_path)

        try:
            output_file, logs = process_uploaded_files(file_paths, app.config['OUTPUT_FOLDER'])

            if output_file:
                user_email = session.get("user_email")
                user_name = session.get("user_name", "User")

                try:
                    msg = Message(
                        subject="✅ Your Dosa Coffee Master Report is Ready",
                        recipients=[user_email],
                        body=(
                            f"Hi {user_name},\n\n"
                            "Attached is your consolidated Zomato master payout report.\n\n"
                            "You can also download it from the web interface anytime.\n\n"
                            "Regards,\nDosa Coffee Automation System"
                        )
                    )

                    with app.open_resource(output_file) as fp:
                        msg.attach(
                            filename=os.path.basename(output_file),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            data=fp.read()
                        )

                    mail.send(msg)
                    logs.append(f"📧 Sent report to {user_email}")
                except Exception as e:
                    logs.append(f"⚠️ Failed to send email: {str(e)}")

                output_filename = os.path.basename(output_file)
                download_link = f"/download/{output_filename}"
                return render_template('index.html', logs=logs, download_link=download_link)

            return render_template('index.html', logs=logs)

        except Exception as e:
            return render_template('index.html', logs=[f"❌ Unexpected error: {str(e)}"])

    # GET request — just show the page
    return render_template('index.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], filename), as_attachment=True)

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True)

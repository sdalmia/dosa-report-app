import os
from flask import Blueprint, render_template, request, send_file, session, make_response
from flask_dance.contrib.google import google
from generate_master_payout import process_uploaded_files
from flask_mail import Message
from app.mail import mail
from app.routes.main import login_required

uploader_bp = Blueprint('uploader', __name__)

# Always resolve outputs relative to this file (inside /app/routes)
BASE_DIR = os.path.dirname(__file__)  # -> /dosa-report-app/app/routes
OUTPUT_FOLDER = os.path.join(BASE_DIR, "outputs")

@uploader_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_index():
    logs = []
    download_link = None

    # If user is not logged in, prompt them to login (but still show index.html with login CTA)
    # if not google.authorized or 'user_email' not in session or 'user_name' not in session:
    # if 'user_name' not in session :
    #     print("Some issue in uploader() - check 1")
    #     return render_template('index.html', logs=[], download_link=None)

    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        file_paths = []

        upload_dir = os.getenv("UPLOAD_FOLDER", "uploads")
        # output_dir = os.getenv("OUTPUT_FOLDER", "outputs")

        output_dir = os.path.join(os.path.dirname(__file__), os.getenv("OUTPUT_FOLDER", "outputs"))

        print ("✅ Output folder Current | We are in Uploader.py and the Base Directory is :" + str(os.path.dirname(__file__)))
        print ("✅ Output folder Current | We are in Uploader.py and the output path is :" + str(output_dir))

        os.makedirs(upload_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        for file in uploaded_files:
            if file.filename:
                path = os.path.join(upload_dir, file.filename)
                file.save(path)
                file_paths.append(path)

        try:
            print("Sending Files for Processing!")

            output_file, logs, output_filename = process_uploaded_files(file_paths, OUTPUT_FOLDER)

            if output_file:
                # Attempt to send email
                try:
                    msg = Message(
                        subject="✅ Your Dosa Coffee Master Report is Ready",
                        recipients=[session.get('user_email')],
                        body=f"Hi {session.get('user_name', 'User')},\n\nYour Zomato payout report is ready.\n\n– Dosa Coffee"
                    )
                    with open(output_file, 'rb') as f:
                        msg.attach(
                            os.path.basename(output_file),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            f.read()
                        )
                    mail.send(msg)
                    logs.append(f"📧 Sent report to {session['user_email']}")
                except Exception as e:
                    logs.append(f"⚠️ Failed to send email: {e}")

                download_link = f"/download/{output_filename}"

        except Exception as e:
            logs.append(f"❌ Error during processing: {e}")

    return render_template('index.html', logs=logs, download_link=download_link)




@uploader_bp.route('/download/<filename>')
@login_required
def download_file(filename):

    # output_folder =  os.getenv("OUTPUT_FOLDER", "outputs")

    path = os.path.join(OUTPUT_FOLDER, filename)

    print(f"📥 Attempting download: {filename}")
    print(f"📂 Full path: {path}")

    if not os.path.exists(path):
        print(f"❌ File not found at path: {path}")
        return f"❌ File not found: {filename}", 404

    print("✅ File found, sending to user...")
    return send_file(path, as_attachment=True)



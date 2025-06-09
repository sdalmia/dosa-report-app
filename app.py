# app.py

from flask import Flask, render_template, request, send_file
import os
from generate_master_payout import process_uploaded_files

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_files = request.files.getlist('files')
        file_paths = []

        for file in uploaded_files:
            if file.filename != '':
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(file_path)
                file_paths.append(file_path)

        try:
            output_file, logs = process_uploaded_files(file_paths, app.config['OUTPUT_FOLDER'])
            if output_file:
                output_filename = os.path.basename(output_file)
                download_link = f"/download/{output_filename}"
                return render_template('index.html', logs=logs, download_link=download_link)
            else:
                return render_template('index.html', logs=logs)
        except Exception as e:
            return render_template('index.html', logs=[f"❌ Unexpected error: {str(e)}"])

    return render_template('index.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
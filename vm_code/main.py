"""Main app script."""
from datetime import datetime
import os
import subprocess

from flask import abort, Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

import helper_functions

app = Flask(
    __name__,
    static_url_path='',
    static_folder='../web_interface')
app.config['UPLOAD_EXTENSIONS'] = ['.wav', '.mp3']
app.config['UPLOAD_PATH'] = 'uploads'
app.config['DOWNLOAD_PATH'] = 'downloads'
app.config['REGION'] = 'europe-west4'
app.config['BUCKET_NAME'] = (
    'gs://ddsp-train-' +
    str(int((datetime.now()-datetime(1970, 1, 1)).total_seconds())))
app.config['PREPROCESSING_JOB_NAME'] = ''
app.config['JOB_NAME'] = ''

# Create a directory in a known location to save files to.
uploads_dir = os.path.join(app.instance_path, app.config['UPLOAD_PATH'])
os.makedirs(uploads_dir, exist_ok=True)
downloads_dir = os.path.join(app.instance_path, app.config['DOWNLOAD_PATH'])
os.makedirs(downloads_dir, exist_ok=True)

@app.route('/')
def main():
  return render_template('index_vm.html')

@app.route('/upload', methods=['POST'])
def upload_files():
  for uploaded_file in request.files.getlist('file'):
    filename = secure_filename(uploaded_file.filename)
    if filename != '':
      file_ext = os.path.splitext(filename)[1]
      if file_ext not in app.config['UPLOAD_EXTENSIONS']:
        abort(400)
      uploaded_file.save(os.path.join(uploads_dir, filename))
  helper_functions.create_bucket(
      app.config['BUCKET_NAME'],
      app.config['REGION'])
  helper_functions.upload_blob(app.config['BUCKET_NAME'], uploads_dir)
  return render_template('index_vm.html')

@app.route('/preprocess', methods=['POST'])
def preprocess():
  status = helper_functions.run_preprocessing(
      app.config['BUCKET_NAME'],
      app.config['REGION'])
  if status == 'DOCKER_IMAGE_ERROR':
    message = (
        'Docker image is not ready for preprocessing. '
        'Try once more in a minute!')
  elif status == 'ERROR':
    message = 'There was a problem running preprocessing. Try once more!'
  else:
    app.config['PREPROCESSING_JOB_NAME'] = status
    message = 'Preprocessing started successfully!'
  return render_template('index_vm.html', message=message)

@app.route('/submit', methods=['POST'])
def job_submission():
  print(request.form)
  status = helper_functions.submit_job(
      request,
      app.config['BUCKET_NAME'],
      app.config['REGION'],
      app.config['PREPROCESSING_JOB_NAME'])
  if status == 'DOCKER_IMAGE_ERROR':
    message = (
        'Docker image is not ready for training. '
        'Try once more in a minute!')
  elif status == 'QUOTA_ERROR':
    message = (
        'Your project doesn\'t have enough quota '
        'for this setup. Try smaller batch size!')
  elif status == 'ERROR':
    message = 'There was a problem starting training. Try once more!'
  elif status == 'PREPROCESSING_NOT_FINISHED':
    message = 'Preprocessing is not yet finished. Try once more in a minute!'
  elif status == 'PREPROCESSING_ERROR':
    message = 'Preprocessing job failed. Run it once more!'
  elif status == 'PREPROCESSING_NOT_SUBMITTED':
    message = 'You haven\'t preprocessed the data!'
  else:
    app.config['JOB_NAME'] = status
    message = 'Training started successfully!'
  return render_template('index_vm.html', message=message)

@app.route('/check_status', methods=['POST'])
def check_status():
  if app.config['JOB_NAME']:
    status = helper_functions.check_job_status(app.config['JOB_NAME'])
    if status == 'JOB_NOT_EXIST':
      message = 'You haven\'t submitted training job yet!'
    else:
      message = 'Training job status: ' + status
  else:
    message = 'You haven\'t submitted training job yet!'

  return render_template('index_vm.html', message=message)

@app.route('/download', methods=['POST'])
def download_model():
  if app.config['JOB_NAME']:
    status = helper_functions.check_job_status(app.config['JOB_NAME'])
    if status == 'JOB_NOT_EXIST':
      message = 'You haven\'t submitted training job yet!'
      return render_template('index_vm.html', message=message)
    elif status == 'SUCCEEDED':
      helper_functions.get_model(app.config['BUCKET_NAME'],
                                 downloads_dir, app.instance_path)
      download_zip = os.path.join(app.instance_path, 'model.zip')
      return send_file(download_zip, as_attachment=True)
    else:
      message = 'Training job status: ' + status
      return render_template('index_vm.html', message=message)
  else:
    message = 'You haven\'t submitted training job yet!'
    return render_template('index_vm.html', message=message)

@app.route('/delete_bucket', methods=['POST'])
def delete_bucket():
  status = helper_functions.delete_bucket(app.config['BUCKET_NAME'])
  if status == 'ERROR':
    message = 'There was a problem deleting bucket :/'
  else:
    message = 'Bucket deleted successfully!'
  return render_template('index_vm.html', message=message)


@app.route('/tensorboard', methods=['POST'])
def enable_tensorboard():
  if app.config['JOB_NAME']:
    status = helper_functions.check_job_status(app.config['JOB_NAME'])
    if status == 'JOB_NOT_EXIST':
      message = 'You haven\'t submitted training job yet!'
      return render_template('index_vm.html', message=message)
    elif status == 'RUNNING':
      tensorboard_command = ('tensorboard --logdir ' +
                             app.config['BUCKET_NAME'] + '/model ' +
                             '--port 6006 --bind_all &')
      os.system(tensorboard_command)
      get_ip_command = ('gcloud compute instances describe ddsp-docker '
                        '--zone=europe-west4-a '
                        '--format=\'get(networkInterfaces[0]'
                        '.accessConfigs[0].natIP)\'')
      link = subprocess.check_output(get_ip_command, shell=True)
      link = str(link)
      link = link[2:-3]
      link = 'http://' + link + ':6006/'
      return render_template('index_vm.html', link=link)
    else:
      message = 'Training job status: ' + status
      return render_template('index_vm.html', message=message)
  else:
    message = 'You haven\'t submitted training job yet!'
    return render_template('index_vm.html', message=message)

if __name__ == '__main__':
  app.run(host='127.0.0.1', port=8080, debug=True)

"""`main` is the top level module for your Flask application."""

# Import the Flask Framework and modules
from flask import Flask
from flask.ext.dropbox import Dropbox, DropboxBlueprint
from flask import url_for, redirect, request, render_template
from flask import g, request, session as flask_session, url_for

# Google NDB
from google.appengine.ext import ndb

# Google Cloud Storage
import cloudstorage as gcs
from google.appengine.api import app_identity

# App engine specific urlfetch
from google.appengine.api import urlfetch

# utilities
import datetime
from poster.encode import multipart_encode
from poster.streaminghttp import register_openers
import json
import base64
import os
import uuid

# our own Dropbox Client reference
from dropbox.client import DropboxClient
from dropbox.session import DropboxSession

# our app settings are stored here.
import settings

import logging
logger = logging.getLogger('sketchfab-upload')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
logger.addHandler(ch)

app = Flask(__name__)
# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

app.config.from_object(settings)

dropbox = Dropbox(app)
dropbox.register_blueprint(url_prefix='/dropbox')

register_openers()

# Models
class User(ndb.Model):
  """Models an individual User entry with dropbox credentials and sketchfab API key."""
  dropbox_uid = ndb.IntegerProperty()
  dropbox_email = ndb.StringProperty()
  dropbox_access_token_key = ndb.StringProperty()
  dropbox_access_token_secret = ndb.StringProperty()
  dropbox_cursor = ndb.StringProperty()
  sketchfab_api_token = ndb.StringProperty()
  created_date = ndb.DateTimeProperty(auto_now_add=True)
  last_login_date = ndb.DateTimeProperty()
  last_check_date = ndb.DateTimeProperty()

class Upload(ndb.Model):
  """Models an individual Upload entry."""
  sketchfab_api_token = ndb.StringProperty()
  sketchfab_model_id = ndb.StringProperty()
  dropbox_path = ndb.StringProperty()
  createdDate = ndb.DateTimeProperty(auto_now_add=True)
  updatedDate = ndb.DateTimeProperty()

# routes

@app.route('/')
def home():
    return render_template('home.html',
                authenticated=dropbox.is_authenticated,
                login_url = dropbox.login_url,
                logout_url = dropbox.logout_url)

@app.route('/welcome')
def welcome():
    # save user info
    key, secret = flask_session['dropbox_access_token']
    uid = dropbox.account_info['uid']

    user = User.query(User.dropbox_uid == uid).get()
    if user:
        logger.info('Got returning user')
        user.populate(
                    dropbox_email = dropbox.account_info['email'],
                    dropbox_access_token_key = key,
                    dropbox_access_token_secret = secret,
                    last_login_date = datetime.datetime.now())
    else:
        logger.info('New user')
        user = User(dropbox_uid=dropbox.account_info['uid'],
                    dropbox_email = dropbox.account_info['email'],
                    dropbox_access_token_key = key,
                    dropbox_access_token_secret = secret,
                    last_login_date = datetime.datetime.now())
    logger.info(u'user %s' % (user.dropbox_uid))
    user.put()

    return render_template('welcome.html')

@app.route('/sketchfabtoken', methods=('GET', 'POST'))
def sketchfabtoken():
    if request.method == 'POST':
        logger.info('got sketchfab API token')
        token = request.form['sketchfabapi']
        uid = dropbox.account_info['uid']
        user = User.query(User.dropbox_uid == uid).get()
        if user:
            user.populate(sketchfab_api_token = token)
            user.put()
            return redirect(url_for('done'))
        else:
            logger.error(u'user %s not found' % uid)
            return 'Sorry, user cannot be found', 500

    return redirect(url_for('home'))

@app.route('/done')
def done():
    return render_template('done.html')


@app.route('/success/<path:filename>')
def success(filename):

    return u'File successfully uploaded as /%s' % filename

@app.route('/upload', methods=('GET', 'POST'))
def upload():
    logger.info('Upload called')

    if not dropbox.is_authenticated:
        logger.info('Not logged')
        return redirect(url_for('home'))

    if request.method == 'POST':
        logger.info('POST received')
        logger.info(request.method)
        file_obj = request.files['file']
        logger.info('got file?')

        if file_obj:
            logger.info('got file')
            client = dropbox.client
            filename = file_obj.filename
            logger.info(filename)

            # Actual uploading process
            result = client.put_file('/' + filename, file_obj.read())
            logger.info('File put')

            path = result['path']

            # Test store something as an "upload"
            upload = Upload(dropbox_path=path,
                        sketchfab_model_id = "testmodelID")
            upload.put()

            return redirect(url_for('success', filename=path))

    logger.info('Display upload form')
    return u'<form action="" method="post" enctype="multipart/form-data">' \
           u'<input name="file" type="file">' \
           u'<input type="submit" value="Upload">' \
           u'</form>'

# temporary endpoint to check for new models
@app.route('/checkdropbox')
def checkdropbox():
    bucket_name = os.environ.get('BUCKET_NAME', app_identity.get_default_gcs_bucket_name())
    bucket = '/' + bucket_name

    users = User.query().order(-User.last_check_date).fetch(100)

    for user in users:
        logger.info(u'checking user %s' % user.dropbox_uid)


        session = dropbox.session
        session.set_token(user.dropbox_access_token_key, user.dropbox_access_token_secret)
        # session = DropboxSession(app.config.get(real_name), app.config.get(real_name), app.config.get(real_name))

        client = DropboxClient(session)
        # cursor keeps track of satte of files, everything we will get from this API is new and should be imported
        #deltas = client.delta()
        deltas = client.delta(user.dropbox_cursor)

        logger.info('Got response from Dropbox, number of deltas: %s' % len(deltas["entries"]))

        # store the cursor of the files states and update check date.
        user.populate(dropbox_cursor = deltas["cursor"], last_check_date = datetime.datetime.now())
        user.put()

        for delta in deltas["entries"]:
            #delta is ["path", "metadata"]
            if delta[1] and not delta[1]["is_dir"]:
                logger.info(u"New model from Dropbox: %s" % delta[0])

                upload = Upload.query(Upload.dropbox_path == delta[0], Upload.sketchfab_api_token == user.sketchfab_api_token).get()
                if upload:
                    logger.info(u"Existing Sketchfab model for this path and user, with id: %s" % upload.sketchfab_model_id)
                else:
                    upload = Upload(dropbox_path = delta[0], sketchfab_api_token = user.sketchfab_api_token)
                    logger.info(u"No existing Sketchfab model found")

                os.path.basename(delta[0])
                name, extension = os.path.splitext(os.path.basename(delta[0]))

                filename = uuid.uuid4().hex + extension
                full_file_path = bucket + '/' + filename

                logger.info(u"Storing file %s to Google Cloud Storage" % full_file_path)
                gcs_file = gcs.open(full_file_path, 'w')
                f = client.get_file(delta[0]).read()
                gcs_file.write(f)
                gcs_file.close()

                logger.info(u"Uploading model to Sketchfab's API, using token %s" % user.sketchfab_api_token)
                url="https://api.sketchfab.com/v1/models"
                data = {
                    'title': name,
                    'description': 'uploaded from Sketchfab-Dropbox',
                    'fileModel': gcs.open(full_file_path),
                    'filenameModel': filename,
                    'token': user.sketchfab_api_token
                }
                # TODO: if existing model ID, we should update the model, using a PUT request?

                datamulti, headers = multipart_encode(data)

                # FIXME we have issue with request size limitation : request size	10 megabytes, see https://developers.google.com/appengine/docs/python/urlfetch/#Python_Quotas_and_limits
                # we may need to use sockets, see https://developers.google.com/appengine/docs/python/sockets/#making_httplib_use_sockets

                response = urlfetch.fetch(url=url,
                              payload="".join(datamulti),
                              method=urlfetch.POST,
                              headers=headers)

                logger.info(u"response: code: %s content: %s" % (response.status_code, response.content))

                if response.status_code == 200:
                    response_json = json.loads(response.content)
                    # TODO check result.success
                    logger.info(u"saving sketchfab model with id %s" % response_json['result']['id'])
                    upload.populate(sketchfab_model_id = response_json['result']['id'])
                    upload.populate(updatedDate = datetime.datetime.now())
                    upload.put()

    return 'Aaaannnnnd done'


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404


@app.errorhandler(500)
def page_not_found(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500

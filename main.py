"""`main` is the top level module for your Flask application."""

# Import the Flask Framework
from flask import Flask
from flask.ext.dropbox import Dropbox, DropboxBlueprint
from flask import url_for, redirect, request

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

@app.route('/')
def home():
    return u'Click <a href="%s">here</a> to login with Dropbox.' % \
           dropbox.login_url

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

            path = result['path'].lstrip('/')
            return redirect(url_for('success', filename=path))

    logger.info('Display upload form')
    return u'<form action="" method="post" enctype="multipart/form-data">' \
           u'<input name="file" type="file">' \
           u'<input type="submit" value="Upload">' \
           u'</form>'

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404


@app.errorhandler(500)
def page_not_found(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500

import os
import logging
import re
import pymysql
import boto3
from flask import Flask, render_template, request, redirect, url_for, session, g
from flask_bcrypt import Bcrypt
from flask_session import Session
from functools import wraps
from werkzeug.utils import secure_filename

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder="templates")

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.secret_key = os.environ.get("SECRET_KEY", "default-secret-key")
Session(app)

# Initialize Bcrypt for password hashing
bcrypt = Bcrypt(app)

# AWS S3 Configuration
S3_BUCKET = os.environ.get("S3_BUCKET")
S3_REGION = os.environ.get("AWS_DEFAULT_REGION")

# Initialize S3 client (relying on IAM role for credentials)
s3_client = boto3.client('s3', region_name=S3_REGION)

# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}

# Admin-required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # Check if the user is an admin
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT is_admin FROM users WHERE id = %s", (session["user_id"],))
        user = cursor.fetchone()
        if user["is_admin"] != 1:
            return redirect(url_for("index"))  # Redirect if not admin
        return f(*args, **kwargs)
    return decorated_function

# Database connection function
def get_db():
    if 'db' not in g:
        db_host = os.environ.get('DB_HOST')
        db_user = os.environ.get('DB_USER')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME')

        # Log the database host
        logger.debug(f"Connecting to database at {db_host}")

        g.db = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name,
            cursorclass=pymysql.cursors.DictCursor
        )
    return g.db

# Close the database connection after each request
@app.teardown_appcontext
def close_connection(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Initialize tables before first request
@app.before_first_request
def initialize_tables():
    db = get_db()
    cursor = db.cursor()
    # Create tables if they do not exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        email VARCHAR(255) NOT NULL UNIQUE,
                        password VARCHAR(255) NOT NULL,
                        is_admin TINYINT DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS polls (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        poll TEXT NOT NULL,
                        creator_id INT NOT NULL,
                        FOREIGN KEY (creator_id) REFERENCES users(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS options (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        poll_id INT NOT NULL,
                        option_text TEXT NOT NULL,
                        votes INT DEFAULT 0,
                        FOREIGN KEY (poll_id) REFERENCES polls(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS comments (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        poll_id INT NOT NULL,
                        user_id INT NOT NULL,
                        comment TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        parent_comment_id INT,
                        FOREIGN KEY (poll_id) REFERENCES polls(id),
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (parent_comment_id) REFERENCES comments(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS votes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        poll_id INT NOT NULL,
                        user_id INT NOT NULL,
                        option_id INT NOT NULL,
                        FOREIGN KEY (poll_id) REFERENCES polls(id),
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (option_id) REFERENCES options(id),
                        UNIQUE(poll_id, user_id))''')
    db.commit()

# Check if file extension is allowed
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
# Routes

# Home route (index)
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))  # Redirect to login if user is not logged in

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM polls")
    polls = cursor.fetchall()

    my_polls = []
    if "user_id" in session:
        cursor.execute("SELECT * FROM polls WHERE creator_id = %s", (session["user_id"],))
        my_polls = cursor.fetchall()

    return render_template("index.html", polls=polls, my_polls=my_polls)

# Registration route
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # Password strength validation
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$', password):
            error = "Password must be at least 8 characters long, include uppercase, lowercase, number, and special character."
        else:
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            try:
                db = get_db()
                cursor = db.cursor()
                cursor.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_password))
                db.commit()

                # Invoke Lambda Function
                lambda_client = boto3.client('lambda', region_name=os.environ.get('AWS_DEFAULT_REGION'))

                payload = {'email': email}

                response = lambda_client.invoke(
                    FunctionName='welcome_email_function',
                    InvocationType='Event',
                    Payload=json.dumps(payload)
                )

                return redirect(url_for("login"))
            except pymysql.err.IntegrityError:
                error = "Email already exists. Please use a different one."

    return render_template("register.html", error=error)


# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["email"] = user["email"]  # Keep email in session if needed

            # Redirect based on admin status
            if user["is_admin"] == 1:
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("index"))
        else:
            error = "Invalid email or password."

    return render_template("login.html", error=error)

# Logout route
@app.route("/logout")
def logout():
    session.clear()  # Clear the session
    return redirect(url_for("login"))

# Poll details route
@app.route("/polls/<id>")
def polls(id):
    db = get_db()
    cursor = db.cursor()

    # Fetch the poll details
    cursor.execute("SELECT * FROM polls WHERE id = %s", (id,))
    poll = cursor.fetchone()

    # Fetch the options for the poll
    cursor.execute("SELECT * FROM options WHERE poll_id = %s", (id,))
    options = cursor.fetchall()

    # Fetch all comments and replies for the poll
    cursor.execute("""
        SELECT comments.*, users.email
        FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE poll_id = %s
        ORDER BY created_at ASC
        """, (id,))
    comments = cursor.fetchall()

    # Check if the user has already voted
    has_voted = False
    if "user_id" in session:
        cursor.execute("SELECT * FROM votes WHERE poll_id = %s AND user_id = %s", (id, session["user_id"]))
        vote = cursor.fetchone()
        if vote:
            has_voted = True

    if poll:
        return render_template("show_poll.html", poll=poll, options=options, comments=comments, has_voted=has_voted)
    else:
        return "Poll not found", 404

# Voting route
@app.route("/vote/<id>/<option_id>")
def vote(id, option_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    db = get_db()
    cursor = db.cursor()
    # Check if the user has already voted in this poll
    cursor.execute("SELECT * FROM votes WHERE poll_id = %s AND user_id = %s", (id, session["user_id"]))
    existing_vote = cursor.fetchone()
    if existing_vote:
        return "You have already voted in this poll."

    # Ensure the option belongs to the poll
    cursor.execute("SELECT * FROM options WHERE id = %s AND poll_id = %s", (option_id, id))
    option = cursor.fetchone()

    if option:
        # Record the vote
        try:
            cursor.execute("INSERT INTO votes (poll_id, user_id, option_id) VALUES (%s, %s, %s)", (id, session["user_id"], option_id))
            # Increment the vote count in the options table
            cursor.execute("UPDATE options SET votes = votes + 1 WHERE id = %s", (option_id,))
            db.commit()
            return redirect(url_for("polls", id=id))
        except pymysql.err.IntegrityError:
            return "You have already voted in this poll."
    else:
        return "Invalid option.", 400

# Create poll route
@app.route("/polls", methods=["GET", "POST"])
def create_poll():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        poll = request.form["poll"]
        options = request.form.getlist("options[]")
        creator_id = session["user_id"]

        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO polls (poll, creator_id) VALUES (%s, %s)", (poll, creator_id))
        poll_id = cursor.lastrowid

        for option in options:
            cursor.execute("INSERT INTO options (poll_id, option_text) VALUES (%s, %s)", (poll_id, option))

        db.commit()

        return redirect(url_for("index"))

    return render_template("new_poll.html")

# Route for viewing a user's polls
@app.route("/my_polls")
def my_polls():
    if "user_id" not in session:
        return redirect(url_for("login"))

    creator_id = session["user_id"]
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM polls WHERE creator_id = %s", (creator_id,))
    polls = cursor.fetchall()

    return render_template("my_polls.html", polls=polls)

# Add comment to poll route
@app.route("/add_comment/<int:poll_id>", methods=["POST"])
def add_comment(poll_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment_text = request.form["comment"]
    user_id = session["user_id"]

    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO comments (poll_id, user_id, comment) VALUES (%s, %s, %s)", (poll_id, user_id, comment_text))
    db.commit()  # Ensure the commit after inserting the comment

    return redirect(url_for("polls", id=poll_id))

# Add reply to comment route
@app.route("/add_reply/<int:poll_id>/<int:parent_comment_id>", methods=["POST"])
def add_reply(poll_id, parent_comment_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    reply_text = request.form["reply"]
    user_id = session["user_id"]

    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO comments (poll_id, user_id, comment, parent_comment_id) VALUES (%s, %s, %s, %s)",
                   (poll_id, user_id, reply_text, parent_comment_id))
    db.commit()  # Ensure the commit after inserting the reply

    return redirect(url_for("polls", id=poll_id))

# Admin dashboard
@app.route("/admin")
@admin_required
def admin_dashboard():
    # Fetch all polls
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM polls")
    polls = cursor.fetchall()

    # Fetch all users
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    return render_template("admin_dashboard.html", polls=polls, users=users)

# Admin delete user route
@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()

    return redirect(url_for("admin_dashboard"))

# Admin delete poll route
@app.route("/admin/delete_poll/<int:poll_id>", methods=["POST"])
@admin_required
def delete_poll(poll_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM polls WHERE id = %s", (poll_id,))
    cursor.execute("DELETE FROM options WHERE poll_id = %s", (poll_id,))
    db.commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/upload", methods=["GET", "POST"])
def upload_file():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        if 'file' not in request.files:
            return "No file part"
        file = request.files['file']
        if file.filename == '':
            return "No selected file"
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            s3_client.upload_fileobj(
                file,
                S3_BUCKET,
                filename,
                ExtraArgs={
                    "ACL": "public-read",
                    "ContentType": file.content_type
                }
            )
            file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{filename}"
            return f"File uploaded successfully. Accessible at {file_url}"

    return render_template("upload.html")

# Health check route for ALB
@app.route("/health")
def health():
    return "OK", 200

# 404 error handler
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

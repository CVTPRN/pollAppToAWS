import os
import logging
import pymysql
import bcrypt
from flask import Flask, render_template, request, redirect, url_for, make_response, g, session
from functools import wraps

# Setup logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app
app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get('SECRET_KEY', 'your_default_secret_key')

# Database connection function
def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD'],
            database=os.environ['DB_NAME'],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )
    return g.db

# Close database connection
@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Admin-required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT is_admin FROM users WHERE id = %s", (session["user_id"],))
            user = cur.fetchone()
            if user["is_admin"] != 1:
                return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function

# Ensure the tables are initialized
initialized = False

@app.before_request
def initialize_tables():
    global initialized
    if not initialized:
        db = get_db()
        with db.cursor() as cur:
            # Initialize users table
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            username VARCHAR(255) NOT NULL UNIQUE,
                            password VARCHAR(255) NOT NULL,
                            is_admin TINYINT(1) DEFAULT 0)''')

            # Initialize polls table
            cur.execute('''CREATE TABLE IF NOT EXISTS polls (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            poll TEXT NOT NULL,
                            creator_username VARCHAR(255) NOT NULL)''')

            # Initialize options table
            cur.execute('''CREATE TABLE IF NOT EXISTS options (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            poll_id INT NOT NULL,
                            option_text TEXT NOT NULL,
                            votes INT DEFAULT 0,
                            FOREIGN KEY (poll_id) REFERENCES polls(id))''')

            # Initialize comments table
            cur.execute('''CREATE TABLE IF NOT EXISTS comments (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            poll_id INT NOT NULL,
                            username VARCHAR(255) NOT NULL,
                            comment TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            parent_comment_id INT,
                            FOREIGN KEY (poll_id) REFERENCES polls(id))''')
        db.commit()
        initialized = True

# Routes

@app.route("/")
def index():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM polls")
        polls = cur.fetchall()

        my_polls = []
        if "user_id" in session:
            cur.execute("SELECT * FROM polls WHERE creator_username = %s", (session["username"],))
            my_polls = cur.fetchall()

    return render_template("index.html", polls=polls, my_polls=my_polls)

@app.route("/health")
def health_check():
    return "OK", 200

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        db = get_db()
        with db.cursor() as cur:
            try:
                cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
                db.commit()
                return redirect(url_for("login"))
            except pymysql.err.IntegrityError:
                return "Username already exists. Please choose another."
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cur.fetchone()

            if user and bcrypt.checkpw(password.encode('utf-8'), user["password"].encode('utf-8')):
                session["user_id"] = user["id"]
                session["username"] = user["username"]

                if user["is_admin"] == 1:
                    return redirect(url_for("admin_dashboard"))
                else:
                    return redirect(url_for("index"))
            else:
                return "Invalid username or password."
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/polls/<id>")
def polls(id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM polls WHERE id = %s", (id,))
        poll = cur.fetchone()

        cur.execute("SELECT * FROM options WHERE poll_id = %s", (id,))
        options = cur.fetchall()

        cur.execute("SELECT * FROM comments WHERE poll_id = %s ORDER BY created_at ASC", (id,))
        comments = cur.fetchall()

    if poll:
        return render_template("show_poll.html", poll=poll, options=options, comments=comments)
    else:
        return "Poll not found", 404

@app.route("/vote/<id>/<option_id>")
def vote(id, option_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.cookies.get(f"vote_{id}_cookie") is None:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM options WHERE id = %s AND poll_id = %s", (option_id, id))
            option = cur.fetchone()

            if option:
                cur.execute("UPDATE options SET votes = votes + 1 WHERE id = %s", (option_id,))
                db.commit()

                response = make_response(redirect(url_for("polls", id=id)))
                response.set_cookie(f"vote_{id}_cookie", str(option_id))
                return response
            return "Invalid option", 400
    return f"Cannot vote more than once! Go back <a href='{url_for('polls', id=id)}'>here</a>"

@app.route("/polls", methods=["GET", "POST"])
def create_poll():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        poll = request.form["poll"]
        options = request.form.getlist("options[]")
        creator_username = session["username"]

        db = get_db()
        with db.cursor() as cur:
            cur.execute("INSERT INTO polls (poll, creator_username) VALUES (%s, %s)", (poll, creator_username))
            poll_id = cur.lastrowid

            for option in options:
                cur.execute("INSERT INTO options (poll_id, option_text) VALUES (%s, %s)", (poll_id, option))
            db.commit()

        return redirect(url_for("index"))
    return render_template("new_poll.html")

@app.route("/my_polls")
def my_polls():
    if "user_id" not in session:
        return redirect(url_for("login"))

    creator_username = session["username"]
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM polls WHERE creator_username = %s", (creator_username,))
        polls = cur.fetchall()

    return render_template("my_polls.html", polls=polls)

@app.route("/add_comment/<int:poll_id>", methods=["POST"])
def add_comment(poll_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    comment_text = request.form["comment"]
    username = session["username"]

    db = get_db()
    with db.cursor() as cur:
        cur.execute("INSERT INTO comments (poll_id, username, comment) VALUES (%s, %s, %s)",
                    (poll_id, username, comment_text))
        db.commit()

    return redirect(url_for("polls", id=poll_id))

@app.route("/add_reply/<int:poll_id>/<int:parent_comment_id>", methods=["POST"])
def add_reply(poll_id, parent_comment_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    reply_text = request.form["reply"]
    username = session["username"]

    db = get_db()
    with db.cursor() as cur:
        cur.execute("INSERT INTO comments (poll_id, username, comment, parent_comment_id) VALUES (%s, %s, %s, %s)",
                    (poll_id, username, reply_text, parent_comment_id))
        db.commit()

    return redirect(url_for("polls", id=poll_id))

@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM polls")
        polls = cur.fetchall()

        cur.execute("SELECT * FROM users")
        users = cur.fetchall()

    return render_template("admin_dashboard.html", polls=polls, users=users)

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == session["user_id"]:
        return redirect(url_for("admin_dashboard"))

    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()

    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete_poll/<int:poll_id>", methods=["POST"])
@admin_required
def delete_poll(poll_id):
    db = get_db()
    with db.cursor() as cur:
        cur.execute("DELETE FROM polls WHERE id = %s", (poll_id,))
        cur.execute("DELETE FROM options WHERE poll_id = %s", (poll_id,))
        db.commit()
    return redirect(url_for("admin_dashboard"))

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

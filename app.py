from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
import sqlite3
import os
import uuid
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ================= SECURITY =================
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key")

# ================= PATH =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lost_found.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ================= DB =================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ================= INIT DB =================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        description TEXT,
        location_found TEXT,
        status TEXT,
        image TEXT,
        reporter_name TEXT,
        reporter_phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS claimers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        course TEXT,
        lost_item TEXT,
        date_lost TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


# ================= AUTH DECORATORS =================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user") and not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("Admin access required!", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ================= HOME =================
@app.route("/")
def home():
    return render_template("index.html")


# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?,?,?)",
                (username, email, password),
            )
            conn.commit()
            flash("Registration successful!", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("User already exists!", "danger")
        finally:
            conn.close()

    return render_template("register.html")


# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        # ADMIN LOGIN
        if username == "admin" and password == "1234":
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user"] = user["username"]
            return redirect(url_for("report"))

        flash("Invalid login details", "danger")

    return render_template("login.html")


# ================= REPORT =================
@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    if request.method == "POST":
        file = request.files.get("image")

        if not file or file.filename == "":
            flash("Image required!", "danger")
            return redirect(url_for("report"))

        if "." not in file.filename:
            flash("Invalid file!", "danger")
            return redirect(url_for("report"))

        ext = file.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"

        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO items (
                item_name, description, location_found,
                status, image, reporter_name, reporter_phone
            )
            VALUES (?,?,?,?,?,?,?)
        """, (
            request.form.get("name"),
            request.form.get("description"),
            request.form.get("location"),
            request.form.get("status"),
            filename,
            request.form.get("reporter_name"),
            request.form.get("reporter_phone")
        ))
        conn.commit()
        conn.close()

        flash("Item reported successfully!", "success")
        return redirect(url_for("report"))

    return render_template("report.html", username=session.get("user"))


# ================= SEARCH =================
@app.route("/search")
def search():
    query = request.args.get("search", "")
    status = request.args.get("status", "")

    conn = get_db_connection()

    sql = "SELECT * FROM items WHERE 1=1"
    params = []

    if query:
        sql += " AND item_name LIKE ?"
        params.append(f"%{query}%")

    if status:
        sql += " AND status=?"
        params.append(status)

    sql += " ORDER BY id DESC"

    results = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template("search.html", results=results, query=query)


# ================= CLAIMER =================
@app.route("/claimer", methods=["GET", "POST"])
def claimer():
    if request.method == "POST":
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO claimers (name, phone, course, lost_item, date_lost)
            VALUES (?,?,?,?,?)
        """, (
            request.form.get("name"),
            request.form.get("phone"),
            request.form.get("course"),
            request.form.get("lost_item"),
            request.form.get("date_lost")
        ))
        conn.commit()
        conn.close()

        flash("Claim submitted successfully!", "success")
        return redirect(url_for("claimer"))

    return render_template("claimer.html")


# ================= ADMIN =================
@app.route("/admin_dashboard")
@admin_required
def admin_dashboard():
    conn = get_db_connection()

    users = conn.execute("SELECT * FROM users").fetchall()
    items = conn.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    claimers = conn.execute("SELECT * FROM claimers").fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        users=users,
        items=items,
        claimers=claimers
    )


# ================= DELETE =================
@app.route("/delete_item/<int:item_id>")
@admin_required
def delete_item(item_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))


@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))


@app.route("/delete_claimer/<int:claimer_id>")
@admin_required
def delete_claimer(claimer_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM claimers WHERE id=?", (claimer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))


# ================= QR =================
@app.route("/qr_scanner")
def qr_scanner():
    return render_template("qr_scanner.html")


# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

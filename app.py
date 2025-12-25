from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
)
import mysql.connector
from mysql.connector import Error
from config import DB_CONFIG, SECRET_KEY
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = SECRET_KEY

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)


def get_db_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapper


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if not name or not email or not password:
            flash("Name, email and password are required", "error")
            return render_template("signup.html")

        conn = get_db_connection()
        if not conn:
            flash("Database connection error", "error")
            return render_template("signup.html")

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            flash("Email already registered", "error")
            return render_template("signup.html")

        password_hash = generate_password_hash(password)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, email, role, password_hash) VALUES (%s, %s, %s, %s)",
            (name, email, "user", password_hash),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Signup successful. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db_connection()
        if not conn:
            flash("Database connection error", "error")
            return render_template("login.html")

        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, role, password_hash FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user or not user.get("password_hash") or not check_password_hash(
            user["password_hash"], password
        ):
            flash("Invalid email or password", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_role"] = user["role"]

        next_url = request.args.get("next") or url_for("index")
        return redirect(next_url)

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("login"))


@app.route("/")
def index():
    """If the user is not logged in show the public landing page.
    If logged in, show the dashboard with real-time stats."""
    if 'user_id' not in session:
        # Public landing page (no login required)
        return render_template('landing.html')
    stats = {
        "total_documents": 0,
        "total_categories": 0,
    }
    category_labels = []
    category_counts = []
    summary_labels = []
    summary_counts = []

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        # total documents
        cursor.execute("SELECT COUNT(*) FROM documents")
        stats["total_documents"] = cursor.fetchone()[0]

        # total categories
        cursor.execute("SELECT COUNT(*) FROM categories")
        stats["total_categories"] = cursor.fetchone()[0]

        # documents per category (for chart)
        cursor.execute(
            """
            SELECT COALESCE(c.name, 'Uncategorized') AS label, COUNT(d.id) AS total
            FROM categories c
            LEFT JOIN documents d ON d.category_id = c.id
            GROUP BY c.id, c.name
            ORDER BY label
            """
        )
        rows = cursor.fetchall()
        for label, total in rows:
            category_labels.append(label or "Uncategorized")
            category_counts.append(total)

        # overall summary counts (documents, categories, users, departments)
        try:
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
        except Exception:
            total_users = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM departments")
            total_departments = cursor.fetchone()[0]
        except Exception:
            total_departments = 0

        summary_labels = ["Documents", "Categories", "Users", "Departments"]
        summary_counts = [stats["total_documents"], stats["total_categories"], total_users, total_departments]

        cursor.close()
        conn.close()

    return render_template(
        "index.html",
        stats=stats,
        category_labels=category_labels,
        category_counts=category_counts,
        summary_labels=summary_labels,
        summary_counts=summary_counts,
    )


@app.route("/users")
@login_required
def users_page():
    conn = get_db_connection()
    users = []
    stats = {"total_users": 0, "admin_users": 0}
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, role FROM users ORDER BY id")
        users = cursor.fetchall()
        stats["total_users"] = len(users)
        stats["admin_users"] = sum(1 for u in users if str(u.get("role", "")).lower().startswith("admin"))
        cursor.close()
        conn.close()
    return render_template("users.html", users=users, stats=stats)


@app.route("/users/create", methods=["GET", "POST"])
@login_required
def user_create():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        role = request.form.get("role")

        if not name or not email or not role:
            flash("Name, email and role are required", "error")
            return render_template("user_form.html", user=None)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (name, email, role) VALUES (%s, %s, %s)",
                (name, email, role),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("User created", "success")
            return redirect(url_for("users_page"))

    return render_template("user_form.html", user=None)


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def user_edit(user_id):
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("users_page"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if not user:
        cursor.close()
        conn.close()
        flash("User not found", "error")
        return redirect(url_for("users_page"))

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        role = request.form.get("role")

        if not name or not email or not role:
            flash("Name, email and role are required", "error")
            return render_template("user_form.html", user=user)

        cursor.execute(
            "UPDATE users SET name = %s, email = %s, role = %s WHERE id = %s",
            (name, email, role, user_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("User updated", "success")
        return redirect(url_for("users_page"))

    cursor.close()
    conn.close()
    return render_template("user_form.html", user=user)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("User deleted", "success")
    return redirect(url_for("users_page"))


@app.route("/departments")
@login_required
def departments_page():
    conn = get_db_connection()
    departments = []
    stats = {"total_departments": 0}
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, description FROM departments ORDER BY name")
        departments = cursor.fetchall()
        stats["total_departments"] = len(departments)
        cursor.close()
        conn.close()
    return render_template("departments.html", departments=departments, stats=stats)


@app.route("/departments/create", methods=["GET", "POST"])
@login_required
def department_create():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")

        if not name:
            flash("Name is required", "error")
            return render_template("department_form.html", department=None)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO departments (name, description) VALUES (%s, %s)",
                (name, description),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Department created", "success")
            return redirect(url_for("departments_page"))

    return render_template("department_form.html", department=None)


@app.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@login_required
def department_edit(dept_id):
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("departments_page"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM departments WHERE id = %s", (dept_id,))
    department = cursor.fetchone()

    if not department:
        cursor.close()
        conn.close()
        flash("Department not found", "error")
        return redirect(url_for("departments_page"))

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")

        if not name:
            flash("Name is required", "error")
            return render_template("department_form.html", department=department)

        cursor.execute(
            "UPDATE departments SET name = %s, description = %s WHERE id = %s",
            (name, description, dept_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Department updated", "success")
        return redirect(url_for("departments_page"))

    cursor.close()
    conn.close()
    return render_template("department_form.html", department=department)


@app.route("/departments/<int:dept_id>/delete", methods=["POST"])
@login_required
def department_delete(dept_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM departments WHERE id = %s", (dept_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Department deleted", "success")
    return redirect(url_for("departments_page"))


@app.route("/reports")
@login_required
def reports_page():
    """Simple dynamic reports using summary counts from the database."""
    summary = {
        "total_documents": 0,
        "total_categories": 0,
        "total_departments": 0,
        "total_users": 0,
    }
    docs_by_category = []

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()

        # basic counts
        cursor.execute("SELECT COUNT(*) FROM documents")
        summary["total_documents"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM categories")
        summary["total_categories"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM departments")
        summary["total_departments"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        summary["total_users"] = cursor.fetchone()[0]

        # documents grouped by category
        cursor.execute(
            """
            SELECT COALESCE(c.name, 'Uncategorized') AS category_name,
                   COUNT(d.id) AS document_count
            FROM categories c
            LEFT JOIN documents d ON d.category_id = c.id
            GROUP BY c.id, c.name
            ORDER BY category_name
            """
        )
        docs_by_category = cursor.fetchall()

        cursor.close()
        conn.close()

    return render_template("reports.html", summary=summary, docs_by_category=docs_by_category)


@app.route('/about')
def about_page():
    return render_template('about.html')


@app.route('/contact')
def contact_page():
    return render_template('contact.html')


@app.route('/team')
def team_page():
    # Sample team members — replace or extend as needed
    members = [
        {
            'name': 'Alice Johnson',
            'role': 'Project Lead',
            'email': 'alice.johnson@example.com',
            'phone': '+1 555-0123',
            'photo': url_for('static', filename='img/team/alice.jpg')
        },
        {
            'name': 'Bob Martinez',
            'role': 'Backend Engineer',
            'email': 'bob.martinez@example.com',
            'phone': '+1 555-0456',
            'photo': url_for('static', filename='img/team/bob.jpg')
        },
        {
            'name': 'Carol Lee',
            'role': 'Frontend Engineer',
            'email': 'carol.lee@example.com',
            'phone': '+1 555-0789',
            'photo': url_for('static', filename='img/team/carol.jpg')
        }
    ]
    return render_template('team.html', members=members)


@app.route("/documents")
@login_required
def documents_list():
    conn = get_db_connection()
    documents = []
    stats = {"total_documents": 0, "uncategorized": 0}
    categories = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = """SELECT d.id, d.title, d.description, d.file_path, d.created_at, c.name AS category_name
                   FROM documents d
                   LEFT JOIN categories c ON d.category_id = c.id
                   ORDER BY d.id DESC"""
        cursor.execute(query)
        documents = cursor.fetchall()
        stats["total_documents"] = len(documents)
        stats["uncategorized"] = sum(1 for d in documents if not d.get("category_name"))

        # fetch categories for the create modal dropdown
        cursor.execute("SELECT id, name FROM categories ORDER BY name")
        categories = cursor.fetchall()

        cursor.close()
        conn.close()
    return render_template("documents_list.html", documents=documents, stats=stats, categories=categories)


@app.route("/my-dashboard")
@login_required
def user_dashboard():
    """Per-user dashboard showing only the current user's documents."""
    user_id = session.get("user_id")
    stats = {"total_documents": 0, "uncategorized": 0}
    documents = []

    conn = get_db_connection()
    if conn and user_id:
        cursor = conn.cursor(dictionary=True)
        query = """SELECT d.id, d.title, d.description, d.file_path, d.created_at, c.name AS category_name
                   FROM documents d
                   LEFT JOIN categories c ON d.category_id = c.id
                   WHERE d.owner_id = %s
                   ORDER BY d.id DESC"""
        cursor.execute(query, (user_id,))
        documents = cursor.fetchall()
        stats["total_documents"] = len(documents)
        stats["uncategorized"] = sum(1 for d in documents if not d.get("category_name"))
        cursor.close()
        conn.close()

    return render_template("user_dashboard.html", documents=documents, stats=stats)


@app.route("/documents/create", methods=["GET", "POST"])
@login_required
def document_create():
    conn = get_db_connection()
    categories = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name FROM categories ORDER BY name")
        categories = cursor.fetchall()
        cursor.close()

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        file_path = request.form.get("file_path")  # just store a simple path/text
        category_id = request.form.get("category_id") or None
        owner_id = session.get("user_id")

        if not title:
            flash("Title is required", "error")
            return render_template("document_form.html", categories=categories, document=None)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            insert_query = "INSERT INTO documents (title, description, file_path, category_id, owner_id) VALUES (%s, %s, %s, %s, %s)"
            cursor.execute(insert_query, (title, description, file_path, category_id, owner_id))
            conn.commit()
            cursor.close()
            conn.close()
            flash("Document created successfully", "success")
            return redirect(url_for("documents_list"))

    return render_template("document_form.html", categories=categories, document=None)


@app.route("/documents/<int:doc_id>/edit", methods=["GET", "POST"])
@login_required
def document_edit(doc_id):
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("documents_list"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
    document = cursor.fetchone()

    cursor.execute("SELECT id, name FROM categories ORDER BY name")
    categories = cursor.fetchall()

    if not document:
        cursor.close()
        conn.close()
        flash("Document not found", "error")
        return redirect(url_for("documents_list"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        file_path = request.form.get("file_path")
        category_id = request.form.get("category_id") or None

        if not title:
            flash("Title is required", "error")
            return render_template("document_form.html", categories=categories, document=document)

        update_query = """UPDATE documents
                         SET title = %s, description = %s, file_path = %s, category_id = %s
                         WHERE id = %s"""
        cursor.execute(update_query, (title, description, file_path, category_id, doc_id))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Document updated successfully", "success")
        return redirect(url_for("documents_list"))

    cursor.close()
    conn.close()
    return render_template("document_form.html", categories=categories, document=document)


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def document_delete(doc_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Document deleted", "success")
    return redirect(url_for("documents_list"))


@app.route("/categories")
@login_required
def categories_list():
    conn = get_db_connection()
    categories = []
    stats = {"total_categories": 0, "empty_categories": 0}
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, description FROM categories ORDER BY name")
        categories = cursor.fetchall()
        stats["total_categories"] = len(categories)

        # count documents per category to know which categories are empty
        cursor.execute(
            """SELECT category_id, COUNT(*) AS total
                FROM documents
                WHERE category_id IS NOT NULL
                GROUP BY category_id"""
        )
        counts = {row["category_id"]: row["total"] for row in cursor.fetchall()}
        stats["empty_categories"] = sum(1 for c in categories if counts.get(c["id"], 0) == 0)

        cursor.close()
        conn.close()
    return render_template("categories_list.html", categories=categories, stats=stats)


@app.route("/activity")
@login_required
def activity_page():
    """Simple activity page showing recent documents."""
    conn = get_db_connection()
    recent_docs = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, title, created_at FROM documents ORDER BY created_at DESC LIMIT 10"
        )
        recent_docs = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("activity.html", recent_docs=recent_docs)


@app.route("/categories/create", methods=["GET", "POST"])
@login_required
def category_create():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")

        if not name:
            flash("Name is required", "error")
            return render_template("category_form.html", category=None)

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO categories (name, description) VALUES (%s, %s)",
                (name, description),
            )
            conn.commit()
            cursor.close()
            conn.close()
            flash("Category created", "success")
            return redirect(url_for("categories_list"))

    return render_template("category_form.html", category=None)


@app.route("/categories/<int:cat_id>/edit", methods=["GET", "POST"])
@login_required
def category_edit(cat_id):
    conn = get_db_connection()
    if not conn:
        flash("Database connection error", "error")
        return redirect(url_for("categories_list"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM categories WHERE id = %s", (cat_id,))
    category = cursor.fetchone()

    if not category:
        cursor.close()
        conn.close()
        flash("Category not found", "error")
        return redirect(url_for("categories_list"))

    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")

        if not name:
            flash("Name is required", "error")
            return render_template("category_form.html", category=category)

        cursor.execute(
            "UPDATE categories SET name = %s, description = %s WHERE id = %s",
            (name, description, cat_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Category updated", "success")
        return redirect(url_for("categories_list"))

    cursor.close()
    conn.close()
    return render_template("category_form.html", category=category)


@app.route("/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def category_delete(cat_id):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE id = %s", (cat_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Category deleted", "success")
    return redirect(url_for("categories_list"))


@app.route("/file-manager")
@login_required
def file_manager_root():
    """Show top-level folders for the file manager."""
    conn = get_db_connection()
    folders = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, parent_id, created_at FROM file_folders WHERE parent_id IS NULL ORDER BY created_at DESC"
        )
        folders = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("file_manager.html", folders=folders, current_folder=None, files=[])


@app.route("/file-manager/folder/<int:folder_id>")
@login_required
def file_manager_folder(folder_id):
    """Show a specific folder and its files."""
    conn = get_db_connection()
    folder = None
    folders = []
    files = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, parent_id, created_at FROM file_folders WHERE id = %s", (folder_id,))
        folder = cursor.fetchone()

        cursor.execute(
            "SELECT id, name, parent_id, created_at FROM file_folders WHERE parent_id = %s ORDER BY created_at DESC",
            (folder_id,),
        )
        folders = cursor.fetchall()

        cursor.execute(
            "SELECT id, title, filename, stored_path, uploaded_at FROM folder_files WHERE folder_id = %s ORDER BY uploaded_at DESC",
            (folder_id,),
        )
        files = cursor.fetchall()

        cursor.close()
        conn.close()

    if not folder:
        flash("Folder not found", "error")
        return redirect(url_for("file_manager_root"))

    return render_template("file_manager.html", folders=folders, current_folder=folder, files=files)


@app.route("/file-manager/folders/create", methods=["POST"])
@login_required
def file_manager_create_folder():
    name = request.form.get("name")
    parent_id = request.form.get("parent_id") or None

    if not name:
        flash("Folder name is required", "error")
        return redirect(request.referrer or url_for("file_manager_root"))

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO file_folders (name, parent_id) VALUES (%s, %s)",
            (name, parent_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("Folder created", "success")

    if parent_id:
        return redirect(url_for("file_manager_folder", folder_id=parent_id))
    return redirect(url_for("file_manager_root"))


@app.route("/file-manager/folder/<int:folder_id>/upload", methods=["POST"])
@login_required
def file_manager_upload(folder_id):
    title = request.form.get("title")
    file = request.files.get("file")

    if not title or not file:
        flash("Title and file are required", "error")
        return redirect(url_for("file_manager_folder", folder_id=folder_id))

    from werkzeug.utils import secure_filename

    filename = secure_filename(file.filename)
    if not filename:
        flash("Invalid file name", "error")
        return redirect(url_for("file_manager_folder", folder_id=folder_id))

    folder_dir = os.path.join(UPLOAD_ROOT, str(folder_id))
    os.makedirs(folder_dir, exist_ok=True)
    stored_path = os.path.join(str(folder_id), filename)
    save_path = os.path.join(UPLOAD_ROOT, stored_path)
    file.save(save_path)

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO folder_files (folder_id, title, filename, stored_path) VALUES (%s, %s, %s, %s)",
            (folder_id, title, filename, stored_path),
        )
        conn.commit()
        cursor.close()
        conn.close()
        flash("File uploaded", "success")

    return redirect(url_for("file_manager_folder", folder_id=folder_id))


@app.route("/file-manager/files/<int:file_id>/download")
@login_required
def file_manager_download(file_id):
    conn = get_db_connection()
    file_rec = None
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, title, filename, stored_path FROM folder_files WHERE id = %s",
            (file_id,),
        )
        file_rec = cursor.fetchone()
        cursor.close()
        conn.close()

    if not file_rec:
        flash("File not found", "error")
        return redirect(url_for("file_manager_root"))

    stored_path = file_rec["stored_path"]
    directory = UPLOAD_ROOT
    return send_from_directory(directory, stored_path, as_attachment=True, download_name=file_rec["filename"])


if __name__ == "__main__":
    app.run(debug=True)

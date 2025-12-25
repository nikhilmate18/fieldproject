# Simple Flask Document Management System

Very basic example using Flask + MySQL with plain HTML/CSS/JS.

## Setup

1. Create and populate the database in MySQL:

```sql
SOURCE schema.sql;
```

Or run the contents of `schema.sql` manually.

2. Create a virtual environment (optional but recommended) and install requirements:

```bash
pip install -r requirements.txt
```

3. Update `config.py` with your MySQL username/password if needed.

4. Run the Flask app:

```bash
set FLASK_APP=app.py   # on Windows (PowerShell: $env:FLASK_APP = "app.py")
flask run
```

5. Open in browser:

- Home: http://127.0.0.1:5000/
- Documents: http://127.0.0.1:5000/documents
- Categories: http://127.0.0.1:5000/categories

You now have basic CRUD for:

- Categories (add/edit/delete)
- Documents (add/edit/delete, linked to categories)

You can add more modules (e.g., users, departments, clients) by copying the same pattern: table in `schema.sql`, routes in `app.py`, and templates in `templates/`.

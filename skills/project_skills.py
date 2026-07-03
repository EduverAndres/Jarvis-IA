import os
from skills.file_skills import create_folder, create_file


# ── Python básico ─────────────────────────────────────────────────────────

def create_python_project(path: str, name: str) -> str:
    create_folder(path)
    create_folder(os.path.join(path, "src"))
    create_folder(os.path.join(path, "tests"))

    create_file(os.path.join(path, "main.py"),
        f'# {name}\n\ndef main():\n    print("Hola desde {name}")\n\n'
        'if __name__ == "__main__":\n    main()\n')

    create_file(os.path.join(path, "requirements.txt"), "")
    create_file(os.path.join(path, "README.md"),
        f"# {name}\n\nProyecto Python generado por JARVIS.\n")
    create_file(os.path.join(path, ".gitignore"),
        "__pycache__/\n*.pyc\n.env\nvenv/\ndist/\nbuild/\n")

    return f"Proyecto Python '{name}' listo en {path}"


# ── CRUD Flask + SQLite ───────────────────────────────────────────────────

def create_crud_project(path: str, name: str) -> str:
    create_folder(path)
    create_folder(os.path.join(path, "templates"))
    create_folder(os.path.join(path, "static", "css"))

    # ── app.py ──
    create_file(os.path.join(path, "app.py"), f'''\
from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app       = Flask(__name__)
DB        = "database.db"
APP_TITLE = "{name}"


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT NOT NULL,
                descripcion TEXT,
                creado      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


@app.route("/")
def index():
    rows = get_db().execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    return render_template("index.html", items=rows, title=APP_TITLE)


@app.route("/crear", methods=["GET", "POST"])
def crear():
    if request.method == "POST":
        with get_db() as db:
            db.execute("INSERT INTO items (nombre, descripcion) VALUES (?, ?)",
                       (request.form["nombre"], request.form.get("descripcion", "")))
        return redirect(url_for("index"))
    return render_template("form.html", item=None, accion="Crear")


@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar(id):
    db   = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (id,)).fetchone()
    if request.method == "POST":
        with get_db() as db:
            db.execute("UPDATE items SET nombre=?, descripcion=? WHERE id=?",
                       (request.form["nombre"], request.form.get("descripcion", ""), id))
        return redirect(url_for("index"))
    return render_template("form.html", item=item, accion="Editar")


@app.route("/eliminar/<int:id>")
def eliminar(id):
    with get_db() as db:
        db.execute("DELETE FROM items WHERE id=?", (id,))
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    print("Servidor en http://localhost:5000")
    app.run(debug=True)
''')

    # ── index.html ──
    create_file(os.path.join(path, "templates", "index.html"), f'''\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{{{{ title }}}}</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="container">
  <header>
    <h1>{{{{ title }}}}</h1>
    <a href="/crear" class="btn btn-primary">+ Nuevo</a>
  </header>
  <table>
    <thead><tr><th>#</th><th>Nombre</th><th>Descripción</th><th>Acciones</th></tr></thead>
    <tbody>
    {{% for item in items %}}
    <tr>
      <td>{{{{ item.id }}}}</td>
      <td>{{{{ item.nombre }}}}</td>
      <td>{{{{ item.descripcion }}}}</td>
      <td>
        <a href="/editar/{{{{ item.id }}}}" class="btn btn-edit">Editar</a>
        <a href="/eliminar/{{{{ item.id }}}}" class="btn btn-del"
           onclick="return confirm('¿Eliminar este elemento?')">Eliminar</a>
      </td>
    </tr>
    {{% endfor %}}
    </tbody>
  </table>
</div>
</body>
</html>
''')

    # ── form.html ──
    create_file(os.path.join(path, "templates", "form.html"), '''\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{{ accion }}</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="container">
  <h1>{{ accion }} elemento</h1>
  <form method="POST" class="form-card">
    <label>Nombre</label>
    <input type="text" name="nombre"
           value="{{ item.nombre if item else \'\' }}" required>
    <label>Descripción</label>
    <textarea name="descripcion">{{ item.descripcion if item else \'\' }}</textarea>
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ accion }}</button>
      <a href="/" class="btn btn-cancel">Cancelar</a>
    </div>
  </form>
</div>
</body>
</html>
''')

    # ── style.css ──
    create_file(os.path.join(path, "static", "css", "style.css"), '''\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f0f2f5; color: #1a1a2e; min-height: 100vh; }
.container { max-width: 960px; margin: 0 auto; padding: 32px 20px; }
header { display: flex; align-items: center; justify-content: space-between;
         margin-bottom: 28px; }
h1 { font-size: 1.6rem; font-weight: 700; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border-radius: 12px; overflow: hidden;
        box-shadow: 0 2px 12px rgba(0,0,0,.06); }
th, td { padding: 14px 18px; border-bottom: 1px solid #f0f0f0; text-align: left; }
th { background: #1a1a2e; color: #fff; font-weight: 600; font-size: .85rem;
     text-transform: uppercase; letter-spacing: .05em; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f9fbff; }
.btn { display: inline-block; padding: 8px 18px; border-radius: 8px;
       font-size: .875rem; font-weight: 600; text-decoration: none;
       cursor: pointer; border: none; transition: opacity .15s; }
.btn:hover { opacity: .82; }
.btn-primary { background: #1a1a2e; color: #fff; }
.btn-edit    { color: #2563eb; }
.btn-del     { color: #dc2626; margin-left: 8px; }
.btn-cancel  { color: #6b7280; margin-left: 12px; }
.form-card { background: #fff; border-radius: 12px; padding: 28px;
             box-shadow: 0 2px 12px rgba(0,0,0,.06); max-width: 520px; }
label { display: block; font-size: .85rem; font-weight: 600;
        color: #374151; margin-bottom: 6px; margin-top: 18px; }
input, textarea { width: 100%; padding: 10px 14px; border: 1.5px solid #e5e7eb;
                  border-radius: 8px; font-size: .95rem; font-family: inherit;
                  transition: border-color .15s; }
input:focus, textarea:focus { outline: none; border-color: #1a1a2e; }
textarea { height: 110px; resize: vertical; }
.form-actions { margin-top: 24px; display: flex; align-items: center; }
''')

    create_file(os.path.join(path, "requirements.txt"), "flask\n")
    create_file(os.path.join(path, "README.md"),
        f"# {name}\n\nCRUD generado por JARVIS.\n\n"
        "## Ejecutar\n```bash\npip install flask\npython app.py\n```\n"
        "Abre http://localhost:5000\n")

    return (f"✅ CRUD '{name}' creado en {path}\n"
            f"Ejecuta: cd \"{path}\" && pip install flask && python app.py")


# ── Web estático ──────────────────────────────────────────────────────────

def create_web_project(path: str, name: str) -> str:
    create_folder(path)
    create_folder(os.path.join(path, "css"))
    create_folder(os.path.join(path, "js"))
    create_folder(os.path.join(path, "img"))

    create_file(os.path.join(path, "index.html"), f'''\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <h1>{name}</h1>
  <script src="js/main.js"></script>
</body>
</html>
''')
    create_file(os.path.join(path, "css", "style.css"),
        "*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "body { font-family: system-ui, sans-serif; padding: 40px; }\n")
    create_file(os.path.join(path, "js", "main.js"),
        f"// {name}\nconsole.log('JARVIS: {name} cargado');\n")

    return f"✅ Proyecto web '{name}' listo en {path}"

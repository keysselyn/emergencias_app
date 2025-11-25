"""
bootstrap.py

Bootstrap + esquema "suave" para MySQL/Railway:
- Crea tablas que no existen (db.create_all()).
- Agrega columnas faltantes a tablas existentes (ALTER TABLE ADD COLUMN).
- NO modifica tipos ni elimina columnas.

Activa con BOOTSTRAP_ON_START=1
Opcional: /admin/bootstrap?token=SETUP_TOKEN
"""

import os
from datetime import datetime
from sqlalchemy import inspect, text

# OJO: NO importes Flask current_app aquí para evitar errores en import.
from models import db, User, Hospital, EmergencyRecord, GuardiaEmergencia, Internamiento

# ----------------------------
# Seed de hospitales base
# ----------------------------
HOSPITALES_BASE = [
    "Hospital Regional Juan Pablo Pina",
    "Hospital Provincial Dr. Rafael j Mañón",
    "Hospital Provincial Nuestra señora de regla",
    "Hospital Municpal Villa Fundacion",
    "Hospital Municipal Barsequillo",
    "Hospital Municipal Maria Paniagua",
    "Hospital Municipal Tomasina Valdez",
    "Hospital Municipal Nizao",
    "Hospital  Municipal Cambita pueblo",
    "Hospital Municipal Cambita Garabitos",
    "Hospital Municipal de Yaguate",
    "Hospital Municipal Villa Altagracia",
    "Hospital Nustra Señora de Altagracia",
    "Hospital Municipal Dr.Guarionex ALcantara",
    "Hospital Provincial San José de Ocoa",
    "Hospital Municipal los Cacaos",
]

def _seed_hospitals():
    creados = 0
    for nombre in HOSPITALES_BASE:
        if not Hospital.query.filter_by(nombre=nombre).first():
            db.session.add(Hospital(nombre=nombre, activo=True))
            creados += 1
    db.session.commit()
    print(f"[BOOTSTRAP] Hospitales OK (nuevos: {creados})")


# ---------------------------------------------------
# Helpers para ALTER TABLE ADD COLUMN según SQLAlchemy
# ---------------------------------------------------
def _mysql_type_for_column(col):
    """Devuelve tipo MySQL aproximado basado en SQLAlchemy column.type."""
    t = col.type

    # Integer / Boolean
    if t.__class__.__name__.lower() in ("integer", "biginteger", "smallinteger"):
        return "INT"
    if t.__class__.__name__.lower() in ("boolean",):
        return "TINYINT(1)"

    # Date / DateTime
    if t.__class__.__name__.lower() == "date":
        return "DATE"
    if t.__class__.__name__.lower() in ("datetime", "timestamp"):
        return "DATETIME"

    # Text
    if t.__class__.__name__.lower() in ("text", "unicodeText".lower()):
        return "TEXT"

    # String(VARCHAR)
    if t.__class__.__name__.lower() in ("string", "unicode", "varchar"):
        length = getattr(t, "length", None) or 255
        return f"VARCHAR({length})"

    # Fallback
    return "VARCHAR(255)"


def _default_sql(col):
    if col.default is None:
        return ""
    # default puede ser callable o scalar
    if hasattr(col.default, "arg"):
        val = col.default.arg
    else:
        val = col.default
    # boolean
    if isinstance(val, bool):
        return f" DEFAULT {1 if val else 0}"
    # números
    if isinstance(val, (int, float)):
        return f" DEFAULT {val}"
    # strings
    if isinstance(val, str):
        return f" DEFAULT '{val}'"
    return ""


def _nullable_sql(col):
    return " NOT NULL" if not col.nullable else ""


def _add_column_ddl(table_name, col):
    col_name = col.name
    col_type = _mysql_type_for_column(col)
    nullable_sql = _nullable_sql(col)
    default_sql = _default_sql(col)

    return f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type}{nullable_sql}{default_sql};"


def ensure_schema():
    """
    Agrega columnas faltantes a tablas existentes según metadata de modelos.
    """
    insp = inspect(db.engine)

    # Recorrer todas las tablas definidas en metadata
    for table_name, table in db.metadata.tables.items():
        if not insp.has_table(table_name):
            continue  # si no existe, create_all() la crea

        existing_cols = {c["name"] for c in insp.get_columns(table_name)}

        for col in table.columns:
            if col.name in existing_cols:
                continue

            ddl = _add_column_ddl(table_name, col)
            print(f"[BOOTSTRAP] {ddl}")

            try:
                db.session.execute(text(ddl))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[BOOTSTRAP] Error añadiendo columna {col.name} en {table_name}: {e}")


def bootstrap_if_empty():
    """
    1) Crea tablas que falten
    2) Agrega columnas faltantes
    3) Seed de hospitales + admin si DB vacía
    """
    db.create_all()
    ensure_schema()

    total_users = User.query.count()
    print(f"[BOOTSTRAP] Usuarios existentes: {total_users}")

    if total_users == 0:
        _seed_hospitals()

        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_pass = os.getenv("ADMIN_PASS", "Admin123*")
        admin_hosp = os.getenv("ADMIN_HOSPITAL", "Hospital Municipal los Cacaos")

        ok = Hospital.query.filter_by(nombre=admin_hosp, activo=True).first()
        if not ok:
            any_h = Hospital.query.filter_by(activo=True).first()
            admin_hosp = any_h.nombre if any_h else admin_hosp

        u = User(
            username=admin_user,
            hospital=admin_hosp,
            is_admin=True,
            is_hospital_admin=True,
        )
        u.set_password(admin_pass)
        db.session.add(u)
        db.session.commit()
        print(f"[BOOTSTRAP] Admin creado: {admin_user} / hospital={admin_hosp}")
    else:
        print("[BOOTSTRAP] Ya hay usuarios. No se crea admin nuevo.")


def run_bootstrap_on_start(app):
    """
    Llamar desde app.py DESPUÉS de db.init_app(app):
        from bootstrap import run_bootstrap_on_start
        run_bootstrap_on_start(app)
    """
    if os.getenv("BOOTSTRAP_ON_START", "0") != "1":
        return

    try:
        with app.app_context():
            bootstrap_if_empty()
    except Exception as e:
        print(f"[BOOTSTRAP] Error general: {e}")

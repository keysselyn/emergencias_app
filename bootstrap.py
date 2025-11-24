"""
bootstrap.py
Ejecuta creación inicial de tablas y migraciones ligeras (ALTER) al iniciar Railway.
Úsalo con: BOOTSTRAP_ON_START=python3 bootstrap.py

- Crea tablas faltantes via db.create_all()
- Agrega columnas/índices faltantes de forma idempotente (no falla si ya existen)
Compatible con PostgreSQL y MySQL/MariaDB.
"""

import sys
from sqlalchemy import inspect, text

# Importa tu app y db ya configuradas
from app import app, db
import models  # asegura que los modelos estén cargados


def log(msg):
    print(f"[BOOTSTRAP] {msg}")


def qi(dialect: str, name: str) -> str:
    """
    Quote Identifiers para evitar choques con reservadas
    y respetar case/char especiales.
    """
    if dialect.startswith("postgres"):
        return f'"{name}"'
    # mysql / mariadb
    return f"`{name}`"


def has_table(inspector, table_name):
    return table_name in inspector.get_table_names()


def has_column(inspector, table_name, col_name):
    cols = [c["name"] for c in inspector.get_columns(table_name)]
    return col_name in cols


def add_column(conn, dialect, table, col, coltype_sql, default_sql=None, nullable=True):
    """
    Agrega columna solo si no existe.
    coltype_sql debe ser string SQL apropiado al dialecto.
    """
    insp = inspect(conn)
    if has_column(insp, table, col):
        log(f"Columna ya existe: {table}.{col}")
        return

    null_sql = "NULL" if nullable else "NOT NULL"
    default_part = f" DEFAULT {default_sql}" if default_sql is not None else ""

    t = qi(dialect, table)
    c = qi(dialect, col)

    sql = f"ALTER TABLE {t} ADD COLUMN {c} {coltype_sql} {null_sql}{default_part};"
    log(f"Ejecutando: {sql}")
    conn.execute(text(sql))


def alter_column_type(conn, dialect, table, col, newtype_sql, using_sql=None):
    """
    Cambia tipo de columna si existe.
    En Postgres puedes pasar using_sql para casting seguro.
    """
    insp = inspect(conn)
    if not has_column(insp, table, col):
        log(f"No se altera tipo porque columna no existe: {table}.{col}")
        return

    t = qi(dialect, table)
    c = qi(dialect, col)

    if dialect.startswith("postgres"):
        using_part = f" USING {using_sql}" if using_sql else ""
        sql = f"ALTER TABLE {t} ALTER COLUMN {c} TYPE {newtype_sql}{using_part};"
    else:
        # mysql / mariadb
        sql = f"ALTER TABLE {t} MODIFY COLUMN {c} {newtype_sql};"

    log(f"Ejecutando: {sql}")
    conn.execute(text(sql))


def add_index(conn, dialect, table, index_name, cols):
    insp = inspect(conn)
    existing = {ix["name"] for ix in insp.get_indexes(table)}
    if index_name in existing:
        log(f"Índice ya existe: {index_name}")
        return

    t = qi(dialect, table)
    cols_sql = ", ".join(qi(dialect, c) for c in cols)
    ix = qi(dialect, index_name)

    sql = f"CREATE INDEX {ix} ON {t} ({cols_sql});"
    log(f"Ejecutando: {sql}")
    conn.execute(text(sql))


def ensure_schema():
    with app.app_context():
        log("Iniciando bootstrap de DB...")

        # 1) Crear tablas que no existan
        try:
            db.create_all()
            log("db.create_all() completado.")
        except Exception as e:
            log(f"create_all falló (se continúa): {type(e).__name__}: {e}")

        engine = db.engine
        dialect = engine.dialect.name
        log(f"Dialect detectado: {dialect}")

        with engine.begin() as conn:
            insp = inspect(conn)

            # ------------------------------
            # INTERNAMIENTOS
            # ------------------------------
            if has_table(insp, "internamientos"):

                # fecha_actualizacion
                add_column(
                    conn, dialect, "internamientos", "fecha_actualizacion",
                    "DATETIME" if not dialect.startswith("postgres") else "TIMESTAMP"
                )

                # egresado boolean
                if dialect.startswith("postgres"):
                    add_column(
                        conn, dialect, "internamientos", "egresado",
                        "BOOLEAN", default_sql="FALSE", nullable=False
                    )
                else:
                    add_column(
                        conn, dialect, "internamientos", "egresado",
                        "TINYINT(1)", default_sql="0", nullable=False
                    )

                # dia_ingreso int (si venía como date/text en versiones viejas)
                # - Postgres: intenta cast seguro si no es int aún.
                if dialect.startswith("postgres"):
                    alter_column_type(
                        conn, dialect, "internamientos", "dia_ingreso", "INTEGER",
                        using_sql="NULLIF(dia_ingreso::text,'')::integer"
                    )
                else:
                    alter_column_type(
                        conn, dialect, "internamientos", "dia_ingreso", "INT"
                    )

                # índice fecha+hospital (si no existe)
                try:
                    add_index(
                        conn, dialect, "internamientos",
                        "ix_internamiento_fecha_hospital",
                        ["fecha", "hospital"]
                    )
                except Exception as e:
                    log(f"No se pudo crear índice ix_internamiento_fecha_hospital: {type(e).__name__}: {e}")

                # backfill fecha_actualizacion para viejos
                try:
                    insp2 = inspect(conn)
                    if has_column(insp2, "internamientos", "fecha_actualizacion"):
                        if dialect.startswith("postgres"):
                            sql = f"""
                                UPDATE {qi(dialect,'internamientos')}
                                SET {qi(dialect,'fecha_actualizacion')} = {qi(dialect,'fecha')}::timestamp
                                WHERE {qi(dialect,'fecha_actualizacion')} IS NULL;
                            """
                        else:
                            sql = f"""
                                UPDATE {qi(dialect,'internamientos')}
                                SET {qi(dialect,'fecha_actualizacion')} = CONCAT({qi(dialect,'fecha')}, ' 00:00:00')
                                WHERE {qi(dialect,'fecha_actualizacion')} IS NULL;
                            """
                        log("Backfill fecha_actualizacion (solo NULLs).")
                        conn.execute(text(sql))
                except Exception as e:
                    log(f"Backfill fecha_actualizacion falló: {type(e).__name__}: {e}")

            else:
                log("Tabla internamientos no existe; create_all debió crearla.")

            # ------------------------------
            # GUARDIAS_EMERGENCIA
            # ------------------------------
            if has_table(insp, "guardias_emergencia"):
                try:
                    add_index(
                        conn, dialect, "guardias_emergencia",
                        "ix_guardia_fecha_hospital",
                        ["fecha", "hospital"]
                    )
                except Exception as e:
                    log(f"No se pudo crear índice guardias_emergencia: {type(e).__name__}: {e}")

            # ------------------------------
            # EMERGENCY_RECORDS
            # ------------------------------
            if has_table(insp, "emergency_records"):
                try:
                    add_index(
                        conn, dialect, "emergency_records",
                        "ix_emergency_fecha_hospital",
                        ["fecha", "hospital"]
                    )
                except Exception as e:
                    log(f"No se pudo crear índice emergency_records: {type(e).__name__}: {e}")

            # ------------------------------
            # HOSPITALS: logo_filename
            # ------------------------------
            if has_table(insp, "hospitals"):
                add_column(
                    conn, dialect, "hospitals", "logo_filename",
                    "VARCHAR(255)"
                )

        log("Bootstrap finalizado sin errores fatales.")


if __name__ == "__main__":
    try:
        ensure_schema()
    except Exception as e:
        log(f"Bootstrap terminó con error: {type(e).__name__}: {e}")
        # no abortar el deploy: salimos 0
        sys.exit(0)

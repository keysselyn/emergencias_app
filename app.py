# app.py (LIMPIO Y FUNCIONAL)

from flask import (
    Flask, render_template, request, redirect, url_for, flash, Response,
    send_from_directory, abort, jsonify, make_response, current_app
)
from flask_login import (
    LoginManager, login_user, logout_user, current_user, login_required
)
from datetime import datetime, date, timedelta
from io import StringIO, BytesIO
from functools import wraps
import csv, json, os
from dateutil import parser

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from xhtml2pdf import pisa
from werkzeug.utils import secure_filename

from models import db, User, Hospital, EmergencyRecord, GuardiaEmergencia, Internamiento


# ==============================
# APP CONFIG
# ==============================
app = Flask(__name__)


# ==============================
# LOGOS CONFIG
# ==============================
LOGOS_SUBFOLDER = "img"  # dentro de /static
UPLOAD_FOLDER_LOGOS = os.path.join(app.root_path, "static", LOGOS_SUBFOLDER)
os.makedirs(UPLOAD_FOLDER_LOGOS, exist_ok=True)

ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def allowed_logo_file(filename: str) -> bool:
    if not filename:
        return False
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_LOGO_EXTENSIONS


# ==============================
# DB CONFIG (MySQL / Railway)
# ==============================
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:@127.0.0.1:3306/emergencias?charset=utf8mb4"
)

if not DATABASE_URL:
    rh = os.getenv("MYSQLHOST")
    ru = os.getenv("MYSQLUSER")
    rp = os.getenv("MYSQLPASSWORD")
    rport = os.getenv("MYSQLPORT", "3306")
    rdb = os.getenv("MYSQLDATABASE")
    if rh and ru and rp and rdb:
        DATABASE_URL = f"mysql+pymysql://{ru}:{rp}@{rh}:{rport}/{rdb}?charset=utf8mb4"

if not DATABASE_URL:
    raise RuntimeError(
        "No se ha configurado la base de datos. "
        "Define DATABASE_URL o las variables MYSQLHOST, MYSQLUSER, "
        "MYSQLPASSWORD, MYSQLPORT, MYSQLDATABASE."
    )

if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

if DATABASE_URL.startswith("mysql+pymysql://") and "charset=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}charset=utf8mb4"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia-esta-clave")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db.init_app(app)


# ==============================
# LOGIN MANAGER
# ==============================
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ==============================
# DECORADORES DE PERMISOS
# ==============================
def admin_required(fn):
    """Solo Admin general (is_admin=True)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Solo Administradores generales.", "danger")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper


def hospital_admin_required(fn):
    """
    Permite acceso a:
      - Admin general (is_admin=True)
      - Admin de hospital (is_hospital_admin=True)
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not (current_user.is_admin or current_user.is_hospital_admin):
            flash("Solo administradores (general o de hospital).", "danger")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper


def user_hospital_scope():
    """
    Hospital filtro según rol:
    - Admin general: None (ve todos)
    - Admin hospital/usuario normal: su hospital
    """
    if current_user.is_admin:
        return None
    return current_user.hospital


# ==============================
# CONTEXT PROCESSOR
# ==============================
@app.context_processor
def inject_choices():
    """Hace disponibles los hospitales activos en todas las plantillas."""
    try:
        hospitales = Hospital.query.filter_by(activo=True).order_by(Hospital.nombre.asc()).all()
    except Exception:
        hospitales = []
    return dict(HOSPITALES=hospitales)

# ==============================
# BOOTSTRAP DB (OPCIONAL)
# ==============================
def _seed_hospitals():
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
    creados = 0
    for nombre in HOSPITALES_BASE:
        if not Hospital.query.filter_by(nombre=nombre).first():
            db.session.add(Hospital(nombre=nombre, activo=True))
            creados += 1
    db.session.commit()
    print(f"[BOOTSTRAP] Hospitales OK (nuevos: {creados})")


def bootstrap_if_empty():
    """Crea tablas y un admin si la DB está vacía (BOOTSTRAP_ON_START=1)."""
    with app.app_context():
        db.create_all()
        total = User.query.count()
        print(f"[BOOTSTRAP] Usuarios existentes: {total}")
        if total == 0:
            _seed_hospitals()
            admin_user = os.getenv("ADMIN_USER", "admin")
            admin_pass = os.getenv("ADMIN_PASS", "Admin123*")
            admin_hosp = os.getenv("ADMIN_HOSPITAL", "Hospital Municipal los Cacaos")

            ok = Hospital.query.filter_by(nombre=admin_hosp, activo=True).first()
            if not ok:
                any_h = Hospital.query.filter_by(activo=True).first()
                admin_hosp = any_h.nombre if any_h else "Hospital Municipal los Cacaos"

            u = User(
                username=admin_user,
                hospital=admin_hosp,
                is_admin=True,
                is_hospital_admin=True
            )
            u.set_password(admin_pass)
            db.session.add(u)
            db.session.commit()
            print(f"[BOOTSTRAP] Admin creado: {admin_user} / hospital={admin_hosp}")
        else:
            print("[BOOTSTRAP] Ya hay usuarios. No se crea admin nuevo.")


if os.getenv("BOOTSTRAP_ON_START", "0") == "1":
    try:
        bootstrap_if_empty()
    except Exception as e:
        print(f"[BOOTSTRAP] Error: {e}")


@app.route("/admin/bootstrap")
def admin_bootstrap():
    token = request.args.get("token", "")
    expected = os.getenv("SETUP_TOKEN", "")
    if not expected or token != expected:
        return abort(403)
    try:
        bootstrap_if_empty()
        return "Bootstrap ejecutado", 200
    except Exception as e:
        return f"Error: {e}", 500


# ==============================
# HEALTHCHECK
# ==============================
@app.route("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
        return "OK", 200
    except Exception as e:
        return f"DB ERROR: {e}", 500


# ==============================
# PÁGINAS BASE / LOGIN
# ==============================
@app.route("/")
def index():
    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", hoy=hoy)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Sesión iniciada.", "success")
            return redirect(url_for("dashboard"))
        flash("Credenciales inválidas.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("index"))


# ======================================================================
#   REGISTRO DIARIO DE EMERGENCIAS
# ======================================================================
@app.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            fecha = parser.parse(fecha_str).date() if fecha_str else datetime.today().date()

            if current_user.is_admin:
                hospital_nombre = (request.form.get("hospital") or "").strip()
                ok = Hospital.query.filter_by(nombre=hospital_nombre, activo=True).first()
                if not ok:
                    flash("Hospital inválido o inactivo.", "danger")
                    return render_template("form.html")
                hospital = hospital_nombre
            else:
                hospital = current_user.hospital

            existente = EmergencyRecord.query.filter_by(fecha=fecha, hospital=hospital).first()
            if existente:
                flash(
                    "Ya existe un registro para este hospital en esa fecha. "
                    "Edítalo en lugar de crear uno nuevo.",
                    "danger"
                )
                return redirect(url_for("editar", rec_id=existente.id))

            def to_int(name):
                val = (request.form.get(name) or "0").strip()
                try:
                    return max(int(val), 0)
                except Exception:
                    return 0

            rec = EmergencyRecord(
                fecha=fecha,
                hospital=hospital,
                atenciones=to_int("atenciones"),
                ingresos=to_int("ingresos"),
                alta_voluntario=to_int("alta_voluntario"),
                traslados=to_int("traslados"),
                defunciones=to_int("defunciones"),
                motivo_traslado=(request.form.get("motivo_traslado") or "").strip(),
                hospital_referencia=(request.form.get("hospital_referencia") or "").strip(),
                eventualidades=(request.form.get("eventualidades") or "").strip(),
                created_by_id=current_user.id,
            )
            db.session.add(rec)
            db.session.commit()
            flash("Registro guardado correctamente.", "success")
            return redirect(url_for("listar"))

        except Exception as e:
            flash(f"Error guardando: {e}", "danger")

    return render_template("form.html")


@app.route("/editar/<int:rec_id>", methods=["GET", "POST"])
@login_required
def editar(rec_id):
    rec = EmergencyRecord.query.get_or_404(rec_id)

    if not current_user.is_admin and rec.hospital != current_user.hospital:
        flash("No tiene permiso para editar este registro.", "danger")
        return redirect(url_for("listar"))

    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            nueva_fecha = parser.parse(fecha_str).date() if fecha_str else rec.fecha

            if current_user.is_admin:
                hospital_nombre = (request.form.get("hospital") or rec.hospital).strip()
                ok = Hospital.query.filter_by(nombre=hospital_nombre, activo=True).first()
                if not ok:
                    flash("Hospital inválido o inactivo.", "danger")
                    return render_template("edit.html", rec=rec)
                nuevo_hospital = hospital_nombre
            else:
                nuevo_hospital = current_user.hospital

            duplicado = EmergencyRecord.query.filter(
                EmergencyRecord.id != rec.id,
                EmergencyRecord.fecha == nueva_fecha,
                EmergencyRecord.hospital == nuevo_hospital
            ).first()
            if duplicado:
                flash("Ya existe otro registro para este hospital en esa fecha.", "danger")
                return render_template("edit.html", rec=rec)

            rec.fecha = nueva_fecha
            rec.hospital = nuevo_hospital

            def to_int(name, current):
                val = request.form.get(name, "")
                if val == "":
                    return current
                try:
                    return max(int(val), 0)
                except Exception:
                    return current

            rec.atenciones = to_int("atenciones", rec.atenciones)
            rec.ingresos = to_int("ingresos", rec.ingresos)
            rec.alta_voluntario = to_int("alta_voluntario", rec.alta_voluntario)
            rec.traslados = to_int("traslados", rec.traslados)
            rec.defunciones = to_int("defunciones", rec.defunciones)
            rec.motivo_traslado = (request.form.get("motivo_traslado") or "").strip()
            rec.hospital_referencia = (request.form.get("hospital_referencia") or "").strip()
            rec.eventualidades = (request.form.get("eventualidades") or "").strip()

            db.session.commit()
            flash("Registro actualizado correctamente.", "success")
            return redirect(url_for("listar"))

        except Exception as e:
            flash(f"Error actualizando: {e}", "danger")

    return render_template("edit.html", rec=rec)


@app.route("/eliminar/<int:rec_id>", methods=["POST"])
@login_required
@admin_required
def eliminar(rec_id):
    rec = EmergencyRecord.query.get_or_404(rec_id)
    db.session.delete(rec)
    db.session.commit()
    flash("Registro eliminado correctamente.", "success")
    return redirect(url_for("listar"))


@app.route("/listar")
@login_required
def listar():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde")
    f_hasta = request.args.get("hasta")

    q = EmergencyRecord.query

    if not current_user.is_admin:
        q = q.filter(EmergencyRecord.hospital == current_user.hospital)
    else:
        if f_hospital:
            q = q.filter(EmergencyRecord.hospital == f_hospital)

    def parse_date(s):
        try:
            return parser.parse(s).date()
        except Exception:
            return None

    d_desde = parse_date(f_desde) if f_desde else None
    d_hasta = parse_date(f_hasta) if f_hasta else None

    if d_desde:
        q = q.filter(EmergencyRecord.fecha >= d_desde)
    if d_hasta:
        q = q.filter(EmergencyRecord.fecha <= d_hasta)

    registros = q.order_by(EmergencyRecord.fecha.desc(), EmergencyRecord.id.desc()).all()
    return render_template("list.html", registros=registros)


# ================== EXPORTAR CSV ==================
@app.route("/exportar_csv")
@login_required
def exportar_csv():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde")
    f_hasta = request.args.get("hasta")

    q = EmergencyRecord.query

    if not current_user.is_admin:
        q = q.filter(EmergencyRecord.hospital == current_user.hospital)
    else:
        if f_hospital:
            q = q.filter(EmergencyRecord.hospital == f_hospital)

    def parse_date(s):
        try:
            return parser.parse(s).date()
        except Exception:
            return None

    d_desde = parse_date(f_desde) if f_desde else None
    d_hasta = parse_date(f_hasta) if f_hasta else None

    if d_desde:
        q = q.filter(EmergencyRecord.fecha >= d_desde)
    if d_hasta:
        q = q.filter(EmergencyRecord.fecha <= d_hasta)

    registros = q.order_by(EmergencyRecord.fecha.desc(), EmergencyRecord.id.desc()).all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow([
        "Fecha", "Hospital", "Atenciones", "Ingresos", "Alta Voluntario",
        "Traslados", "Motivo del traslado", "Hospital de referencia",
        "Defunciones", "Eventualidades"
    ])
    for r in registros:
        writer.writerow(r.to_row())

    output = si.getvalue().encode("utf-8-sig")
    return Response(
        output,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=registros_emergencias.csv"}
    )


# ================== EXPORTAR EXCEL ==================
@app.route("/exportar_excel")
@login_required
def exportar_excel():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde") or ""
    f_hasta = request.args.get("hasta") or ""

    def parse_date(s):
        try:
            return parser.parse(s).date() if s else None
        except Exception:
            return None

    d_desde = parse_date(f_desde)
    d_hasta = parse_date(f_hasta)

    if d_desde and d_hasta and d_desde > d_hasta:
        d_desde, d_hasta = d_hasta, d_desde
        f_desde, f_hasta = (
            d_desde.isoformat() if d_desde else "",
            d_hasta.isoformat() if d_hasta else ""
        )

    q = EmergencyRecord.query
    motivo_vacio = []

    if not current_user.is_admin:
        q = q.filter(EmergencyRecord.hospital == current_user.hospital)
        motivo_vacio.append(f"Rol usuario restringe a hospital '{current_user.hospital}'")
    else:
        if f_hospital:
            q = q.filter(EmergencyRecord.hospital == f_hospital)
            motivo_vacio.append(f"Filtro hospital '{f_hospital}'")

    if d_desde:
        q = q.filter(EmergencyRecord.fecha >= d_desde)
        motivo_vacio.append(f"Desde {d_desde.isoformat()}")
    if d_hasta:
        q = q.filter(EmergencyRecord.fecha <= d_hasta)
        motivo_vacio.append(f"Hasta {d_hasta.isoformat()}")

    registros = q.order_by(EmergencyRecord.fecha.asc(), EmergencyRecord.id.asc()).all()

    reintento_sin_fechas = False
    if len(registros) == 0 and (d_desde or d_hasta):
        q2 = EmergencyRecord.query
        if not current_user.is_admin:
            q2 = q2.filter(EmergencyRecord.hospital == current_user.hospital)
        else:
            if f_hospital:
                q2 = q2.filter(EmergencyRecord.hospital == f_hospital)

        registros = q2.order_by(EmergencyRecord.fecha.asc(), EmergencyRecord.id.asc()).all()
        reintento_sin_fechas = True

    wb = Workbook()
    ws = wb.active
    ws.title = "Registros"

    headers = [
        "Fecha", "Hospital", "Atenciones", "Ingresos", "Alta Voluntario",
        "Traslados", "Motivo del traslado", "Hospital de referencia",
        "Defunciones", "Eventualidades"
    ]
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="0D6EFD")
    header_font = Font(color="FFFFFF", bold=True)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin = Side(border_style="thin", color="D0D7E2")
    border_all = Border(top=thin, left=thin, right=thin, bottom=thin)

    number_right = NamedStyle(name="number_right")
    number_right.number_format = "#,##0"
    number_right.alignment = Alignment(horizontal="right", vertical="center")

    date_center = NamedStyle(name="date_center")
    date_center.number_format = "yyyy-mm-dd"
    date_center.alignment = Alignment(horizontal="center", vertical="center")

    text_wrap = NamedStyle(name="text_wrap")
    text_wrap.alignment = Alignment(wrap_text=True, vertical="top")

    for st in (number_right, date_center, text_wrap):
        try:
            wb.add_named_style(st)
        except Exception:
            pass

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = border_all

    row_start = 2
    for r in registros:
        ws.append([
            r.fecha,
            r.hospital,
            r.atenciones,
            r.ingresos,
            r.alta_voluntario,
            r.traslados,
            r.motivo_traslado or "",
            r.hospital_referencia or "",
            r.defunciones,
            (r.eventualidades or "").replace("\r", " ")
        ])

    COL_FECHA = 1
    COL_NUMS = [3, 4, 5, 6, 9]
    COL_TEXT_WRAP = [7, 8, 10]
    last_row = ws.max_row

    if last_row > 1:
        for row in range(row_start, last_row + 1):
            ws.cell(row=row, column=COL_FECHA).style = "date_center"
            for c in COL_NUMS:
                ws.cell(row=row, column=c).style = "number_right"
            for c in COL_TEXT_WRAP:
                ws.cell(row=row, column=c).style = "text_wrap"
            for c in range(1, len(headers) + 1):
                ws.cell(row=row, column=c).border = border_all

        total_row = last_row + 1
        ws.cell(row=total_row, column=1, value="Totales")
        ws.cell(row=total_row, column=1).font = Font(bold=True)
        ws.cell(row=total_row, column=1).alignment = Alignment(horizontal="right")

        for c in COL_NUMS:
            col_letter = get_column_letter(c)
            ws.cell(
                row=total_row, column=c,
                value=f"=SUM({col_letter}{row_start}:{col_letter}{last_row})"
            ).style = "number_right"

        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=total_row, column=c)
            cell.border = border_all
            if c in COL_NUMS or c == 1:
                cell.fill = PatternFill("solid", fgColor="E9F2FF")

        last_row = total_row

    widths = {1: 12, 2: 38, 3: 12, 4: 12, 5: 16, 6: 12, 7: 28, 8: 28, 9: 12, 10: 50}
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"

    summary = wb.create_sheet("Resumen", 0)
    summary["A1"] = "Exportación de Registros de Emergencias"
    summary["A1"].font = Font(size=14, bold=True)

    summary["A3"] = "Generado:"
    summary["B3"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary["A4"] = "Hospital:"
    summary["B4"] = (
        f_hospital if (current_user.is_admin and f_hospital)
        else (current_user.hospital if not current_user.is_admin else "Todos")
    )
    summary["A5"] = "Desde:"
    summary["B5"] = f_desde or ""
    summary["A6"] = "Hasta:"
    summary["B6"] = f_hasta or ""
    summary["A7"] = "Registros exportados:"
    summary["B7"] = len(registros)

    summary["A9"] = "Notas:"
    notes = []
    if reintento_sin_fechas:
        notes.append("Sin resultados con fechas; se exportó sin filtros de fecha.")
    if motivo_vacio:
        notes.append("Filtros aplicados: " + "; ".join(motivo_vacio))
    summary["B9"] = "\n".join(notes) if notes else "—"

    summary.column_dimensions["A"].width = 20
    summary.column_dimensions["B"].width = 60
    for r in range(1, 11):
        for c in range(1, 3):
            summary.cell(row=r, column=c).alignment = Alignment(vertical="top")

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    filename = "registros_emergencias.xlsx"
    return Response(
        bio.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ======================================================================
#   PDF HELPERS
# ======================================================================
def link_callback(uri, rel):
    """Resuelve rutas static para xhtml2pdf."""
    if uri.startswith("/static/"):
        uri = uri.lstrip("/")

    if uri.startswith("static/"):
        path = os.path.join(current_app.root_path, uri.replace("/", os.sep))
        if os.path.isfile(path):
            return path

    return uri


def render_pdf_from_html(html: str, pdf_filename: str = "reporte.pdf"):
    """Convierte HTML a PDF usando xhtml2pdf."""
    result = BytesIO()
    pisa_status = pisa.CreatePDF(
        src=html.encode("utf-8"),
        dest=result,
        encoding="utf-8",
        link_callback=link_callback,
    )

    if pisa_status.err:
        print("Errores xhtml2pdf:", pisa_status.err)
        return Response("Error generando PDF.", mimetype="text/plain")

    result.seek(0)
    response = make_response(result.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'inline; filename="{pdf_filename}"'
    return response


# ======================================================================
#   DASHBOARD
# ======================================================================
@app.route("/dashboard")
@login_required
def dashboard():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde")
    f_hasta = request.args.get("hasta")

    q = EmergencyRecord.query
    if not current_user.is_admin:
        q = q.filter(EmergencyRecord.hospital == current_user.hospital)
        sel_hospital = current_user.hospital
    else:
        if f_hospital:
            q = q.filter(EmergencyRecord.hospital == f_hospital)
        sel_hospital = f_hospital or "Todos"

    def parse_date(s):
        try:
            return parser.parse(s).date()
        except Exception:
            return None

    d_desde = parse_date(f_desde) if f_desde else None
    d_hasta = parse_date(f_hasta) if f_hasta else None
    if d_desde:
        q = q.filter(EmergencyRecord.fecha >= d_desde)
    if d_hasta:
        q = q.filter(EmergencyRecord.fecha <= d_hasta)

    registros = q.order_by(EmergencyRecord.fecha.asc()).all()

    kpi_atenciones = sum(r.atenciones for r in registros)
    kpi_ingresos = sum(r.ingresos for r in registros)
    kpi_traslados = sum(r.traslados for r in registros)
    kpi_defunciones = sum(r.defunciones for r in registros)

    series = {}
    for r in registros:
        key = r.fecha.isoformat()
        series.setdefault(key, {"atenciones": 0, "ingresos": 0, "traslados": 0, "defunciones": 0})
        series[key]["atenciones"] += r.atenciones
        series[key]["ingresos"] += r.ingresos
        series[key]["traslados"] += r.traslados
        series[key]["defunciones"] += r.defunciones

    dates = sorted(series.keys())
    chart_atenciones = [series[d]["atenciones"] for d in dates]
    chart_ingresos = [series[d]["ingresos"] for d in dates]
    chart_traslados = [series[d]["traslados"] for d in dates]
    chart_defunciones = [series[d]["defunciones"] for d in dates]

    ranking = []
    if current_user.is_admin and not f_hospital:
        totales = {}
        for r in registros:
            totales.setdefault(r.hospital, 0)
            totales[r.hospital] += r.atenciones
        ranking = sorted(
            ({"hospital": h, "atenciones": totales[h]} for h in totales),
            key=lambda x: x["atenciones"],
            reverse=True
        )[:5]

    return render_template(
        "dashboard.html",
        sel_hospital=sel_hospital,
        f_hospital=f_hospital,
        f_desde=f_desde or "",
        f_hasta=f_hasta or "",
        kpi_atenciones=kpi_atenciones,
        kpi_ingresos=kpi_ingresos,
        kpi_traslados=kpi_traslados,
        kpi_defunciones=kpi_defunciones,
        labels=json.dumps(dates),
        data_atenciones=json.dumps(chart_atenciones),
        data_ingresos=json.dumps(chart_ingresos),
        data_traslados=json.dumps(chart_traslados),
        data_defunciones=json.dumps(chart_defunciones),
        ranking=ranking
    )


# ======================================================================
#   CRUD HOSPITALES (ADMIN GENERAL)
# ======================================================================
@app.route("/hospitales")
@login_required
@admin_required
def hospitales_list():
    hospitales = Hospital.query.order_by(Hospital.activo.desc(), Hospital.nombre.asc()).all()
    return render_template("hosp_list.html", hospitales=hospitales)


@app.route("/hospitales/nuevo", methods=["GET", "POST"])
@login_required
@admin_required
def hospitales_nuevo():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        logo_file = request.files.get("logo_file")

        if not nombre:
            flash("El nombre es obligatorio.", "danger")
            return render_template("hosp_form.html")

        if Hospital.query.filter_by(nombre=nombre).first():
            flash("Ya existe un hospital con ese nombre.", "danger")
            return render_template("hosp_form.html")

        logo_filename_db = None
        if logo_file and logo_file.filename:
            if not allowed_logo_file(logo_file.filename):
                flash("Tipo de logo no permitido. Use PNG/JPG/JPEG/GIF.", "danger")
                return render_template("hosp_form.html")

            safe_name = secure_filename(logo_file.filename)
            save_path = os.path.join(UPLOAD_FOLDER_LOGOS, safe_name)
            logo_file.save(save_path)
            logo_filename_db = os.path.join(LOGOS_SUBFOLDER, safe_name).replace("\\", "/")

        h = Hospital(nombre=nombre, activo=True, logo_filename=logo_filename_db)
        db.session.add(h)
        db.session.commit()
        flash("Hospital creado.", "success")
        return redirect(url_for("hospitales_list"))

    return render_template("hosp_form.html")


@app.route("/hospitales/editar/<int:h_id>", methods=["GET", "POST"])
@login_required
@admin_required
def hospitales_editar(h_id):
    h = Hospital.query.get_or_404(h_id)

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        activo = True if request.form.get("activo") == "on" else False
        logo_file = request.files.get("logo_file")
        borrar_logo = True if request.form.get("borrar_logo") == "on" else False

        if not nombre:
            flash("El nombre es obligatorio.", "danger")
            return render_template("hosp_form.html", h=h)

        existe = Hospital.query.filter(Hospital.id != h.id, Hospital.nombre == nombre).first()
        if existe:
            flash("Ya existe otro hospital con ese nombre.", "danger")
            return render_template("hosp_form.html", h=h)

        h.nombre = nombre
        h.activo = activo

        if borrar_logo:
            h.logo_filename = None

        if logo_file and logo_file.filename:
            if not allowed_logo_file(logo_file.filename):
                flash("Tipo de logo no permitido. Use PNG/JPG/JPEG/GIF.", "danger")
                return render_template("hosp_form.html", h=h)

            safe_name = secure_filename(logo_file.filename)
            save_path = os.path.join(UPLOAD_FOLDER_LOGOS, safe_name)
            logo_file.save(save_path)
            h.logo_filename = os.path.join(LOGOS_SUBFOLDER, safe_name).replace("\\", "/")

        db.session.commit()
        flash("Hospital actualizado.", "success")
        return redirect(url_for("hospitales_list"))

    return render_template("hosp_form.html", h=h)


@app.route("/hospitales/eliminar/<int:h_id>", methods=["POST"])
@login_required
@admin_required
def hospitales_eliminar(h_id):
    h = Hospital.query.get_or_404(h_id)
    h.activo = False
    db.session.commit()
    flash("Hospital desactivado (puedes reactivarlo editando).", "success")
    return redirect(url_for("hospitales_list"))


# ======================================================================
#   GESTIÓN DE USUARIOS (ADMIN GENERAL + ADMIN HOSPITAL)
# ======================================================================
@app.route("/usuarios")
@login_required
@hospital_admin_required
def usuarios_list():
    q = User.query
    if current_user.is_admin:
        usuarios = q.order_by(
            User.is_admin.desc(),
            User.is_hospital_admin.desc(),
            User.username.asc()
        ).all()
    else:
        usuarios = q.filter(User.hospital == current_user.hospital).order_by(
            User.is_admin.desc(),
            User.is_hospital_admin.desc(),
            User.username.asc()
        ).all()

    return render_template("users_list.html", usuarios=usuarios)


@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@login_required
@hospital_admin_required
def usuarios_nuevo():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        hospital = (request.form.get("hospital") or "").strip()
        password1 = request.form.get("password1") or ""
        password2 = request.form.get("password2") or ""

        if not username:
            flash("El nombre de usuario es obligatorio.", "danger")
            return render_template("user_form.html")

        if User.query.filter_by(username=username).first():
            flash("Ya existe un usuario con ese nombre.", "danger")
            return render_template("user_form.html")

        if not password1:
            flash("La contraseña es obligatoria.", "danger")
            return render_template("user_form.html")

        if password1 != password2:
            flash("Las contraseñas no coinciden.", "danger")
            return render_template("user_form.html")

        if current_user.is_admin:
            hospital_final = hospital or None
            if hospital_final:
                h = Hospital.query.filter_by(nombre=hospital_final, activo=True).first()
                if not h:
                    flash("Hospital inválido o inactivo.", "danger")
                    return render_template("user_form.html")
        else:
            hospital_final = current_user.hospital
            if not hospital_final:
                flash("Tu usuario no tiene hospital asignado.", "danger")
                return render_template("user_form.html")

        if current_user.is_admin:
            is_admin = True if request.form.get("is_admin") == "on" else False
            is_hosp_admin = True if request.form.get("is_hospital_admin") == "on" else False
        else:
            is_admin = False
            is_hosp_admin = True if request.form.get("is_hospital_admin") == "on" else False

        u = User(
            username=username,
            hospital=hospital_final,
            is_admin=is_admin,
            is_hospital_admin=is_hosp_admin,
            nombre=request.form.get("nombre") or "",
            apellido=request.form.get("apellido") or "",
            cedula=request.form.get("cedula") or "",
            especialidad=request.form.get("especialidad") or "",
            cargo=request.form.get("cargo") or "",
            exequatur=request.form.get("exequatur") or "",
            telefono=request.form.get("telefono") or "",
            email=request.form.get("email") or "",
        )
        u.set_password(password1)
        db.session.add(u)
        db.session.commit()
        flash("Usuario creado correctamente.", "success")
        return redirect(url_for("usuarios_list"))

    return render_template("user_form.html")


@app.route("/usuarios/editar/<int:u_id>", methods=["GET", "POST"])
@login_required
@hospital_admin_required
def usuarios_editar(u_id):
    u = User.query.get_or_404(u_id)

    if not current_user.is_admin and u.hospital != current_user.hospital:
        flash("No puedes editar usuarios de otros hospitales.", "danger")
        return redirect(url_for("usuarios_list"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        hospital = (request.form.get("hospital") or "").strip()
        password1 = request.form.get("password1") or ""
        password2 = request.form.get("password2") or ""

        if current_user.is_admin:
            is_admin = True if request.form.get("is_admin") == "on" else False
            is_hosp_admin = True if request.form.get("is_hospital_admin") == "on" else False
        else:
            is_admin = u.is_admin
            is_hosp_admin = True if request.form.get("is_hospital_admin") == "on" else False

        if not username:
            flash("El nombre de usuario es obligatorio.", "danger")
            return render_template("user_form.html", u=u)

        existe = User.query.filter(User.id != u.id, User.username == username).first()
        if existe:
            flash("Ya existe otro usuario con ese nombre.", "danger")
            return render_template("user_form.html", u=u)

        if current_user.is_admin:
            hospital_final = hospital or None
            if hospital_final:
                h = Hospital.query.filter_by(nombre=hospital_final, activo=True).first()
                if not h:
                    flash("Hospital inválido o inactivo.", "danger")
                    return render_template("user_form.html", u=u)
        else:
            hospital_final = current_user.hospital
            if not hospital_final:
                flash("Tu usuario no tiene hospital asignado.", "danger")
                return render_template("user_form.html", u=u)

        u.username = username
        u.hospital = hospital_final
        u.is_admin = is_admin
        u.is_hospital_admin = is_hosp_admin
        u.nombre = request.form.get("nombre") or u.nombre
        u.apellido = request.form.get("apellido") or u.apellido
        u.cedula = request.form.get("cedula") or u.cedula
        u.especialidad = request.form.get("especialidad") or u.especialidad
        u.cargo = request.form.get("cargo") or u.cargo
        u.exequatur = request.form.get("exequatur") or u.exequatur
        u.telefono = request.form.get("telefono") or u.telefono
        u.email = request.form.get("email") or u.email

        if password1 or password2:
            if password1 != password2:
                flash("Las contraseñas no coinciden.", "danger")
                return render_template("user_form.html", u=u)
            if not password1:
                flash("La nueva contraseña no puede estar vacía.", "danger")
                return render_template("user_form.html", u=u)
            u.set_password(password1)

        db.session.commit()
        flash("Usuario actualizado correctamente.", "success")
        return redirect(url_for("usuarios_list"))

    return render_template("user_form.html", u=u)


@app.route("/usuarios/eliminar/<int:u_id>", methods=["POST"])
@login_required
@hospital_admin_required
def usuarios_eliminar(u_id):
    u = User.query.get_or_404(u_id)

    if current_user.id == u.id:
        flash("No puedes eliminar tu propio usuario.", "danger")
        return redirect(url_for("usuarios_list"))

    if not current_user.is_admin and u.hospital != current_user.hospital:
        flash("No puedes eliminar usuarios de otros hospitales.", "danger")
        return redirect(url_for("usuarios_list"))

    db.session.delete(u)
    db.session.commit()
    flash("Usuario eliminado correctamente.", "success")
    return redirect(url_for("usuarios_list"))


# ======================================================================
#   GUARDIAS
# ======================================================================
@app.route("/guardias")
@login_required
def guardias_list():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde")
    f_hasta = request.args.get("hasta")

    def parse_date(s):
        try:
            return parser.parse(s).date()
        except Exception:
            return None

    d_desde = parse_date(f_desde) if f_desde else None
    d_hasta = parse_date(f_hasta) if f_hasta else None

    hoy = date.today()
    if not d_desde and not d_hasta:
        d_desde = hoy.replace(day=1)
        d_hasta = hoy
    else:
        if d_desde and not d_hasta:
            d_hasta = hoy
        if d_hasta and not d_desde:
            d_desde = d_hasta.replace(day=1)

    if d_desde and d_hasta and d_desde > d_hasta:
        d_desde, d_hasta = d_hasta, d_desde

    q = GuardiaEmergencia.query

    scope_hosp = user_hospital_scope()
    if scope_hosp:
        q = q.filter(GuardiaEmergencia.hospital == scope_hosp)
        hospitales_scope = [scope_hosp]
    else:
        if f_hospital:
            q = q.filter(GuardiaEmergencia.hospital == f_hospital)
            hospitales_scope = [f_hospital]
        else:
            hospitales_scope = [h.nombre for h in Hospital.query.filter_by(activo=True).all()]

    if d_desde:
        q = q.filter(GuardiaEmergencia.fecha >= d_desde)
    if d_hasta:
        q = q.filter(GuardiaEmergencia.fecha <= d_hasta)

    guardias = q.order_by(GuardiaEmergencia.fecha.desc(), GuardiaEmergencia.id.desc()).all()

    def date_range(start: date, end: date):
        cur = start
        while cur <= end:
            yield cur
            cur += timedelta(days=1)

    pendientes_por_hospital = {}
    total_pendientes = 0

    for hosp_name in hospitales_scope:
        fechas_con_guardia = {g.fecha for g in guardias if g.hospital == hosp_name}
        faltantes = [d for d in date_range(d_desde, d_hasta) if d not in fechas_con_guardia]

        if faltantes:
            pendientes_por_hospital[hosp_name] = faltantes
            total_pendientes += len(faltantes)

    pendiente_count = 0
    pendiente_fechas = []
    if len(hospitales_scope) == 1:
        hname = hospitales_scope[0]
        if hname in pendientes_por_hospital:
            pendiente_fechas = [d.strftime("%Y-%m-%d") for d in pendientes_por_hospital[hname]]
            pendiente_count = len(pendiente_fechas)

    return render_template(
        "guardias_list.html",
        guardias=guardias,
        rango_inicio=d_desde.strftime("%Y-%m-%d") if d_desde else "",
        rango_fin=d_hasta.strftime("%Y-%m-%d") if d_hasta else "",
        pendientes_por_hospital=pendientes_por_hospital,
        total_pendientes=total_pendientes,
        pendiente_count=pendiente_count,
        pendiente_fechas=pendiente_fechas,
    )


@app.route("/guardias/nuevo", methods=["GET", "POST"])
@login_required
def guardias_nuevo():
    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            fecha = parser.parse(fecha_str).date() if fecha_str else datetime.today().date()

            hospital_nombre = (
                (request.form.get("hospital") or "").strip()
                if current_user.is_admin
                else current_user.hospital
            )

            if not hospital_nombre:
                flash("Debe indicar un hospital.", "danger")
                return render_template("guardias_form.html")

            existe = GuardiaEmergencia.query.filter_by(fecha=fecha, hospital=hospital_nombre).first()
            if existe:
                flash("Ya existe una guardia registrada para esa fecha y hospital.", "danger")
                return redirect(url_for("guardias_editar", g_id=existe.id))

            def to_int(name):
                val = (request.form.get(name) or "0").strip()
                try:
                    return max(int(val), 0)
                except Exception:
                    return 0

            g = GuardiaEmergencia(
                fecha=fecha,
                hospital=hospital_nombre,
                medicos_emergencia=(request.form.get("medicos_emergencia") or "").strip(),
                total_matutino=to_int("total_matutino"),
                total_vespertino=to_int("total_vespertino"),
                total_nocturno=to_int("total_nocturno"),
                adultos=to_int("adultos"),
                pediatricos=to_int("pediatricos"),
                ginecologicas=to_int("ginecologicas"),
                ingresados_total=to_int("ingresados_total"),
                ingresados_en_emergencia=to_int("ingresados_en_emergencia"),
                fallecidos=to_int("fallecidos"),
                traidos_911=to_int("traidos_911"),
                de_cuidados=to_int("de_cuidados"),
                referidos=to_int("referidos"),
                eventualidades=(request.form.get("eventualidades") or "").strip(),
                firma=(request.form.get("firma") or "").strip(),
                created_by_id=current_user.id
            )

            db.session.add(g)
            db.session.commit()
            flash("Guardia creada correctamente.", "success")
            return redirect(url_for("guardias_list"))

        except Exception as e:
            flash(f"Error guardando guardia: {e}", "danger")

    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template("guardias_form.html", hoy=hoy, g=None)


@app.route("/guardias/editar/<int:g_id>", methods=["GET", "POST"])
@login_required
def guardias_editar(g_id):
    g = GuardiaEmergencia.query.get_or_404(g_id)

    scope_hosp = user_hospital_scope()
    if scope_hosp and g.hospital != scope_hosp:
        flash("No puedes editar guardias de otros hospitales.", "danger")
        return redirect(url_for("guardias_list"))

    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            nueva_fecha = parser.parse(fecha_str).date() if fecha_str else g.fecha

            hospital_nombre = (
                (request.form.get("hospital") or g.hospital).strip()
                if current_user.is_admin
                else g.hospital
            )

            dup = GuardiaEmergencia.query.filter(
                GuardiaEmergencia.id != g.id,
                GuardiaEmergencia.fecha == nueva_fecha,
                GuardiaEmergencia.hospital == hospital_nombre
            ).first()
            if dup:
                flash("Ya existe otra guardia para esa fecha y hospital.", "danger")
                return render_template("guardias_form.html", g=g)

            def to_int(name, current):
                val = request.form.get(name, "")
                if val == "":
                    return current
                try:
                    return max(int(val), 0)
                except Exception:
                    return current

            g.fecha = nueva_fecha
            g.hospital = hospital_nombre
            g.medicos_emergencia = (request.form.get("medicos_emergencia") or "").strip()
            g.total_matutino = to_int("total_matutino", g.total_matutino)
            g.total_vespertino = to_int("total_vespertino", g.total_vespertino)
            g.total_nocturno = to_int("total_nocturno", g.total_nocturno)
            g.adultos = to_int("adultos", g.adultos)
            g.pediatricos = to_int("pediatricos", g.pediatricos)
            g.ginecologicas = to_int("ginecologicas", g.ginecologicas)
            g.ingresados_total = to_int("ingresados_total", g.ingresados_total)
            g.ingresados_en_emergencia = to_int("ingresados_en_emergencia", g.ingresados_en_emergencia)
            g.fallecidos = to_int("fallecidos", g.fallecidos)
            g.traidos_911 = to_int("traidos_911", g.traidos_911)
            g.de_cuidados = to_int("de_cuidados", g.de_cuidados)
            g.referidos = to_int("referidos", g.referidos)
            g.eventualidades = (request.form.get("eventualidades") or "").strip()
            g.firma = (request.form.get("firma") or "").strip()

            db.session.commit()
            flash("Guardia actualizada correctamente.", "success")
            return redirect(url_for("guardias_list"))

        except Exception as e:
            flash(f"Error actualizando guardia: {e}", "danger")

    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template("guardias_edit.html", hoy=hoy, g=g)


@app.route("/guardias/eliminar/<int:g_id>", methods=["POST"])
@login_required
@hospital_admin_required
def guardias_eliminar(g_id):
    g = GuardiaEmergencia.query.get_or_404(g_id)

    scope_hosp = user_hospital_scope()
    if scope_hosp and g.hospital != scope_hosp:
        flash("No puedes eliminar guardias de otros hospitales.", "danger")
        return redirect(url_for("guardias_list"))

    db.session.delete(g)
    db.session.commit()
    flash("Guardia eliminada correctamente.", "success")
    return redirect(url_for("guardias_list"))


@app.route("/guardias/<int:g_id>/pdf")
@login_required
def guardias_pdf(g_id):
    g = GuardiaEmergencia.query.get_or_404(g_id)

    hosp = Hospital.query.filter_by(nombre=g.hospital, activo=True).first()

    scope_hosp = user_hospital_scope()
    if scope_hosp and g.hospital != scope_hosp:
        flash("No puedes ver guardias de otros hospitales.", "danger")
        return redirect(url_for("guardias_list"))

    html = render_template(
        "guardia_pdf.html",
        g=g,
        hosp=hosp,
        generated_at=datetime.now()
    )
    filename = f"guardia_{g.hospital.replace(' ', '_')}_{g.fecha.isoformat()}.pdf"
    return render_pdf_from_html(html, pdf_filename=filename)


# ======================================================================
#   INTERNAMIENTOS
# ======================================================================
@app.route("/internamientos")
@login_required
def internamientos_list():
    f_hospital = (request.args.get("hospital") or "").strip()
    f_desde = request.args.get("desde")
    f_hasta = request.args.get("hasta")

    mostrar_egresados = request.args.get("egresados") == "1"

    q = Internamiento.query.options(joinedload(Internamiento.created_by))

    if not mostrar_egresados:
        q = q.filter(Internamiento.egresado == False)

    scope_hosp = user_hospital_scope()
    if scope_hosp:
        q = q.filter(Internamiento.hospital == scope_hosp)
    else:
        if f_hospital:
            q = q.filter(Internamiento.hospital == f_hospital)

    def parse_date(s):
        try:
            return parser.parse(s).date()
        except Exception:
            return None

    d_desde = parse_date(f_desde) if f_desde else None
    d_hasta = parse_date(f_hasta) if f_hasta else None

    hoy = date.today()
    if not d_desde and not d_hasta:
        d_desde = hoy.replace(day=1)
        d_hasta = hoy
    else:
        if d_desde and not d_hasta:
            d_hasta = hoy
        if d_hasta and not d_desde:
            d_desde = d_hasta.replace(day=1)

    if d_desde and d_hasta and d_desde > d_hasta:
        d_desde, d_hasta = d_hasta, d_desde

    if d_desde:
        q = q.filter(Internamiento.fecha >= d_desde)
    if d_hasta:
        q = q.filter(Internamiento.fecha <= d_hasta)

    internamientos = q.order_by(Internamiento.fecha.desc(), Internamiento.id.desc()).all()

    return render_template(
        "internamientos_list.html",
        internamientos=internamientos,
        rango_inicio=d_desde.strftime("%Y-%m-%d") if d_desde else "",
        rango_fin=d_hasta.strftime("%Y-%m-%d") if d_hasta else "",
        f_hospital=f_hospital,
        mostrar_egresados=mostrar_egresados
    )


@app.route("/internamientos/nuevo", methods=["GET", "POST"])
@login_required
def internamientos_nuevo():
    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            fecha = parser.parse(fecha_str).date() if fecha_str else datetime.today().date()

            if current_user.is_admin or current_user.is_hospital_admin:
                hospital_nombre = (request.form.get("hospital") or current_user.hospital or "").strip()
            else:
                hospital_nombre = current_user.hospital

            if not hospital_nombre:
                flash("Debe indicar un hospital.", "danger")
                return render_template("internamientos_form.html", ir=None)

            def to_int_or_none(name):
                val = (request.form.get(name) or "").strip()
                if not val:
                    return None
                try:
                    return int(val)
                except Exception:
                    return None

            dia_ingreso_str = (request.form.get("dia_ingreso") or "").strip()
            dia_ingreso_val = None
            if dia_ingreso_str:
                try:
                    dia_ingreso_val = parser.parse(dia_ingreso_str).date()
                except Exception:
                    dia_ingreso_val = None

            ir = Internamiento(
                fecha=fecha,
                hospital=hospital_nombre,
                area=(request.form.get("area") or "").strip(),
                habitacion=(request.form.get("habitacion") or "").strip(),
                nombre_paciente=(request.form.get("nombre_paciente") or "").strip(),
                edad=to_int_or_none("edad"),
                signos_vitales=(request.form.get("signos_vitales") or "").strip(),
                diagnosticos=(request.form.get("diagnosticos") or "").strip(),
                condicion_plan=(request.form.get("condicion_plan") or "").strip(),
                origen_ingreso=(request.form.get("origen_ingreso") or "").strip(),
                observaciones=(request.form.get("observaciones") or "").strip(),
                egresado=True if request.form.get("egresado") == "on" else False,
                dia_ingreso=dia_ingreso_val,
                created_by_id=current_user.id
            )

            db.session.add(ir)
            db.session.commit()
            flash("Internamiento registrado correctamente.", "success")
            return redirect(url_for("internamientos_list"))

        except Exception as e:
            flash(f"Error guardando internamiento: {e}", "danger")

    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template("internamientos_form.html", hoy=hoy, ir=None)


@app.route("/internamientos/editar/<int:i_id>", methods=["GET", "POST"])
@login_required
def internamientos_editar(i_id):
    ir = Internamiento.query.get_or_404(i_id)

    scope_hosp = user_hospital_scope()
    if scope_hosp and ir.hospital != scope_hosp:
        flash("No puedes editar internamientos de otros hospitales.", "danger")
        return redirect(url_for("internamientos_list"))

    if request.method == "POST":
        try:
            fecha_str = request.form.get("fecha")
            ir.fecha = parser.parse(fecha_str).date() if fecha_str else ir.fecha

            if current_user.is_admin or current_user.is_hospital_admin:
                hospital_nombre = (request.form.get("hospital") or ir.hospital).strip()
                ir.hospital = hospital_nombre

            def to_int_or_none(name, current=None):
                val = (request.form.get(name) or "").strip()
                if val == "":
                    return current
                try:
                    return int(val)
                except Exception:
                    return current

            ir.edad = to_int_or_none("edad", ir.edad)

            dia_ingreso_str = (request.form.get("dia_ingreso") or "").strip()
            if dia_ingreso_str:
                try:
                    ir.dia_ingreso = parser.parse(dia_ingreso_str).date()
                except Exception:
                    pass

            ir.area = (request.form.get("area") or "").strip()
            ir.habitacion = (request.form.get("habitacion") or "").strip()
            ir.nombre_paciente = (request.form.get("nombre_paciente") or "").strip()
            ir.signos_vitales = (request.form.get("signos_vitales") or "").strip()
            ir.diagnosticos = (request.form.get("diagnosticos") or "").strip()
            ir.condicion_plan = (request.form.get("condicion_plan") or "").strip()
            ir.origen_ingreso = (request.form.get("origen_ingreso") or "").strip()
            ir.observaciones = (request.form.get("observaciones") or "").strip()
            ir.egresado = True if request.form.get("egresado") == "on" else False

            db.session.commit()
            flash("Internamiento actualizado correctamente.", "success")
            return redirect(url_for("internamientos_list"))

        except Exception as e:
            flash(f"Error actualizando internamiento: {e}", "danger")

    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template("internamientos_form.html", hoy=hoy, ir=ir)


@app.route("/internamientos/eliminar/<int:i_id>", methods=["POST"])
@login_required
def internamientos_eliminar(i_id):
    ir = Internamiento.query.get_or_404(i_id)

    scope_hosp = user_hospital_scope()
    if scope_hosp and ir.hospital != scope_hosp:
        flash("No puedes eliminar internamientos de otros hospitales.", "danger")
        return redirect(url_for("internamientos_list"))

    db.session.delete(ir)
    db.session.commit()
    flash("Internamiento eliminado correctamente.", "success")
    return redirect(url_for("internamientos_list"))


@app.route("/internamientos/pdf")
@login_required
def internamientos_pdf():

    # 1) SOLO VALIDACIÓN
    if request.args.get("validar") == "1":
        fecha_str = request.args.get("fecha")
        try:
            fecha_reporte = parser.parse(fecha_str).date() if fecha_str else date.today()
        except Exception:
            fecha_reporte = date.today()

        scope_hosp = user_hospital_scope()
        hospital_nombre = scope_hosp or (request.args.get("hospital") or current_user.hospital).strip()

        activos = Internamiento.query.filter(
            Internamiento.hospital == hospital_nombre,
            Internamiento.egresado == False,
            Internamiento.fecha <= fecha_reporte
        ).all()

        faltantes = []
        for i in activos:
            if not i.fecha_actualizacion or i.fecha_actualizacion.date() != fecha_reporte:
                faltantes.append({
                    "id": i.id,
                    "nombre": i.nombre_paciente,
                    "area": i.area or "",
                    "habitacion": i.habitacion or ""
                })

        return jsonify({"ok": len(faltantes) == 0, "faltantes": faltantes})

    # 2) GENERAR PDF
    if request.args.get("generar") == "1":
        fecha_str = request.args.get("fecha")
        try:
            fecha_reporte = parser.parse(fecha_str).date() if fecha_str else date.today()
        except Exception:
            fecha_reporte = date.today()

        mostrar_egresados = request.args.get("egresados") == "1"

        q = Internamiento.query.options(joinedload(Internamiento.created_by))

        scope_hosp = user_hospital_scope()
        hospital_nombre = scope_hosp or (request.args.get("hospital") or current_user.hospital).strip()

        q = q.filter(Internamiento.hospital == hospital_nombre)

        if not mostrar_egresados:
            q = q.filter(Internamiento.egresado == False)

        q = q.filter(Internamiento.fecha <= fecha_reporte)

        internamientos = q.order_by(
            Internamiento.area.asc(),
            Internamiento.habitacion.asc(),
            Internamiento.nombre_paciente.asc()
        ).all()

        hosp = Hospital.query.filter_by(nombre=hospital_nombre, activo=True).first()
        observaciones_generales = (request.args.get("observaciones_generales") or "").strip()

        html = render_template(
            "internamientos_pdf.html",
            internamientos=internamientos,
            hosp=hosp,
            fecha_reporte=fecha_reporte,
            generated_at=datetime.now(),
            mostrar_egresados=mostrar_egresados,
            observaciones_generales=observaciones_generales
        )

        filename = f"internamientos_{hospital_nombre.replace(' ', '_')}_{fecha_reporte.isoformat()}.pdf"
        return render_pdf_from_html(html, pdf_filename=filename)

    return jsonify({"error": "Modo inválido"}), 400


# ======================================================================
#   PWA: manifest / service worker / offline
# ======================================================================
@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/offline")
def offline():
    return render_template("offline.html")


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

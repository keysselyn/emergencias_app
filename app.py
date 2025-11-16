from flask import (
    Flask, render_template, request, redirect, url_for, flash, Response,
    send_from_directory, abort
)
from flask_login import (
    LoginManager, login_user, logout_user, current_user, login_required
)
from datetime import datetime
from io import StringIO, BytesIO
from functools import wraps
import csv, json, os
from dateutil import parser

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
from openpyxl.utils import get_column_letter

from sqlalchemy import text  # para /healthz
from models import db, EmergencyRecord, User, Hospital

# -------------------- Configuración base (Railway/MySQL) --------------------
app = Flask(__name__)

# ======= DB CONFIG: MySQL (sin SQLite) =======
# Opción A: usar DATABASE_URL directamente
#   Formato: mysql+pymysql://USER:PASS@HOST:PORT/DBNAME?charset=utf8mb4
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:@127.0.0.1:3306/emergencias?charset=utf8mb4"
)

# Opción B: usar variables del plugin MySQL de Railway
# (MYSQLHOST, MYSQLUSER, MYSQLPASSWORD, MYSQLPORT, MYSQLDATABASE)
if not DATABASE_URL:
    rh = os.getenv("MYSQLHOST")
    ru = os.getenv("MYSQLUSER")
    rp = os.getenv("MYSQLPASSWORD")
    rport = os.getenv("MYSQLPORT", "3306")
    rdb = os.getenv("MYSQLDATABASE")
    if rh and ru and rp and rdb:
        DATABASE_URL = f"mysql+pymysql://{ru}:{rp}@{rh}:{rport}/{rdb}?charset=utf8mb4"

# Si aún no hay DATABASE_URL → error explícito
if not DATABASE_URL:
    raise RuntimeError(
        "No se ha configurado la base de datos. "
        "Define DATABASE_URL o las variables MYSQLHOST, MYSQLUSER, "
        "MYSQLPASSWORD, MYSQLPORT, MYSQLDATABASE."
    )

# Normaliza MySQL URL → mysql+pymysql://
if DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)

# Asegura charset si es MySQL
if DATABASE_URL.startswith("mysql+pymysql://") and "charset=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}charset=utf8mb4"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "cambia-esta-clave")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(fn):
    """Protege rutas para Administradores."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Solo Administradores.', 'danger')
            return redirect(url_for('index'))
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_choices():
    """Hace disponibles los hospitales activos en todas las plantillas."""
    try:
        hospitales = Hospital.query.filter_by(activo=True).order_by(Hospital.nombre.asc()).all()
    except Exception:
        hospitales = []
    return dict(HOSPITALES=hospitales)


# -------------------- BOOTSTRAP automático (opcional) --------------------
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
    """Crea tablas y un admin si la DB está vacía (controlado por BOOTSTRAP_ON_START=1)."""
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

            u = User(username=admin_user, hospital=admin_hosp, is_admin=True)
            u.set_password(admin_pass)
            db.session.add(u)
            db.session.commit()
            print(f"[BOOTSTRAP] Admin creado: {admin_user} / hospital={admin_hosp}")
        else:
            print("[BOOTSTRAP] Ya hay usuarios. No se crea admin nuevo.")


# Ejecutar bootstrap en arranque si BOOTSTRAP_ON_START=1
if os.getenv("BOOTSTRAP_ON_START", "0") == "1":
    try:
        bootstrap_if_empty()
    except Exception as e:
        print(f"[BOOTSTRAP] Error: {e}")


# Ruta manual opcional (por token) para forzar bootstrap 1 sola vez
@app.route('/admin/bootstrap')
def admin_bootstrap():
    token = request.args.get('token', '')
    expected = os.getenv("SETUP_TOKEN", "")
    if not expected or token != expected:
        return abort(403)
    try:
        bootstrap_if_empty()
        return "Bootstrap ejecutado", 200
    except Exception as e:
        return f"Error: {e}", 500


# -------------------- Healthcheck (diagnóstico DB) --------------------
@app.route("/healthz")
def healthz():
    try:
        db.session.execute(text("SELECT 1"))
        return "OK", 200
    except Exception as e:
        return f"DB ERROR: {e}", 500


# -------------------- Páginas base --------------------
@app.route('/')
def index():
    hoy = datetime.now().strftime("%Y-%m-%d")
    return render_template('index.html', hoy=hoy)


# -------------------- Autenticación --------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Sesión iniciada.', 'success')
            return redirect(url_for('dashboard'))
        flash('Credenciales inválidas.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('index'))

# -------------------- Registros: Crear / Editar --------------------
@app.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha')
            fecha = parser.parse(fecha_str).date() if fecha_str else datetime.today().date()

            # Hospital según rol
            if current_user.is_admin:
                hospital_nombre = (request.form.get('hospital') or '').strip()
                ok = Hospital.query.filter_by(nombre=hospital_nombre, activo=True).first()
                if not ok:
                    flash('Hospital inválido o inactivo.', 'danger')
                    return render_template('form.html')
                hospital = hospital_nombre
            else:
                hospital = current_user.hospital

            # 🚨 VALIDAR: no permitir 2 registros mismo día + mismo hospital
            existente = EmergencyRecord.query.filter_by(
                fecha=fecha,
                hospital=hospital
            ).first()

            if existente:
                flash('Ya existe un registro para este hospital en esa fecha. '
                      'Por favor edítalo en lugar de crear uno nuevo.', 'danger')
                # Si quieres, puedes mandarlo directo al editar:
                return redirect(url_for('editar', rec_id=existente.id))

            def to_int(name):
                val = request.form.get(name, '0').strip()
                try:
                    return max(int(val), 0)
                except Exception:
                    return 0

            rec = EmergencyRecord(
                fecha=fecha,
                hospital=hospital,
                atenciones=to_int('atenciones'),
                ingresos=to_int('ingresos'),
                alta_voluntario=to_int('alta_voluntario'),
                traslados=to_int('traslados'),
                defunciones=to_int('defunciones'),
                motivo_traslado=(request.form.get('motivo_traslado') or '').strip(),
                hospital_referencia=(request.form.get('hospital_referencia') or '').strip(),
                eventualidades=(request.form.get('eventualidades') or '').strip(),
            )
            db.session.add(rec)
            db.session.commit()
            flash('Registro guardado correctamente.', 'success')
            return redirect(url_for('listar'))
        except Exception as e:
            flash(f'Error guardando: {e}', 'danger')
    return render_template('form.html')


@app.route('/editar/<int:rec_id>', methods=['GET', 'POST'])
@login_required
def editar(rec_id):
    rec = EmergencyRecord.query.get_or_404(rec_id)

    # Seguridad: usuarios no admin solo pueden editar su hospital
    if not current_user.is_admin and rec.hospital != current_user.hospital:
        flash('No tiene permiso para editar este registro.', 'danger')
        return redirect(url_for('listar'))

    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha')
            nueva_fecha = parser.parse(fecha_str).date() if fecha_str else rec.fecha

            if current_user.is_admin:
                hospital_nombre = (request.form.get('hospital') or rec.hospital).strip()
                ok = Hospital.query.filter_by(nombre=hospital_nombre, activo=True).first()
                if not ok:
                    flash('Hospital inválido o inactivo.', 'danger')
                    return render_template('edit.html', rec=rec)
                nuevo_hospital = hospital_nombre
            else:
                nuevo_hospital = current_user.hospital

            # 🚨 VALIDAR: no permitir duplicado en OTRO registro
            duplicado = EmergencyRecord.query.filter(
                EmergencyRecord.id != rec.id,
                EmergencyRecord.fecha == nueva_fecha,
                EmergencyRecord.hospital == nuevo_hospital
            ).first()

            if duplicado:
                flash('Ya existe otro registro para este hospital en esa fecha.', 'danger')
                return render_template('edit.html', rec=rec)

            # Si pasa la validación, actualizamos
            rec.fecha = nueva_fecha
            rec.hospital = nuevo_hospital

            def to_int(name, current):
                val = request.form.get(name, None)
                if val is None or val == '':
                    return current
                try:
                    return max(int(val), 0)
                except Exception:
                    return current

            rec.atenciones = to_int('atenciones', rec.atenciones)
            rec.ingresos = to_int('ingresos', rec.ingresos)
            rec.alta_voluntario = to_int('alta_voluntario', rec.alta_voluntario)
            rec.traslados = to_int('traslados', rec.traslados)
            rec.defunciones = to_int('defunciones', rec.defunciones)
            rec.motivo_traslado = (request.form.get('motivo_traslado') or '').strip()
            rec.hospital_referencia = (request.form.get('hospital_referencia') or '').strip()
            rec.eventualidades = (request.form.get('eventualidades') or '').strip()

            db.session.commit()
            flash('Registro actualizado correctamente.', 'success')
            return redirect(url_for('listar'))
        except Exception as e:
            flash(f'Error actualizando: {e}', 'danger')
    return render_template('edit.html', rec=rec)


# -------------------- Eliminar Registro solo Admin --------------------
@app.route('/eliminar/<int:rec_id>', methods=['POST'])
@login_required
@admin_required
def eliminar(rec_id):
    """Eliminar un registro de emergencias (solo Administradores)."""
    rec = EmergencyRecord.query.get_or_404(rec_id)
    db.session.delete(rec)
    db.session.commit()
    flash('Registro eliminado correctamente.', 'success')
    return redirect(url_for('listar'))


# -------------------- Listar + Filtros --------------------
@app.route('/listar')
@login_required
def listar():
    f_hospital = (request.args.get('hospital') or '').strip()
    f_desde = request.args.get('desde')
    f_hasta = request.args.get('hasta')

    q = EmergencyRecord.query

    # Si no es admin, forzar hospital del usuario
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
    return render_template('list.html', registros=registros)


# -------------------- Exportar CSV --------------------
@app.route('/exportar_csv')
@login_required
def exportar_csv():
    f_hospital = (request.args.get('hospital') or '').strip()
    f_desde = request.args.get('desde')
    f_hasta = request.args.get('hasta')

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
        'Fecha', 'Hospital', 'Atenciones', 'Ingresos', 'Alta Voluntario',
        'Traslados', 'Motivo del traslado', 'Hospital de referencia',
        'Defunciones', 'Eventualidades'
    ])
    for r in registros:
        writer.writerow(r.to_row())
    output = si.getvalue().encode('utf-8-sig')
    return Response(
        output,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=registros_emergencias.csv'}
    )


# -------------------- Exportar Excel (con formato) --------------------
@app.route('/exportar_excel')
@login_required
def exportar_excel():
    # === 1) Filtros (igual que en listar/CSV) ===
    f_hospital = (request.args.get('hospital') or '').strip()
    f_desde = request.args.get('desde') or ''
    f_hasta = request.args.get('hasta') or ''

    def parse_date(s):
        try:
            return parser.parse(s).date() if s else None
        except Exception:
            return None

    d_desde = parse_date(f_desde)
    d_hasta = parse_date(f_hasta)

    # Si las fechas están invertidas, corrígelas
    if d_desde and d_hasta and d_desde > d_hasta:
        d_desde, d_hasta = d_hasta, d_desde
        f_desde, f_hasta = (d_desde.isoformat() if d_desde else ''), (d_hasta.isoformat() if d_hasta else '')

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

    # Salvavidas: si no hay datos y había filtros de fecha, reintenta sin fechas
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

    # === 2) Workbook con estilos ===
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

    # Encabezado
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = border_all

    # Datos
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
    COL_NUMS = [3,4,5,6,9]
    COL_TEXT_WRAP = [7,8,10]
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

        # Totales
        total_row = last_row + 1
        ws.cell(row=total_row, column=1, value="Totales")
        ws.cell(row=total_row, column=1).font = Font(bold=True)
        ws.cell(row=total_row, column=1).alignment = Alignment(horizontal="right")

        for c in COL_NUMS:
            col_letter = get_column_letter(c)
            ws.cell(row=total_row, column=c,
                    value=f"=SUM({col_letter}{row_start}:{col_letter}{last_row})").style = "number_right"
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=total_row, column=c)
            cell.border = border_all
            if c in COL_NUMS or c == 1:
                cell.fill = PatternFill("solid", fgColor="E9F2FF")

        last_row = total_row

    # Ajustes UX
    widths = {1:12, 2:38, 3:12, 4:12, 5:16, 6:12, 7:28, 8:28, 9:12, 10:50}
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"

    # Hoja resumen
    summary = wb.create_sheet("Resumen", 0)
    summary["A1"] = "Exportación de Registros de Emergencias"
    summary["A1"].font = Font(size=14, bold=True)

    summary["A3"] = "Generado:"
    summary["B3"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary["A4"] = "Hospital:"
    summary["B4"] = (f_hospital if (current_user.is_admin and f_hospital)
                     else (current_user.hospital if not current_user.is_admin else "Todos"))
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


# -------------------- Dashboard --------------------
@app.route('/dashboard')
@login_required
def dashboard():
    f_hospital = (request.args.get('hospital') or '').strip()
    f_desde = request.args.get('desde')
    f_hasta = request.args.get('hasta')

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

    # KPIs
    kpi_atenciones = sum(r.atenciones for r in registros)
    kpi_ingresos   = sum(r.ingresos for r in registros)
    kpi_traslados  = sum(r.traslados for r in registros)
    kpi_defunciones= sum(r.defunciones for r in registros)

    # Serie por fecha
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
    chart_ingresos   = [series[d]["ingresos"]   for d in dates]
    chart_traslados  = [series[d]["traslados"]  for d in dates]
    chart_defunciones= [series[d]["defunciones"]for d in dates]

    # Ranking por hospital (solo admin y si no hay filtro de hospital)
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
        'dashboard.html',
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


# -------------------- CRUD Hospitales (Admin) --------------------
@app.route('/hospitales')
@login_required
@admin_required
def hospitales_list():
    hospitales = Hospital.query.order_by(Hospital.activo.desc(), Hospital.nombre.asc()).all()
    return render_template('hosp_list.html', hospitales=hospitales)


@app.route('/hospitales/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def hospitales_nuevo():
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('hosp_form.html')
        if Hospital.query.filter_by(nombre=nombre).first():
            flash('Ya existe un hospital con ese nombre.', 'danger')
            return render_template('hosp_form.html')
        h = Hospital(nombre=nombre, activo=True)
        db.session.add(h)
        db.session.commit()
        flash('Hospital creado.', 'success')
        return redirect(url_for('hospitales_list'))
    return render_template('hosp_form.html')


@app.route('/hospitales/editar/<int:h_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def hospitales_editar(h_id):
    h = Hospital.query.get_or_404(h_id)
    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        activo = True if request.form.get('activo') == 'on' else False

        if not nombre:
            flash('El nombre es obligatorio.', 'danger')
            return render_template('hosp_form.html', h=h)

        existe = Hospital.query.filter(Hospital.id != h.id, Hospital.nombre == nombre).first()
        if existe:
            flash('Ya existe otro hospital con ese nombre.', 'danger')
            return render_template('hosp_form.html', h=h)

        h.nombre = nombre
        h.activo = activo
        db.session.commit()
        flash('Hospital actualizado.', 'success')
        return redirect(url_for('hospitales_list'))
    return render_template('hosp_form.html', h=h)


@app.route('/hospitales/eliminar/<int:h_id>', methods=['POST'])
@login_required
@admin_required
def hospitales_eliminar(h_id):
    h = Hospital.query.get_or_404(h_id)
    # Soft delete: desactivar en lugar de borrar
    h.activo = False
    db.session.commit()
    flash('Hospital desactivado (puedes reactivarlo editando).', 'success')
    return redirect(url_for('hospitales_list'))


# -------------------- Gestión de Usuarios (solo Admin) --------------------
@app.route('/usuarios')
@login_required
@admin_required
def usuarios_list():
    usuarios = User.query.order_by(User.is_admin.desc(), User.username.asc()).all()
    return render_template('users_list.html', usuarios=usuarios)


@app.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def usuarios_nuevo():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        hospital = (request.form.get('hospital') or '').strip()
        password1 = request.form.get('password1') or ''
        password2 = request.form.get('password2') or ''
        is_admin = True if request.form.get('is_admin') == 'on' else False

        # Validaciones básicas
        if not username:
            flash('El nombre de usuario es obligatorio.', 'danger')
            return render_template('user_form.html')

        if User.query.filter_by(username=username).first():
            flash('Ya existe un usuario con ese nombre.', 'danger')
            return render_template('user_form.html')

        if not password1:
            flash('La contraseña es obligatoria.', 'danger')
            return render_template('user_form.html')

        if password1 != password2:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('user_form.html')

        # Validar hospital (puede ser vacío si quieres permitir usuarios sin hospital)
        if hospital:
            h = Hospital.query.filter_by(nombre=hospital, activo=True).first()
            if not h:
                flash('Hospital inválido o inactivo.', 'danger')
                return render_template('user_form.html')

        # Crear usuario
        u = User(
            username=username,
            hospital=hospital or None,
            is_admin=is_admin
        )
        u.set_password(password1)
        db.session.add(u)
        db.session.commit()
        flash('Usuario creado correctamente.', 'success')
        return redirect(url_for('usuarios_list'))

    # GET
    return render_template('user_form.html')


@app.route('/usuarios/editar/<int:u_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def usuarios_editar(u_id):
    u = User.query.get_or_404(u_id)

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        hospital = (request.form.get('hospital') or '').strip()
        password1 = request.form.get('password1') or ''
        password2 = request.form.get('password2') or ''
        is_admin = True if request.form.get('is_admin') == 'on' else False

        if not username:
            flash('El nombre de usuario es obligatorio.', 'danger')
            return render_template('user_form.html', u=u)

        # Verificar que no exista otro usuario con ese username
        existe = User.query.filter(User.id != u.id, User.username == username).first()
        if existe:
            flash('Ya existe otro usuario con ese nombre.', 'danger')
            return render_template('user_form.html', u=u)

        # Validar hospital
        if hospital:
            h = Hospital.query.filter_by(nombre=hospital, activo=True).first()
            if not h:
                flash('Hospital inválido o inactivo.', 'danger')
                return render_template('user_form.html', u=u)

        u.username = username
        u.hospital = hospital or None
        u.is_admin = is_admin

        # Cambio de contraseña solo si se llenan ambos campos
        if password1 or password2:
            if password1 != password2:
                flash('Las contraseñas no coinciden.', 'danger')
                return render_template('user_form.html', u=u)
            if not password1:
                flash('La nueva contraseña no puede estar vacía.', 'danger')
                return render_template('user_form.html', u=u)
            u.set_password(password1)

        db.session.commit()
        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('usuarios_list'))

    return render_template('user_form.html', u=u)


@app.route('/usuarios/eliminar/<int:u_id>', methods=['POST'])
@login_required
@admin_required
def usuarios_eliminar(u_id):
    u = User.query.get_or_404(u_id)

    # Evitar que un admin se borre a sí mismo (opcional)
    if current_user.id == u.id:
        flash('No puedes eliminar tu propio usuario.', 'danger')
        return redirect(url_for('usuarios_list'))

    db.session.delete(u)
    db.session.commit()
    flash('Usuario eliminado correctamente.', 'success')
    return redirect(url_for('usuarios_list'))



# -------------------- Rutas PWA --------------------
@app.route('/manifest.webmanifest')
def manifest():
    return send_from_directory('static', 'manifest.webmanifest', mimetype='application/manifest+json')


@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


@app.route('/offline')
def offline():
    return render_template('offline.html')


# -------------------- Main --------------------
if __name__ == '__main__':
    # Railway usa PORT; local 5000
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

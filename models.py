from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)

    # Hospital al que pertenece
    hospital = db.Column(db.String(200), nullable=True, index=True)

    # Admin global (ve y administra todo)
    is_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Admin de hospital (ve solo su hospital, pero puede gestionar usuarios de su hospital)
    is_hospital_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # --- Datos personales (NUEVOS) ---
    nombre = db.Column(db.String(120), nullable=True)
    apellido = db.Column(db.String(120), nullable=True)
    cedula = db.Column(db.String(20), nullable=True)
    especialidad = db.Column(db.String(120), nullable=True)
    cargo = db.Column(db.String(120), nullable=True)
    exequatur = db.Column(db.String(20), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    

    # Métodos de ayuda para Flask-Login
    def set_password(self, raw_password: str) -> None:
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password, raw_password)

    # Flask-Login hooks
    @property
    def is_authenticated(self):  # pragma: no cover
        return True

    @property
    def is_active(self):  # pragma: no cover
        return True

    @property
    def is_anonymous(self):  # pragma: no cover
        return False

    def get_id(self):  # pragma: no cover
        return str(self.id)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} admin={self.is_admin} hosp_admin={self.is_hospital_admin}>"


class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    activo = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # NUEVO: nombre de archivo del logo (guardado en static/logos/)
    logo_filename = db.Column(db.String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Hospital {self.nombre} activo={self.activo}>"

    # Opcional: URL para usar en HTML normal
    def get_logo_url(self):
        from flask import url_for
        if self.logo_filename:
            return url_for("static", filename=f"img/{self.logo_filename}")
        return url_for("static", filename="img/logo_default.png")

    # Opcional: ruta absoluta para usar en PDF con xhtml2pdf
    def get_logo_fs_path(self):
        import os
        from flask import current_app
        if not self.logo_filename:
            return None
        return os.path.join(current_app.static_folder, "img", self.logo_filename)



class EmergencyRecord(db.Model):
    __tablename__ = "emergency_records"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, index=True)
    hospital = db.Column(db.String(200), nullable=False, index=True)

    atenciones = db.Column(db.Integer, default=0, nullable=False)
    ingresos = db.Column(db.Integer, default=0, nullable=False)
    alta_voluntario = db.Column(db.Integer, default=0, nullable=False)
    traslados = db.Column(db.Integer, default=0, nullable=False)

    motivo_traslado = db.Column(db.String(255))
    hospital_referencia = db.Column(db.String(255))

    defunciones = db.Column(db.Integer, default=0, nullable=False)
    eventualidades = db.Column(db.Text)

     # 👉 NUEVO: quién hizo el registro
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", backref="emergency_records", lazy=True)


    __table_args__ = (
        # índice útil para listados/consultas por fecha+hospital
        db.Index("ix_emergency_fecha_hospital", "fecha", "hospital"),
        # opcional: evitar duplicados por fecha+hospital
        db.UniqueConstraint("fecha", "hospital", name="uq_emergency_fecha_hospital"),
    )

    def to_row(self):
        f = self.fecha.isoformat() if isinstance(self.fecha, (date,)) else str(self.fecha or "")
        return [
            f,
            self.hospital or "",
            int(self.atenciones or 0),
            int(self.ingresos or 0),
            int(self.alta_voluntario or 0),
            int(self.traslados or 0),
            self.motivo_traslado or "",
            self.hospital_referencia or "",
            int(self.defunciones or 0),
            (self.eventualidades or "").replace("\r", " ").strip(),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmergencyRecord {self.fecha} {self.hospital}>"


# ─────────────────────────────────────────────
#  NUEVO: Guardia diaria de emergencia / planta
# ─────────────────────────────────────────────

class GuardiaEmergencia(db.Model):
    """
    Tabla para entrega de guardia diaria de salas de emergencias y planta.

    Campos según tu diseño:
    ID, Fecha, fecha_actualizacion Medicos_emergencia, Total_Matutino, Total_Vespertino, Total_Nocturno,
    Adultos, Pediatricos, Ginecologicas, Ingresados_Total, Ingresados_en_Emergencia,
    Fallecidos, Traidos_911, De_Cuidados, Referidos, Eventualidades, Firma
    """
    __tablename__ = "guardias_emergencia"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, index=True)
    hospital = db.Column(db.String(200), nullable=False, index=True)

    medicos_emergencia = db.Column(db.String(255), nullable=True)

    total_matutino = db.Column(db.Integer, default=0, nullable=False)
    total_vespertino = db.Column(db.Integer, default=0, nullable=False)
    total_nocturno = db.Column(db.Integer, default=0, nullable=False)

    adultos = db.Column(db.Integer, default=0, nullable=False)
    pediatricos = db.Column(db.Integer, default=0, nullable=False)
    ginecologicas = db.Column(db.Integer, default=0, nullable=False)

    ingresados_total = db.Column(db.Integer, default=0, nullable=False)
    ingresados_en_emergencia = db.Column(db.Integer, default=0, nullable=False)

    fallecidos = db.Column(db.Integer, default=0, nullable=False)
    traidos_911 = db.Column(db.Integer, default=0, nullable=False)
    de_cuidados = db.Column(db.Integer, default=0, nullable=False)
    referidos = db.Column(db.Integer, default=0, nullable=False)

    eventualidades = db.Column(db.Text, nullable=True)
    firma = db.Column(db.String(255), nullable=True)

        # Usuario que creó la guardia
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", backref="guardias_creadas", lazy=True)


    __table_args__ = (
        # Evita que haya dos guardias para el mismo hospital y misma fecha
        db.UniqueConstraint("fecha", "hospital", name="uq_guardia_fecha_hospital"),
        db.Index("ix_guardia_fecha_hospital", "fecha", "hospital"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GuardiaEmergencia {self.fecha} {self.hospital}>"
    
class Internamiento(db.Model):
    """
    Registros de pacientes en internamiento.
    """
    __tablename__ = "internamientos"

    id = db.Column(db.Integer, primary_key=True)

    # opcional
    guardia_id = db.Column(
        db.Integer,
        db.ForeignKey("guardias_emergencia.id"),
        nullable=True,
        index=True
    )

    # FECHA = FECHA DE INGRESO REAL
    fecha = db.Column(db.Date, nullable=False, index=True)
    fecha_actualizacion = db.Column(db.DateTime, nullable=True, index=True)

    hospital = db.Column(db.String(200), nullable=False, index=True)
    area = db.Column(db.String(100), nullable=True)
    habitacion = db.Column(db.String(50), nullable=True)

    nombre_paciente = db.Column(db.String(200), nullable=False)
    edad = db.Column(db.Integer, nullable=True)

    # 🔹 Se guarda automáticamente (días hospitalizado)
    dia_ingreso = db.Column(db.Integer, nullable=True)

    # 🔹 Nuevo: egresado
    egresado = db.Column(db.Boolean, default=False, nullable=False, index=True)

    signos_vitales = db.Column(db.Text, nullable=True)
    diagnosticos = db.Column(db.Text, nullable=True)
    condicion_plan = db.Column(db.Text, nullable=True)
    origen_ingreso = db.Column(db.String(150), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", backref="internamientos_creados", lazy=True)

    guardia = db.relationship(
        "GuardiaEmergencia",
        backref="internamientos",
        lazy=True
    )

    __table_args__ = (
        db.Index("ix_internamiento_fecha_hospital", "fecha", "hospital"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Internamiento {self.fecha} {self.hospital} {self.nombre_paciente}>"

    # ======================================================
    #  PROPIEDADES Y CÁLCULOS AUTOMÁTICOS
    # ======================================================

    @property
    def dias_hospitalizado(self):
        """
        Calcula los días desde la fecha de ingreso hasta hoy.
        """
        from datetime import date
        if not self.fecha:
            return 0
        hoy = date.today()
        diff = (hoy - self.fecha).days
        return diff + 1 if diff >= 0 else 0

    def actualizar_dia_ingreso(self):
        """
        Actualiza la columna dia_ingreso automáticamente.
        """
        self.dia_ingreso = self.dias_hospitalizado


# ==========================================================
# EVENTOS AUTOMÁTICOS PARA ACTUALIZAR DÍA DE INGRESO
# ==========================================================
from sqlalchemy import event

@event.listens_for(Internamiento, "before_insert")
def internamiento_before_insert(mapper, connection, target):
    target.actualizar_dia_ingreso()

     # 2) fecha_actualizacion = fecha de ingreso (00:00)
    if target.fecha and not target.fecha_actualizacion:
        target.fecha_actualizacion = datetime.combine(target.fecha, datetime.min.time())

@event.listens_for(Internamiento, "before_update")
def internamiento_before_update(mapper, connection, target):
    target.actualizar_dia_ingreso()

    # 2) fecha_actualizacion = ahora (momento real del update)
    target.fecha_actualizacion = datetime.utcnow()


    __table_args__ = (
        db.Index("ix_internamiento_fecha_hospital", "fecha", "hospital"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Internamiento {self.fecha} {self.hospital} {self.nombre_paciente}>"
    



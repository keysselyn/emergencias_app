from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from sqlalchemy import event

db = SQLAlchemy()


# ======================================================
#   USUARIOS
# ======================================================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # username indexado y único
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)

    # hash de contraseña
    password = db.Column(db.String(255), nullable=False)

    # Hospital al que pertenece (texto, como usas en tu app)
    hospital = db.Column(db.String(200), nullable=True, index=True)

    # Roles
    is_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_hospital_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Datos personales
    nombre = db.Column(db.String(120), nullable=True)
    apellido = db.Column(db.String(120), nullable=True)
    cedula = db.Column(db.String(20), nullable=True)
    especialidad = db.Column(db.String(120), nullable=True)
    cargo = db.Column(db.String(120), nullable=True)
    exequatur = db.Column(db.String(20), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    __table_args__ = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }

    def set_password(self, raw_password: str) -> None:
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password, raw_password)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username} admin={self.is_admin} hosp_admin={self.is_hospital_admin}>"


# ======================================================
#   HOSPITALES
# ======================================================
class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(191), unique=True, nullable=False, index=True)
    activo = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # guarda ruta relativa a static/img/
    logo_filename = db.Column(db.String(255), nullable=True)

    __table_args__ = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Hospital {self.nombre} activo={self.activo}>"

    def get_logo_url(self):
        from flask import url_for
        if self.logo_filename:
            return url_for("static", filename=f"img/{self.logo_filename}")
        return url_for("static", filename="img/logo_default.png")

    def get_logo_fs_path(self):
        import os
        from flask import current_app
        if not self.logo_filename:
            return None
        return os.path.join(current_app.static_folder, "img", self.logo_filename)


# ======================================================
#   REGISTRO DIARIO DE EMERGENCIAS
# ======================================================
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

    # quién creó el registro
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", backref="emergency_records", lazy=True)

    __table_args__ = (
        db.Index("ix_emergency_fecha_hospital", "fecha", "hospital"),
        db.UniqueConstraint("fecha", "hospital", name="uq_emergency_fecha_hospital"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    def to_row(self):
        """Fila para exportar a CSV/Excel."""
        f = self.fecha.isoformat() if isinstance(self.fecha, date) else str(self.fecha or "")
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


# ======================================================
#   GUARDIAS EMERGENCIA
# ======================================================
class GuardiaEmergencia(db.Model):
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
        db.UniqueConstraint("fecha", "hospital", name="uq_guardia_fecha_hospital"),
        db.Index("ix_guardia_fecha_hospital", "fecha", "hospital"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GuardiaEmergencia {self.fecha} {self.hospital}>"


# ======================================================
#   INTERNAMIENTOS
# ======================================================
class Internamiento(db.Model):
    __tablename__ = "internamientos"

    id = db.Column(db.Integer, primary_key=True)

    guardia_id = db.Column(
        db.Integer,
        db.ForeignKey("guardias_emergencia.id"),
        nullable=True,
        index=True
    )

    # FECHA = FECHA DE INGRESO REAL
    fecha = db.Column(db.Date, nullable=False, index=True)

    # Fecha/hora última actualización
    fecha_actualizacion = db.Column(db.DateTime, nullable=True, index=True)

    hospital = db.Column(db.String(200), nullable=False, index=True)
    area = db.Column(db.String(100), nullable=True)
    habitacion = db.Column(db.String(50), nullable=True)

    nombre_paciente = db.Column(db.String(200), nullable=False)
    edad = db.Column(db.Integer, nullable=True)

    # Tus formularios lo manejan como FECHA
    dia_ingreso = db.Column(db.Date, nullable=True)

    egresado = db.Column(db.Boolean, default=False, nullable=False, index=True)

    signos_vitales = db.Column(db.Text, nullable=True)
    diagnosticos = db.Column(db.Text, nullable=True)
    condicion_plan = db.Column(db.Text, nullable=True)
    origen_ingreso = db.Column(db.String(150), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.relationship("User", backref="internamientos_creados", lazy=True)

    guardia = db.relationship("GuardiaEmergencia", backref="internamientos", lazy=True)

    __table_args__ = (
        db.Index("ix_internamiento_fecha_hospital", "fecha", "hospital"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Internamiento {self.fecha} {self.hospital} {self.nombre_paciente}>"

    @property
    def dias_hospitalizado(self):
        """Calcula días desde fecha ingreso real hasta hoy."""
        if not self.fecha:
            return 0
        hoy = date.today()
        diff = (hoy - self.fecha).days
        return diff + 1 if diff >= 0 else 0


# ==========================================================
# EVENTOS AUTOMÁTICOS PARA fecha_actualizacion
# ==========================================================
@event.listens_for(Internamiento, "before_insert")
def internamiento_before_insert(mapper, connection, target):
    if target.fecha and not target.fecha_actualizacion:
        target.fecha_actualizacion = datetime.combine(target.fecha, datetime.min.time())


@event.listens_for(Internamiento, "before_update")
def internamiento_before_update(mapper, connection, target):
    target.fecha_actualizacion = datetime.utcnow()

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # username indexado y único (80 es seguro para MySQL + utf8mb4)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    # hash de contraseña (255 es suficiente para werkzeug)
    password = db.Column(db.String(255), nullable=False)
    # nombre de hospital en texto (lo usas mucho en filtros/export)
    hospital = db.Column(db.String(200), nullable=True, index=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Opciones MySQL
    __table_args__ = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }

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
        return f"<User {self.username} admin={self.is_admin}>"


class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    # 191 para estar 100% tranquilos con unique+index en MySQL antiguos
    nombre = db.Column(db.String(191), unique=True, nullable=False, index=True)
    activo = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Hospital {self.nombre} activo={self.activo}>"


class EmergencyRecord(db.Model):
    __tablename__ = "emergency_records"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, index=True)
    # Usas hospital como string (no FK) en todo el código
    hospital = db.Column(db.String(200), nullable=False, index=True)

    atenciones = db.Column(db.Integer, default=0, nullable=False)
    ingresos = db.Column(db.Integer, default=0, nullable=False)
    alta_voluntario = db.Column(db.Integer, default=0, nullable=False)
    traslados = db.Column(db.Integer, default=0, nullable=False)

    motivo_traslado = db.Column(db.String(255))
    hospital_referencia = db.Column(db.String(255))

    defunciones = db.Column(db.Integer, default=0, nullable=False)
    eventualidades = db.Column(db.Text)

    __table_args__ = (
        # índice útil para listados/consultas por fecha+hospital
        db.Index("ix_emergency_fecha_hospital", "fecha", "hospital"),
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )

    def to_row(self):
        """Fila para exportar a CSV/Excel (coincide con tus encabezados)."""
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

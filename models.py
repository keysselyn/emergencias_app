from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class Hospital(db.Model):
    __tablename__ = 'hospitals'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), unique=True, nullable=False, index=True)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # 'admin' | 'user'
    hospital = db.Column(db.String(160), nullable=False)  # guardamos nombre simple

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role.lower() == 'admin'

    # Flask-Login props
    @property
    def is_authenticated(self): return True
    @property
    def is_active(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return str(self.id)

class EmergencyRecord(db.Model):
    __tablename__ = 'emergency_records'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    hospital = db.Column(db.String(160), nullable=False)  # nombre del hospital
    atenciones = db.Column(db.Integer, nullable=False, default=0)
    ingresos = db.Column(db.Integer, nullable=False, default=0)
    alta_voluntario = db.Column(db.Integer, nullable=False, default=0)
    traslados = db.Column(db.Integer, nullable=False, default=0)
    motivo_traslado = db.Column(db.String(255), nullable=True)
    hospital_referencia = db.Column(db.String(160), nullable=True)
    defunciones = db.Column(db.Integer, nullable=False, default=0)
    eventualidades = db.Column(db.Text, nullable=True)

    def to_row(self):
        return [
            self.fecha.isoformat(),
            self.hospital,
            self.atenciones,
            self.ingresos,
            self.alta_voluntario,
            self.traslados,
            self.motivo_traslado or '',
            self.hospital_referencia or '',
            self.defunciones,
            (self.eventualidades or '').replace('\n', ' ')
        ]

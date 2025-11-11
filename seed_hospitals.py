from app import app
from models import db, Hospital

NOMBRES = [
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

if __name__ == '__main__':
    with app.app_context():
        for n in NOMBRES:
            if not Hospital.query.filter_by(nombre=n).first():
                db.session.add(Hospital(nombre=n, activo=True))
        db.session.commit()
        print("✅ Hospitales iniciales sembrados.")

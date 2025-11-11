from models import db, User
from app import app

def create_user(username, password, hospital, role='user'):
    with app.app_context():
        if User.query.filter_by(username=username).first():
            print(f'⚠️ Ya existe el usuario: {username}')
            return
        u = User(username=username, role=role, hospital=hospital)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        print(f'✅ Usuario creado: {username} ({role}) – Hospital: {hospital}')

if __name__ == '__main__':
    # Ejemplos:
    # Admin:
    #   python manage_users.py
    # y luego modifica aquí las líneas de ejemplo:
    create_user('admin', 'admin123', 'TODOS', role='admin')
    create_user('hmlc_user', 'clave123', 'Hospital Municipal Los Cacaos', role='user')

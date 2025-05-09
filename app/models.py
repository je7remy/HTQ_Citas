from . import db
from flask_login import UserMixin

class Usuario(UserMixin, db.Model):                           #modelos provicionales hasta que se creen las verdaderas tablas para el proyecto
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    rol = db.Column(db.String(50))  # 'secretaria' o 'medico'
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))

class Paciente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    cedula = db.Column(db.String(15))
    telefono = db.Column(db.String(20))

class Cita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('paciente.id'))
    medico_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    fecha = db.Column(db.Date)
    hora = db.Column(db.Time)
    estado = db.Column(db.String(20))  # "pendiente", "cancelada", "completada"
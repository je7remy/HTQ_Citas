from . import db
from flask_login import UserMixin
from datetime import datetime

# Modelo de usuarios del sistema (secretarias y médicos)
class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    
    id_usuario = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    contrasena_hash = db.Column(db.String(100), nullable=False)
    rol = db.Column(db.String(20), nullable=False)  # 'medico' o 'secretaria' administrador?



    
    activo = db.Column(db.Boolean, default=True)

    # Relaciones
    medico = db.relationship('Medico', backref='usuario', uselist=False)
    reportes = db.relationship('LogReporte', backref='generador')

# Modelo de pacientes registrados en el sistema
class Paciente(db.Model):
    __tablename__ = 'pacientes'

    id_paciente = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(100), nullable=False)
    cedula = db.Column(db.String(15), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    fecha_nacimiento = db.Column(db.Date)
    sexo = db.Column(db.String(1))  # 'M' o 'F'
    direccion = db.Column(db.Text)

    # Relación con citas
    citas = db.relationship('Cita', backref='paciente', lazy=True)

# Modelo de médicos, enlazado a un usuario
class Medico(db.Model):
    __tablename__ = 'medicos'

    id_medico = db.Column(db.Integer, primary_key=True)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    especialidad = db.Column(db.String(100), nullable=False)

    # Relaciones
    citas = db.relationship('Cita', backref='medico', lazy=True)
    disponibilidades = db.relationship('DisponibilidadMedica', backref='medico', lazy=True)

# Modelo de disponibilidad médica por día de la semana
class DisponibilidadMedica(db.Model):
    __tablename__ = 'disponibilidad_medica'

    id_disponibilidad = db.Column(db.Integer, primary_key=True)
    id_medico = db.Column(db.Integer, db.ForeignKey('medicos.id_medico'), nullable=False)
    dia_semana = db.Column(db.String(15), nullable=False)  # lunes, martes, etc.
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)

# Modelo de citas médicas entre pacientes y médicos
class Cita(db.Model):
    __tablename__ = 'citas'

    id_cita = db.Column(db.Integer, primary_key=True)
    id_paciente = db.Column(db.Integer, db.ForeignKey('pacientes.id_paciente'), nullable=False)
    id_medico = db.Column(db.Integer, db.ForeignKey('medicos.id_medico'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    estado = db.Column(db.String(20), default='programada')  # programada, cancelada, atendida
    notas_secretaria = db.Column(db.Text)

    # Relación con nota médica
    nota_medica = db.relationship('NotaMedica', backref='cita', uselist=False)

# Modelo de notas médicas registradas por el médico luego de la cita
class NotaMedica(db.Model):
    __tablename__ = 'notas_medicas'

    id_nota = db.Column(db.Integer, primary_key=True)
    id_cita = db.Column(db.Integer, db.ForeignKey('citas.id_cita'), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

# Modelo de historial de reportes generados por secretarias
class LogReporte(db.Model):
    __tablename__ = 'log_reportes'

    id_reporte = db.Column(db.Integer, primary_key=True)
    tipo_reporte = db.Column(db.String(50), nullable=False)
    fecha_generacion = db.Column(db.DateTime, default=datetime.utcnow)
    usuario_generador = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'))

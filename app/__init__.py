from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'clave-secreta'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hospital.db' #url provicional hasta que cree la verdadera bd
    
    db.init_app(app)
    login_manager.init_app(app)

    # Importar blueprints
    from .routes.auth import auth_bp
    from .routes.citas import citas_bp
    from .routes.dashboard import dashboard_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(citas_bp)
    app.register_blueprint(dashboard_bp)

    return app
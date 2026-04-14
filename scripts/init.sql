-- =====================================================================
-- SGCM — Script DDL inicial
-- Base de datos: sgcm_db   |   PostgreSQL 15
-- Fuente: Anexo D de la tesis (HTQPJB, La Vega, R.D.)
-- =====================================================================

CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100)  NOT NULL,
    email           VARCHAR(100)  UNIQUE NOT NULL,
    password_hash   VARCHAR(255)  NOT NULL,
    rol             VARCHAR(20)   NOT NULL CHECK (rol IN ('secretaria','medico','admin')),
    activo          BOOLEAN       DEFAULT TRUE,
    fecha_creacion  TIMESTAMP     DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pacientes (
    id                SERIAL PRIMARY KEY,
    cedula            VARCHAR(13)  UNIQUE NOT NULL,
    nombre            VARCHAR(100) NOT NULL,
    apellidos         VARCHAR(100) NOT NULL,
    fecha_nacimiento  DATE,
    telefono          VARCHAR(15)  NOT NULL,
    direccion         TEXT,
    fecha_registro    TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS medicos (
    id            SERIAL PRIMARY KEY,
    id_usuario    INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    nombre        VARCHAR(100) NOT NULL,
    especialidad  VARCHAR(50)  NOT NULL,
    telefono      VARCHAR(15),
    activo        BOOLEAN      DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS horarios (
    id           SERIAL PRIMARY KEY,
    id_medico    INTEGER REFERENCES medicos(id) ON DELETE CASCADE,
    dia_semana   SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
    hora_inicio  TIME     NOT NULL,
    hora_fin     TIME     NOT NULL,
    activo       BOOLEAN  DEFAULT TRUE,
    CHECK (hora_inicio < hora_fin)
);

CREATE TABLE IF NOT EXISTS citas (
    id              SERIAL PRIMARY KEY,
    id_paciente     INTEGER REFERENCES pacientes(id) NOT NULL,
    id_medico       INTEGER REFERENCES medicos(id)   NOT NULL,
    fecha           DATE     NOT NULL,
    hora            TIME     NOT NULL,
    estado          VARCHAR(20) DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente','atendida','cancelada')),
    motivo          TEXT,
    id_secretaria   INTEGER REFERENCES usuarios(id) NOT NULL,
    fecha_registro  TIMESTAMP DEFAULT NOW()
);

-- Restricción central anti-duplicados (Anexo D de la tesis).
-- Es un índice ÚNICO PARCIAL: ignora citas canceladas, de modo que
-- al cancelar (CU-08) o reprogramar (CU-07) el horario queda liberado,
-- como exige el caso de uso P2.4 — sin perder la unicidad para citas activas.
CREATE UNIQUE INDEX IF NOT EXISTS uq_citas_medico_fecha_hora
    ON citas (id_medico, fecha, hora)
    WHERE estado <> 'cancelada';

CREATE INDEX IF NOT EXISTS idx_citas_fecha     ON citas(fecha);
CREATE INDEX IF NOT EXISTS idx_citas_id_medico ON citas(id_medico);

CREATE TABLE IF NOT EXISTS consultas (
    id              SERIAL PRIMARY KEY,
    id_cita         INTEGER REFERENCES citas(id) UNIQUE NOT NULL,
    observaciones   TEXT NOT NULL,
    fecha_registro  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditoria (
    id              SERIAL PRIMARY KEY,
    id_usuario      INTEGER REFERENCES usuarios(id),
    accion          VARCHAR(20) NOT NULL,
    tabla_afectada  VARCHAR(50) NOT NULL,
    id_registro     INTEGER,
    detalle         TEXT,
    fecha_hora      TIMESTAMP DEFAULT NOW(),
    ip_origen       VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_hora);

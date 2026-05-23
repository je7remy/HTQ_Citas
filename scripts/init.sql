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
    fecha_creacion  TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pacientes (
    id                SERIAL PRIMARY KEY,
    cedula            VARCHAR(13)  UNIQUE NOT NULL,
    nombre            VARCHAR(100) NOT NULL,
    apellidos         VARCHAR(100) NOT NULL,
    sexo              VARCHAR(20)  NOT NULL
                       CHECK (sexo IN ('masculino','femenino','otro','prefiero no decir')),
    fecha_nacimiento  DATE         NOT NULL,
    telefono          VARCHAR(15)  NOT NULL,
    direccion         TEXT,
    fecha_registro    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS medicos (
    id                          SERIAL PRIMARY KEY,
    id_usuario                  INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    nombre                      VARCHAR(100) NOT NULL,
    especialidad                VARCHAR(50)  NOT NULL,
    especialidad_secundaria_1   VARCHAR(50),
    especialidad_secundaria_2   VARCHAR(50),
    telefono                    VARCHAR(15),
    activo                      BOOLEAN      DEFAULT TRUE
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
    fecha_registro  TIMESTAMPTZ DEFAULT NOW()
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
    id                        SERIAL PRIMARY KEY,
    id_cita                   INTEGER REFERENCES citas(id) UNIQUE NOT NULL,
    motivo_consulta           TEXT,
    examen_fisico             TEXT,
    condicion_principal       TEXT NOT NULL,
    condiciones_secundarias   TEXT,
    tratamiento               TEXT,
    observaciones             TEXT,
    fecha_registro            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditoria (
    id              SERIAL PRIMARY KEY,
    id_usuario      INTEGER REFERENCES usuarios(id),
    nombre_usuario  VARCHAR(100) NOT NULL,
    accion          VARCHAR(20) NOT NULL,
    tabla_afectada  VARCHAR(50) NOT NULL,
    id_registro     INTEGER,
    detalle         TEXT,
    fecha_hora      TIMESTAMPTZ DEFAULT NOW(),
    ip_origen       VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria(fecha_hora);

-- Bitácora de respaldos generados desde el panel admin (/respaldos.html).
CREATE TABLE IF NOT EXISTS respaldos (
    id                  SERIAL PRIMARY KEY,
    id_usuario          INTEGER REFERENCES usuarios(id),
    nombre_usuario      VARCHAR(100) NOT NULL,
    tipo                VARCHAR(20)  NOT NULL
                         CHECK (tipo IN ('local','externo','nube')),
    proveedor_nube      VARCHAR(20)
                         CHECK (proveedor_nube IS NULL
                                OR proveedor_nube IN ('s3','gcs','azure')),
    ruta_origen         TEXT         NOT NULL,
    ruta_destino        TEXT         NOT NULL,
    tamano_bytes        BIGINT       NOT NULL,
    hash_sha256         VARCHAR(64)  NOT NULL,
    estado              VARCHAR(20)  NOT NULL
                         CHECK (estado IN ('en_progreso','completado','fallido')),
    mensaje_error       TEXT,
    fecha_inicio        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fecha_fin           TIMESTAMPTZ,
    duracion_segundos   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_respaldos_fecha_inicio ON respaldos(fecha_inicio);
CREATE INDEX IF NOT EXISTS idx_respaldos_tipo_estado  ON respaldos(tipo, estado);

-- Catalogo administrable de especialidades del HTQPJB (CU-17).
-- El campo `medicos.especialidad` sigue siendo VARCHAR sin FK; la validacion
-- contra este catalogo vive en el backend para no introducir migraciones de
-- datos sobre tablas con FKs existentes.
CREATE TABLE IF NOT EXISTS especialidades (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(50)  UNIQUE NOT NULL,
    descripcion     VARCHAR(200),
    activa          BOOLEAN      NOT NULL DEFAULT TRUE,
    fecha_creacion  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_especialidades_activa ON especialidades(activa);

-- Siembra inicial: 18 especialidades oficiales del hospital.
-- ON CONFLICT DO NOTHING hace el bloque idempotente — si init.sql se vuelve
-- a aplicar (lo cual no deberia ocurrir en condiciones normales porque solo
-- corre en la primera creacion del volumen) no se duplican registros.
INSERT INTO especialidades (nombre, activa) VALUES
    ('Ortopedia y Traumatología', TRUE),
    ('Cirugía General', TRUE),
    ('Cirugía Vascular', TRUE),
    ('Cirugía Torácica', TRUE),
    ('Cirugía Plástica', TRUE),
    ('Cirugía Pediátrica', TRUE),
    ('Cirugía Ginecológica', TRUE),
    ('Neurocirugía', TRUE),
    ('Cirugía Maxilofacial', TRUE),
    ('Anestesiología', TRUE),
    ('Medicina Interna', TRUE),
    ('Urología', TRUE),
    ('Oftalmología', TRUE),
    ('Otorrinolaringología', TRUE),
    ('Medicina Física y Rehabilitación', TRUE),
    ('Radiología y Diagnóstico por Imágenes', TRUE),
    ('Laboratorio Clínico', TRUE),
    ('Emergenciología', TRUE)
ON CONFLICT (nombre) DO NOTHING;

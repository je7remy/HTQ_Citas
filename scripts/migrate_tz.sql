-- =====================================================================
-- SGCM — Migración TIMESTAMP → TIMESTAMPTZ
-- =====================================================================
-- Convierte las columnas de timestamp a "with time zone", asumiendo que
-- los datos previos a la migración están en UTC (que era lo que producía
-- datetime.utcnow() del código viejo). PostgreSQL toma el valor naive
-- como UTC y, al consultar, lo presenta convertido a la zona de sesión
-- (America/Santo_Domingo a partir de este release).
--
-- Idempotente: solo altera columnas que aún no son TIMESTAMPTZ.
-- =====================================================================

DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'usuarios' AND column_name = 'fecha_creacion'
       ) = 'timestamp without time zone' THEN
        ALTER TABLE usuarios
            ALTER COLUMN fecha_creacion TYPE TIMESTAMPTZ
            USING fecha_creacion AT TIME ZONE 'UTC';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'pacientes' AND column_name = 'fecha_registro'
       ) = 'timestamp without time zone' THEN
        ALTER TABLE pacientes
            ALTER COLUMN fecha_registro TYPE TIMESTAMPTZ
            USING fecha_registro AT TIME ZONE 'UTC';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'citas' AND column_name = 'fecha_registro'
       ) = 'timestamp without time zone' THEN
        ALTER TABLE citas
            ALTER COLUMN fecha_registro TYPE TIMESTAMPTZ
            USING fecha_registro AT TIME ZONE 'UTC';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'consultas' AND column_name = 'fecha_registro'
       ) = 'timestamp without time zone' THEN
        ALTER TABLE consultas
            ALTER COLUMN fecha_registro TYPE TIMESTAMPTZ
            USING fecha_registro AT TIME ZONE 'UTC';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'auditoria' AND column_name = 'fecha_hora'
       ) = 'timestamp without time zone' THEN
        ALTER TABLE auditoria
            ALTER COLUMN fecha_hora TYPE TIMESTAMPTZ
            USING fecha_hora AT TIME ZONE 'UTC';
    END IF;
END$$;

-- Verificación: tras correr este script, deberías ver "timestamp with time zone"
-- en las cinco columnas:
--   SELECT table_name, column_name, data_type
--   FROM information_schema.columns
--   WHERE column_name IN ('fecha_creacion','fecha_registro','fecha_hora')
--   ORDER BY table_name, column_name;

# Sistema de Respaldos — SGCM (CU-16)

Este documento describe el sistema de respaldos del **SGCM** (Sistema Web
de Gestión de Citas Médicas) del **Hospital Regional Traumatológico y
Quirúrgico Prof. Juan Bosch (HTQPJB)**.

El sistema permite al **administrador** generar copias de seguridad de la
base de datos PostgreSQL en tres modalidades:

| Modalidad   | Destino                                       | Estado en esta versión       |
|-------------|-----------------------------------------------|------------------------------|
| **Local**   | Disco del propio servidor                     | ✅ Funcional                 |
| **Externo** | Disco USB o ruta UNC montada en el SO         | ✅ Funcional                 |
| **Nube**    | Amazon S3, Google Cloud Storage o Azure Blob  | 🏗️ Andamiaje (no activado)  |

Cada respaldo se registra en la tabla `respaldos` con metadatos completos
(usuario, hash SHA-256, tamaño, duración, estado, mensaje de error si lo
hubiera), de modo que el histórico es auditable.

---

## 0. Despliegue tras añadir CU-16

> ⚠️ **Importante.** El sistema de respaldos introduce una tabla nueva
> (`respaldos`) y depende de que el contenedor `api` tenga `pg_dump`
> disponible. La aplicación NO funcionará correctamente hasta completar
> estos pasos en orden:

```bash
# 1. Reconstruir la imagen api (añade postgresql-client y crea /var/backups/sgcm)
docker compose build --no-cache api

# 2. Levantar los servicios
docker compose up -d

# 3. Aplicar la migración 0006 a la BD existente (sin perder datos)
docker exec sgcm_api alembic upgrade head

# 4. Verificar que las rutas nuevas están registradas
curl -s http://localhost/api/v1/_debug/rutas | grep -E "respaldos|agenda-extendida|usuarios/resumen"

# 5. Verificar que pg_dump está disponible
docker exec sgcm_api pg_dump --version
```

Si prefiere empezar limpio (pierde los datos actuales):

```bash
docker compose down -v   # ← borra el volumen sgcm_pgdata; pierde datos
docker compose up -d --build
```

### Por qué este paso es necesario

`scripts/init.sql` se ejecuta una sola vez: cuando el volumen
`sgcm_pgdata` está vacío. Si su BD ya existe, Postgres ignora el
`init.sql` actualizado. La migración Alembic 0006 (`alembic upgrade
head`) crea la tabla `respaldos` sobre la BD existente sin tocar las
demás tablas.

---

## 1. Flujo interno

```
Admin presiona "Crear respaldo"
        │
        ▼
POST /api/v1/respaldos { tipo, proveedor_nube? }
        │
        ▼
┌─────────────────────────────────────────────┐
│ app/services/backup/manager.crear_respaldo  │
│                                             │
│ 1. pg_dump → /tmp/sgcm_backup_<ts>.sql      │
│ 2. SHA-256 del archivo origen               │
│ 3. estrategia.ejecutar(archivo)             │
│      ├── RespaldoLocal     → /var/backups   │
│      ├── RespaldoExterno   → /mnt/...       │
│      └── RespaldoS3/GCS/Azure (stubs)       │
│ 4. estrategia.verificar_integridad(hash)    │
│ 5. INSERT respaldos (estado completado)     │
│                                             │
│ Si algo falla → estado fallido + mensaje    │
└─────────────────────────────────────────────┘
        │
        ▼
Frontend muestra toast con resultado
```

El patrón **Strategy** se define en `app/services/backup/base.py`:

```python
class BackupStrategy(ABC):
    @abstractmethod
    def ejecutar(self, archivo_sql: Path) -> BackupResultado: ...

    @abstractmethod
    def verificar_integridad(self, hash_origen: str) -> bool: ...
```

Cada modalidad (`local`, `externo`, `nube/s3`, `nube/gcs`, `nube/azure`)
implementa esa interfaz, lo cual permite añadir destinos nuevos sin tocar
el orquestador.

---

## 2. Modalidad Local

**Variable de entorno:** `SGCM_BACKUP_LOCAL_DIR` (por defecto `/var/backups/sgcm`).

1. El proceso `api` (FastAPI) ejecuta `pg_dump` apuntando al servicio `db` de Docker Compose.
2. Se calcula el SHA-256 del archivo `.sql` resultante.
3. El archivo se copia al directorio configurado.
4. Se re-lee el archivo en destino y se comprueba que el hash coincide.
5. Se persiste el registro con `estado = 'completado'`.

> El directorio se crea si no existe. Para producción, monte un volumen
> Docker dedicado:
>
> ```yaml
> # docker-compose.yml (fragmento)
> services:
>   api:
>     volumes:
>       - sgcm_backups:/var/backups/sgcm
> volumes:
>   sgcm_backups:
> ```

---

## 3. Modalidad Externa

**Variable de entorno:** `SGCM_BACKUP_EXTERNAL_DIR` (por defecto `/mnt/backup_externo`).

Permite copiar el `.sql` a un disco USB conectado al servidor o a una
ruta UNC compartida en la red del hospital.

### 3.1 Montar disco USB en Linux

```bash
# Identificar el dispositivo
lsblk

# Crear punto de montaje y montar (asumiendo /dev/sdb1)
sudo mkdir -p /mnt/backup_externo
sudo mount /dev/sdb1 /mnt/backup_externo

# Permisos para el usuario del contenedor (UID 1000 si usa la imagen estándar)
sudo chown -R 1000:1000 /mnt/backup_externo
```

Para montar automáticamente al arranque, agregue a `/etc/fstab`:

```fstab
UUID=xxxx-xxxx  /mnt/backup_externo  ext4  defaults,nofail  0  2
```

> `nofail` evita que el servidor se quede colgado en boot si el disco no está conectado.

### 3.2 Exponer el punto de montaje al contenedor

```yaml
# docker-compose.yml (fragmento)
services:
  api:
    volumes:
      - /mnt/backup_externo:/mnt/backup_externo
```

### 3.3 Comportamiento si el disco está desconectado

El servicio detecta que la ruta padre no existe y deja el registro en
`estado = 'fallido'` con un `mensaje_error` claro:

> *"La ruta padre del destino externo no existe: /mnt/backup_externo.
>  Verifique que el disco USB o el recurso de red esté montado."*

El frontend muestra esta nota en el histórico para que el operador la lea.

---

## 4. Modalidad Nube — Roadmap para activarla

Los tres stubs (`s3.py`, `gcs.py`, `azure.py`) ya cumplen la interfaz
`BackupStrategy`. Para activarlos basta con:

### 4.1 Amazon S3 (`boto3`)

```bash
pip install boto3==1.34.*
```

En `requirements.txt`:

```text
boto3==1.34.*
```

Variables de entorno:

```env
SGCM_BACKUP_S3_BUCKET=sgcm-backups-htqpjb
SGCM_BACKUP_S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

Reemplazar el cuerpo de `RespaldoS3.ejecutar`:

```python
import boto3
s3 = boto3.client("s3", region_name=self.region)
key = f"sgcm/{archivo_sql.name}"
s3.upload_file(str(archivo_sql), self.bucket, key)
# Recuperar tamaño/hash desde S3 vía head_object si se quiere usar ETag
return BackupResultado(
    ruta_destino=f"s3://{self.bucket}/{key}",
    hash_destino=_sha256(archivo_sql),
    tamano_bytes=archivo_sql.stat().st_size,
)
```

### 4.2 Google Cloud Storage (`google-cloud-storage`)

```bash
pip install google-cloud-storage==2.18.*
```

Variables:

```env
SGCM_BACKUP_GCS_BUCKET=sgcm-backups-htqpjb
GOOGLE_APPLICATION_CREDENTIALS=/etc/sgcm/gcp-sa.json
```

Implementación mínima:

```python
from google.cloud import storage
client = storage.Client()
bucket = client.bucket(self.bucket)
blob = bucket.blob(f"sgcm/{archivo_sql.name}")
blob.upload_from_filename(str(archivo_sql))
```

### 4.3 Azure Blob Storage (`azure-storage-blob`)

```bash
pip install azure-storage-blob==12.21.*
```

Variables:

```env
SGCM_BACKUP_AZURE_CONTAINER=sgcm-backups
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...
```

Implementación mínima:

```python
from azure.storage.blob import BlobServiceClient
svc = BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])
blob = svc.get_blob_client(container=self.container, blob=f"sgcm/{archivo_sql.name}")
with archivo_sql.open("rb") as f:
    blob.upload_blob(f, overwrite=True)
```

Hasta que se realicen estos cambios, el botón de **Respaldo en Nube** en
`/respaldos.html` permanece deshabilitado y un POST con `tipo='nube'`
registra el respaldo en estado `fallido` con el mensaje:
*"Respaldo en … aún no implementado. Para activarlo: …"*.

---

## 5. Restaurar desde un respaldo

Los archivos generados son volcados plain-SQL producidos por `pg_dump`,
por lo que la restauración se hace con `psql` (o `pg_restore` si en el
futuro se cambia el formato a custom).

### 5.1 Restaurar al mismo servidor (sustituir contenido)

> ⚠️ **DESTRUCTIVO** — la base actual se reemplaza. Haga primero un
> respaldo local extra como punto de retorno.

```bash
# Desde el host
docker exec -it sgcm_db psql -U sgcm -d postgres -c "DROP DATABASE sgcm_db;"
docker exec -it sgcm_db psql -U sgcm -d postgres -c "CREATE DATABASE sgcm_db;"
docker exec -i sgcm_db psql -U sgcm -d sgcm_db < /var/backups/sgcm/sgcm_backup_20260516_103045.sql
```

### 5.2 Restaurar a una base de prueba (recomendado)

```bash
docker exec -it sgcm_db psql -U sgcm -d postgres -c "CREATE DATABASE sgcm_db_restore_test;"
docker exec -i sgcm_db psql -U sgcm -d sgcm_db_restore_test < sgcm_backup_20260516_103045.sql
```

Luego puede comparar conteos:

```bash
docker exec -it sgcm_db psql -U sgcm -d sgcm_db_restore_test -c "
  SELECT 'usuarios' AS tabla, COUNT(*) FROM usuarios
  UNION ALL SELECT 'pacientes',  COUNT(*) FROM pacientes
  UNION ALL SELECT 'citas',      COUNT(*) FROM citas
  UNION ALL SELECT 'consultas',  COUNT(*) FROM consultas;"
```

### 5.3 Restaurar usando `pg_restore` (formato custom)

Si en el futuro el flujo se cambia a `pg_dump -Fc`, el comando equivalente es:

```bash
docker exec -i sgcm_db pg_restore -U sgcm -d sgcm_db --clean --if-exists < respaldo.dump
```

---

## 6. Verificación de integridad

Todo respaldo pasa por una validación de integridad **antes** de marcarse
como `completado`:

1. Se calcula SHA-256 sobre el `.sql` recién producido por `pg_dump`.
2. La estrategia entrega el archivo a su destino (copia local, copia a
   USB, subida a S3, etc.).
3. Se llama a `estrategia.verificar_integridad(hash_origen)`, que vuelve
   a calcular el hash del archivo en destino (o consulta el ETag/CRC del
   proveedor de nube) y lo compara.

Si los hashes no coinciden, el respaldo queda en `estado = 'fallido'`
con el mensaje *"Verificación de integridad fallida: el hash del archivo
en destino no coincide con el del origen."*

---

## 7. Política de retención recomendada

Para el HTQPJB se sugiere la siguiente política (no automatizada en esta
versión: el administrador debe limpiar manualmente):

| Tipo                       | Retención        | Justificación                         |
|----------------------------|------------------|---------------------------------------|
| Respaldo diario local      | 7 días           | Recuperación inmediata                |
| Respaldo semanal externo   | 4 semanas        | Cobertura de mes en curso             |
| Respaldo mensual externo   | 12 meses         | Histórico anual                       |
| Respaldo anual en nube     | 5 años (mínimo)  | Cumplimiento de archivística médica   |

**Frecuencia operativa sugerida:**
- **Lunes a viernes a las 18:00**: respaldo local automático (puede
  programarse con `cron` invocando un script que llame al endpoint con
  un token JWT de admin).
- **Sábados a las 20:00**: respaldo externo (USB rotativo semanal).
- **Primer domingo de cada mes**: respaldo externo a USB de archivo.
- **Activar nube** cuando se contrate el almacenamiento (S3/GCS/Azure)
  para respaldo fuera del sitio.

### 7.1 Eliminar registros antiguos

El endpoint `DELETE /api/v1/respaldos/{id}` solo elimina la fila de la
bitácora; **el archivo físico se conserva**. Para borrar el archivo:

```bash
# Local (dentro del contenedor api)
docker exec sgcm_api rm /var/backups/sgcm/sgcm_backup_YYYYMMDD_HHMMSS.sql

# Externo
rm /mnt/backup_externo/sgcm_backup_YYYYMMDD_HHMMSS.sql
```

---

## 8. Referencia de la API

| Método | Ruta                                  | Rol      | Descripción                              |
|--------|---------------------------------------|----------|------------------------------------------|
| POST   | `/api/v1/respaldos`                   | admin    | Crear respaldo (local / externo / nube)  |
| GET    | `/api/v1/respaldos`                   | admin    | Listar (filtros: tipo, estado, fechas)   |
| GET    | `/api/v1/respaldos/{id}`              | admin    | Detalle de un respaldo                   |
| DELETE | `/api/v1/respaldos/{id}`              | admin    | Borrar registro (no el archivo)          |
| GET    | `/api/v1/respaldos/{id}/descargar`    | admin    | Descargar el `.sql` (solo tipo `local`)  |

### Cuerpo del POST

```json
{
  "tipo": "local",                  // local | externo | nube
  "proveedor_nube": null            // s3 | gcs | azure (solo si tipo='nube')
}
```

### Respuesta (RespaldoRead)

```json
{
  "id": 7,
  "id_usuario": 1,
  "nombre_usuario": "Admin HTQPJB",
  "tipo": "local",
  "proveedor_nube": null,
  "ruta_origen": "/tmp/sgcm_backup_20260516_103045.sql",
  "ruta_destino": "/var/backups/sgcm/sgcm_backup_20260516_103045.sql",
  "tamano_bytes": 184320,
  "hash_sha256": "5b8c9f...",
  "estado": "completado",
  "mensaje_error": null,
  "fecha_inicio": "2026-05-16T10:30:45-04:00",
  "fecha_fin":    "2026-05-16T10:30:46-04:00",
  "duracion_segundos": 1
}
```

---

## 9. Pruebas

`tests/test_respaldos.py` cubre:

- Generación de archivo `.sql` y cálculo correcto del hash SHA-256.
- Persistencia del registro en la tabla `respaldos`.
- Copia a la ruta externa configurada.
- Fallo limpio cuando el punto de montaje externo no existe.
- `NotImplementedError` con mensaje claro al solicitar `tipo=nube`.
- Estado `fallido` cuando `pg_dump` no se puede ejecutar.
- Detección de mismatch de hash → estado `fallido`.
- RBAC: 403 para `secretaria` y `medico`.
- Descarga de respaldo local (200 con el archivo).
- Descarga rechazada para respaldos externos/nube (400 con la ruta).
- Listado con filtros (`tipo`, `estado`, fechas).
- Eliminación de registro (sin tocar el archivo físico).
- `POST` end-to-end inyectando `pg_dump` simulado.
- Validación 422 cuando `tipo=nube` viene sin `proveedor_nube`.

Para ejecutar:

```bash
# Dentro del contenedor api
docker exec sgcm_api pytest tests/test_respaldos.py -v
```

# Operación sin internet (intranet HTQPJB)

El SGCM está pensado para vivir dentro de la intranet del Hospital Regional
Traumatológico y Quirúrgico Prof. Juan Bosch. La red interna del hospital
puede o no tener salida a internet — el sistema debe verse y funcionar
**idéntico** en ambos casos.

Este documento describe cómo se cumple esa garantía y cómo mantenerla.

---

## 1. Qué se hizo

Originalmente el frontend traía cuatro dependencias por CDN externo:

| Recurso | URL anterior | Versión |
|---|---|---|
| Inter (Google Fonts) | `fonts.googleapis.com` + `fonts.gstatic.com` | v20 — pesos 400/500/600/700 |
| Tailwind CSS | `cdn.tailwindcss.com` | Play CDN 3.4.x |
| Lucide Icons | `unpkg.com/lucide@latest` | 0.469.0 |
| FullCalendar | `cdn.jsdelivr.net/npm/fullcalendar@6.1.15` | 6.1.15 |
| xlsx (SheetJS) | `cdn.jsdelivr.net/npm/xlsx@0.18.5` | 0.18.5 |

Cuando el navegador del usuario no podía resolver esos dominios (caso típico
de un servidor sin internet), la interfaz se cargaba sin estilos, sin
iconos, sin tipografía y el calendario no funcionaba. El backend nunca
estuvo afectado: solo el frontend.

Lo que se hizo:

1. Descargar la versión **exacta** de cada dependencia (sin actualizar).
2. Guardarla bajo `frontend/static/vendor/` (JS/CSS) y `frontend/static/fonts/inter/` (woff2).
3. Reemplazar los `<link>` y `<script>` en los 10 templates HTML por rutas locales.
4. Generar un `inter.css` propio con `@font-face` apuntando a los `.woff2` locales.
5. Ajustar Nginx para servir `static/vendor/` y `static/fonts/` con `Cache-Control: public, max-age=31536000, immutable`.

No se tocó nada de backend, base de datos ni lógica de negocio.

---

## 2. Estructura final

```
frontend/static/
├── css/
│   └── sgcm.css                          (hoja propia, no es vendor)
├── js/
│   └── app.js                            (utilitarios SGCM)
├── vendor/
│   ├── tailwind/
│   │   └── tailwind.min.js               # Tailwind Play CDN 3.4.16
│   ├── lucide/
│   │   └── lucide.min.js                 # Lucide 0.469.0
│   ├── fullcalendar/
│   │   ├── fullcalendar.min.js           # FullCalendar 6.1.15 (bundle global, CSS embebido)
│   │   └── locales-es.min.js             # locale es de @fullcalendar/core 6.1.15
│   └── xlsx/
│       └── xlsx.full.min.js              # SheetJS 0.18.5
└── fonts/
    └── inter/
        ├── inter.css                     # @font-face local
        ├── inter-latin.woff2             # Inter v20 — subset latin (variable font, 4 pesos)
        └── inter-latin-ext.woff2         # Inter v20 — subset latin-ext
```

**Nota sobre FullCalendar 6.x:** la versión 6 inyecta el CSS desde el propio
bundle JS, por eso no existe un `fullcalendar.min.css` separado. La referencia
al CSS que estaba en el HTML original (`index.global.min.css`) en realidad
devolvía 404 en jsdelivr; era un remanente del API de FullCalendar 5.

**Nota sobre la fuente Inter:** Google Fonts sirve un `.woff2` único por
subset (latin, latin-ext, etc.) que en realidad es una **variable font** que
cubre todos los pesos. Por eso bastan dos archivos (~130 KB en total) para
los 4 pesos declarados (400/500/600/700).

---

## 3. Bloque de headers en cada HTML

Los 10 templates de `frontend/templates/` cargan vendor y fuente así:

```html
<link rel="stylesheet" href="/static/fonts/inter/inter.css">
<script src="/static/vendor/tailwind/tailwind.min.js"></script>
<script src="/static/vendor/lucide/lucide.min.js"></script>
```

`calendar.html` añade:

```html
<script src="/static/vendor/fullcalendar/fullcalendar.min.js"></script>
<script src="/static/vendor/fullcalendar/locales-es.min.js"></script>
```

`reportes-usuarios.html` añade:

```html
<script src="/static/vendor/xlsx/xlsx.full.min.js"></script>
```

---

## 4. Nginx (`nginx/default.conf`)

Dos bloques `location` dedicados con cache inmutable de 1 año:

```nginx
location /static/vendor/ {
    alias /usr/share/nginx/html/static/vendor/;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
}

location /static/fonts/ {
    alias /usr/share/nginx/html/static/fonts/;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header Access-Control-Allow-Origin "*";
}
```

Los tipos MIME (`text/css`, `application/javascript`, `font/woff2`) ya vienen
incluidos en `/etc/nginx/mime.types` de la imagen `nginx:1.27-alpine`.

---

## 5. Verificación offline

Pasos para confirmar que el sistema funciona sin internet:

1. **Levantar la pila:**
   ```bash
   docker compose up -d
   ```

2. **Simular intranet sin salida.** Cualquiera de estas tres opciones:
   - Desconectar físicamente el cable / Wi-Fi de la máquina.
   - En el navegador → DevTools → pestaña Network → marcar **Offline** (esto
     fuerza fallos a cualquier dominio externo, pero deja pasar el host local).
   - Bloquear salida con firewall:
     ```bash
     # Linux ejemplo (bloquea todo egress excepto loopback y red local)
     sudo iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
     sudo iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT
     sudo iptables -A OUTPUT -j REJECT
     ```

3. **Abrir el sistema** en `http://localhost/` y validar:
   - Login se ve con estilo correcto y fuente Inter.
   - Pacientes / Médicos / Usuarios cargan tablas y modales.
   - Calendario de citas muestra eventos con vista mensual.
   - Iconos Lucide aparecen en sidebar y botones.
   - Reportes administrativos descargan PDF y Excel.
   - Agenda del día funciona.
   - Respaldos: botón "Crear respaldo local" funciona.

4. **Confirmar cero peticiones externas:** en DevTools → Network, filtrar por
   "third-party" o agrupar por dominio. Todas las URLs deben empezar con
   el host del propio servidor (ej. `localhost`, `192.168.x.x`, etc.).

---

## 6. Actualizar una dependencia en el futuro

Si en algún momento conviene actualizar (por ej. parche de seguridad en
Lucide), el procedimiento es:

```powershell
# Ejemplo: actualizar Lucide a la versión X.Y.Z
$ver = '0.500.0'
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://unpkg.com/lucide@$ver/dist/umd/lucide.min.js" `
  -OutFile 'frontend/static/vendor/lucide/lucide.min.js'
```

Luego:

1. Probar en una rama: `docker compose up -d --build nginx`.
2. Validar visualmente las pantallas afectadas.
3. Documentar la nueva versión en este archivo.
4. Commit dominicanizado, por ejemplo: `chore: subo lucide a 0.500.0, todo se ve bien`.

Las versiones pinneadas actualmente (al 2026-05-17) son:

| Dependencia | Versión |
|---|---|
| Tailwind Play CDN | 3.4.16 |
| Lucide | 0.469.0 |
| FullCalendar | 6.1.15 |
| xlsx (SheetJS) | 0.18.5 |
| Inter | v20 |

---

## 7. Consideraciones

- **Tamaño del repo:** los vendors suman ~2 MB. No es trivial pero tampoco
  es problema para un repo institucional. Si en el futuro se quiere
  reducir, se puede compilar Tailwind a CSS estático (purge de las clases
  que de verdad se usan) en lugar de embarcar el JIT runtime — la
  diferencia sería de ~440 KB a ~30 KB. **No se hizo en esta iteración**
  porque hubiera implicado un paso de build adicional y el requisito era
  no alterar el comportamiento visual.

- **No CDN, no DNS externo:** ningún HTML del proyecto hace petición a
  `fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.tailwindcss.com`,
  `unpkg.com` ni `cdn.jsdelivr.net`. Confirmado con grep tras los cambios.

- **WeasyPrint** (generación de PDFs) corre en el backend dentro del
  contenedor `api` — no usa internet en runtime.

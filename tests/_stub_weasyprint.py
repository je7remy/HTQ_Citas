"""Stub local para correr la suite en Windows sin GTK (WeasyPrint).

NO se importa desde el código de producción. Solo se invoca manualmente
cuando se ejecuta pytest en una máquina que no tiene la stack GTK
instalada (WeasyPrint requiere libgobject, libpango, libcairo).

En el contenedor de Docker WeasyPrint funciona nativamente; este stub
no se necesita.
"""
import sys
import types

fake = types.ModuleType("weasyprint")
fake.HTML = lambda *a, **k: types.SimpleNamespace(write_pdf=lambda: b"%PDF-stub")
sys.modules.setdefault("weasyprint", fake)

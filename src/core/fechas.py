"""Interpretacion de fechas tal como las muestran las redes sociales.

Las redes casi nunca muestran "2025-08-03 14:32". Muestran cosas como:
    "Hace 5 min", "2 h", "Ayer a las 14:30", "3 de agosto a las 10:15",
    "3 de agosto de 2024", "31 dic 2023", "August 3 at 10:15 AM", "3d", "2w"

Este modulo convierte todo eso a una fecha real de Python.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

MESES = {
    "enero": 1, "ene": 1, "january": 1, "jan": 1,
    "febrero": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6, "june": 6,
    "julio": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "septiembre": 9, "sept": 9, "sep": 9, "setiembre": 9, "september": 9,
    "octubre": 10, "oct": 10, "october": 10,
    "noviembre": 11, "nov": 11, "november": 11,
    "diciembre": 12, "dic": 12, "december": 12, "dec": 12,
}

# "hace 3 horas", "3 h", "3 hrs", "3 hours ago", "3d", "2 semanas"
_UNIDADES = {
    "s": "segundos", "seg": "segundos", "segundo": "segundos",
    "segundos": "segundos", "sec": "segundos", "second": "segundos",
    "seconds": "segundos",
    "m": "minutos", "min": "minutos", "mins": "minutos",
    "minuto": "minutos", "minutos": "minutos", "minute": "minutos",
    "minutes": "minutos",
    "h": "horas", "hr": "horas", "hrs": "horas", "hora": "horas",
    "horas": "horas", "hour": "horas", "hours": "horas",
    "d": "dias", "dia": "dias", "dias": "dias", "día": "dias",
    "días": "dias", "day": "dias", "days": "dias",
    "sem": "semanas", "semana": "semanas", "semanas": "semanas",
    "w": "semanas", "wk": "semanas", "week": "semanas", "weeks": "semanas",
    "mes": "meses", "meses": "meses", "mo": "meses", "month": "meses",
    "months": "meses",
    "a": "anios", "anio": "anios", "año": "anios", "años": "anios",
    "anos": "anios", "y": "anios", "yr": "anios", "year": "anios",
    "years": "anios",
}

_DELTAS = {
    "segundos": lambda n: timedelta(seconds=n),
    "minutos": lambda n: timedelta(minutes=n),
    "horas": lambda n: timedelta(hours=n),
    "dias": lambda n: timedelta(days=n),
    "semanas": lambda n: timedelta(weeks=n),
    "meses": lambda n: timedelta(days=30 * n),
    "anios": lambda n: timedelta(days=365 * n),
}

_RE_RELATIVA = re.compile(
    r"(?:hace\s+)?(\d+)\s*([a-zA-ZáéíóúñÁÉÍÓÚÑ]+)\.?(?:\s+ago)?",
    re.IGNORECASE,
)
_RE_HORA = re.compile(r"(\d{1,2}):(\d{2})\s*(a\.?\s?m\.?|p\.?\s?m\.?|AM|PM)?", re.IGNORECASE)
_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
_RE_DIA_MES = re.compile(
    r"(\d{1,2})\s*(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]{3,12})\.?"
    r"(?:\s*(?:de|,)?\s*(\d{4}))?",
    re.IGNORECASE,
)
_RE_MES_DIA = re.compile(
    r"([a-zA-Z]{3,12})\.?\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?",
    re.IGNORECASE,
)


def _aplicar_hora(base: datetime, texto: str) -> datetime:
    """Si el texto trae una hora ('a las 14:30' / 'at 2:30 PM'), la aplica."""
    m = _RE_HORA.search(texto)
    if not m:
        return base.replace(hour=12, minute=0, second=0, microsecond=0)
    hora, minuto = int(m.group(1)), int(m.group(2))
    meridiano = (m.group(3) or "").lower().replace(".", "").replace(" ", "")
    if meridiano == "pm" and hora < 12:
        hora += 12
    elif meridiano == "am" and hora == 12:
        hora = 0
    hora = min(hora, 23)
    return base.replace(hour=hora, minute=minuto, second=0, microsecond=0)


def interpretar_fecha(texto: str, ahora: datetime | None = None) -> datetime | None:
    """Convierte el texto de fecha de una red social a un datetime.

    Devuelve None si no logra entenderlo.
    """
    if not texto:
        return None
    ahora = ahora or datetime.now()
    t = " ".join(texto.strip().split())
    tl = t.lower()

    # 1) Formato ISO o timestamp legible (lo mas facil)
    m = _RE_ISO.search(t)
    if m:
        anio, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 12
        mm = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(anio, mes, dia, hh, mm)
        except ValueError:
            return None

    # 2) "Ahora mismo" / "justo ahora"
    if any(p in tl for p in ("ahora mismo", "justo ahora", "just now", "hace un momento")):
        return ahora

    # 3) "Ayer" / "Hoy" / "Anteayer"
    if tl.startswith("hoy") or tl.startswith("today"):
        return _aplicar_hora(ahora, t)
    if tl.startswith("ayer") or tl.startswith("yesterday"):
        return _aplicar_hora(ahora - timedelta(days=1), t)
    if tl.startswith("anteayer"):
        return _aplicar_hora(ahora - timedelta(days=2), t)

    # 4) Fechas relativas: "hace 3 h", "5 min", "2 semanas", "3d"
    m = _RE_RELATIVA.match(tl) or _RE_RELATIVA.search(tl)
    if m:
        cantidad = int(m.group(1))
        unidad = _UNIDADES.get(m.group(2).lower().rstrip("."))
        if unidad:
            return ahora - _DELTAS[unidad](cantidad)

    # 5) Formato "3 de agosto de 2024 a las 10:15" o "3 ago"
    m = _RE_DIA_MES.search(tl)
    if m:
        mes = MESES.get(m.group(2).lower().rstrip("."))
        if mes:
            dia = int(m.group(1))
            anio = int(m.group(3)) if m.group(3) else ahora.year
            try:
                base = datetime(anio, mes, dia)
            except ValueError:
                return None
            # Sin año explicito: si la fecha cae en el futuro, era del año pasado
            if not m.group(3) and base > ahora + timedelta(days=1):
                base = base.replace(year=anio - 1)
            return _aplicar_hora(base, t)

    # 6) Formato ingles "August 3, 2024" / "Aug 3 at 10:15 AM"
    m = _RE_MES_DIA.search(tl)
    if m:
        mes = MESES.get(m.group(1).lower().rstrip("."))
        if mes:
            dia = int(m.group(2))
            anio = int(m.group(3)) if m.group(3) else ahora.year
            try:
                base = datetime(anio, mes, dia)
            except ValueError:
                return None
            if not m.group(3) and base > ahora + timedelta(days=1):
                base = base.replace(year=anio - 1)
            return _aplicar_hora(base, t)

    return None


def desde_epoch(valor: int | float | str) -> datetime | None:
    """Convierte un timestamp Unix (segundos) a datetime.

    Facebook incrusta en el HTML campos como "creation_time":1723456789.
    Esa es la fuente de fecha mas fiable que existe.
    """
    try:
        n = int(float(valor))
    except (TypeError, ValueError):
        return None
    # Descartamos valores absurdos (antes de 2004 o mas de 1 año en el futuro)
    if n < 1072915200 or n > (datetime.now().timestamp() + 31_536_000):
        return None
    try:
        return datetime.fromtimestamp(n)
    except (OSError, OverflowError, ValueError):
        return None


def en_rango(fecha: datetime | None, desde: datetime, hasta: datetime) -> bool:
    """True si la fecha cae dentro del rango (ambos extremos incluidos)."""
    if fecha is None:
        return False
    return desde <= fecha <= hasta

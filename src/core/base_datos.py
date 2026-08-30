"""Base de datos local (SQLite).

Guardamos todo en un solo archivo para que:
  - no pierdas lo extraido si cierras la app,
  - no se dupliquen comentarios si repites una extraccion,
  - puedas filtrar y contar rapido.

No necesitas instalar ningun motor de base de datos: SQLite viene con Python.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .modelos import Comentario, Publicacion
from .rutas import RUTA_BD, asegurar_carpetas

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS publicaciones (
    url             TEXT PRIMARY KEY,
    red             TEXT NOT NULL,
    perfil          TEXT,
    fecha           TEXT,
    tipo            TEXT,
    texto           TEXT,
    n_comentarios   INTEGER DEFAULT 0,
    estado          TEXT DEFAULT 'pendiente',
    nota            TEXT,
    actualizado_en  TEXT
);

CREATE TABLE IF NOT EXISTS comentarios (
    id                TEXT PRIMARY KEY,
    publicacion_url   TEXT NOT NULL,
    red               TEXT,
    autor             TEXT,
    texto             TEXT NOT NULL,
    fecha             TEXT,
    es_respuesta      INTEGER DEFAULT 0,
    reacciones        INTEGER DEFAULT 0,
    extraido_en       TEXT
);

CREATE INDEX IF NOT EXISTS idx_com_pub ON comentarios(publicacion_url);
CREATE INDEX IF NOT EXISTS idx_com_red ON comentarios(red);
CREATE INDEX IF NOT EXISTS idx_pub_red ON publicaciones(red);
"""


def _a_texto(f: datetime | None) -> str | None:
    return f.isoformat(timespec="seconds") if f else None


def _a_fecha(t: str | None) -> datetime | None:
    if not t:
        return None
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


class BaseDatos:
    """Envoltorio sencillo sobre SQLite, seguro para usar desde varios hilos."""

    def __init__(self, ruta: Path | None = None):
        asegurar_carpetas()
        self.ruta = Path(ruta) if ruta else RUTA_BD
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.ruta), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._con.executescript(_ESQUEMA)
            self._con.commit()

    # ---------------------------------------------------------------- escribir

    def guardar_publicacion(self, pub: Publicacion) -> None:
        """Inserta o actualiza una publicacion (no duplica: la URL es la clave)."""
        with self._lock:
            self._con.execute(
                """
                INSERT INTO publicaciones
                    (url, red, perfil, fecha, tipo, texto, n_comentarios,
                     estado, nota, actualizado_en)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    red            = excluded.red,
                    perfil         = COALESCE(NULLIF(excluded.perfil,''), publicaciones.perfil),
                    fecha          = COALESCE(excluded.fecha, publicaciones.fecha),
                    tipo           = excluded.tipo,
                    texto          = COALESCE(NULLIF(excluded.texto,''), publicaciones.texto),
                    n_comentarios  = excluded.n_comentarios,
                    estado         = excluded.estado,
                    nota           = excluded.nota,
                    actualizado_en = excluded.actualizado_en
                """,
                (
                    pub.url, pub.red, pub.perfil, _a_texto(pub.fecha), pub.tipo,
                    pub.texto, pub.n_comentarios, pub.estado, pub.nota,
                    _a_texto(datetime.now()),
                ),
            )
            self._con.commit()

    def guardar_comentarios(self, comentarios: list[Comentario]) -> int:
        """Guarda una lista de comentarios. Devuelve cuantos eran NUEVOS.

        Si un comentario ya existia (mismo autor, mismo texto, misma
        publicacion) simplemente se ignora: asi puedes re-extraer sin miedo.
        """
        if not comentarios:
            return 0
        with self._lock:
            antes = self._con.execute("SELECT COUNT(*) FROM comentarios").fetchone()[0]
            self._con.executemany(
                """
                INSERT OR IGNORE INTO comentarios
                    (id, publicacion_url, red, autor, texto, fecha,
                     es_respuesta, reacciones, extraido_en)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        c.id, c.publicacion_url, c.red, c.autor, c.texto,
                        _a_texto(c.fecha), int(c.es_respuesta), c.reacciones,
                        _a_texto(c.extraido_en),
                    )
                    for c in comentarios
                ],
            )
            self._con.commit()
            despues = self._con.execute("SELECT COUNT(*) FROM comentarios").fetchone()[0]
        return despues - antes

    def recalcular_conteos(self) -> None:
        """Actualiza el contador de comentarios de cada publicacion."""
        with self._lock:
            self._con.execute(
                """
                UPDATE publicaciones SET n_comentarios = (
                    SELECT COUNT(*) FROM comentarios c
                    WHERE c.publicacion_url = publicaciones.url
                )
                """
            )
            self._con.commit()

    # ------------------------------------------------------------------- leer

    def publicaciones(self, red: str | None = None) -> list[Publicacion]:
        sql = "SELECT * FROM publicaciones"
        params: list = []
        if red:
            sql += " WHERE red = ?"
            params.append(red)
        # (fecha IS NULL) primero manda las publicaciones sin fecha al final;
        # es equivalente a "NULLS LAST" pero funciona en cualquier SQLite.
        sql += " ORDER BY (fecha IS NULL), fecha DESC"
        with self._lock:
            filas = self._con.execute(sql, params).fetchall()
        return [
            Publicacion(
                url=f["url"], red=f["red"], perfil=f["perfil"] or "",
                fecha=_a_fecha(f["fecha"]), tipo=f["tipo"] or "publicacion",
                texto=f["texto"] or "", n_comentarios=f["n_comentarios"] or 0,
                estado=f["estado"] or "pendiente", nota=f["nota"] or "",
            )
            for f in filas
        ]

    def urls_con_comentarios(self) -> list[tuple[str, int]]:
        """Lista de (url, cantidad) solo de publicaciones que SI tienen comentarios."""
        with self._lock:
            filas = self._con.execute(
                """
                SELECT publicacion_url, COUNT(*) AS n
                FROM comentarios GROUP BY publicacion_url ORDER BY n DESC
                """
            ).fetchall()
        return [(f["publicacion_url"], f["n"]) for f in filas]

    def comentarios(
        self,
        url: str | None = None,
        red: str | None = None,
        busqueda: str = "",
        autor: str = "",
        solo_respuestas: bool | None = None,
    ) -> list[dict]:
        """Devuelve comentarios aplicando los filtros que le pases.

        Cada resultado incluye tambien la fecha y el tipo de la publicacion,
        para que la tabla de resultados lo pueda mostrar todo junto.
        """
        sql = """
            SELECT c.*, p.fecha AS fecha_publicacion, p.tipo AS tipo_publicacion,
                   p.texto AS texto_publicacion, p.perfil AS perfil
            FROM comentarios c
            LEFT JOIN publicaciones p ON p.url = c.publicacion_url
            WHERE 1=1
        """
        params: list = []
        if url:
            sql += " AND c.publicacion_url = ?"
            params.append(url)
        if red:
            sql += " AND c.red = ?"
            params.append(red)
        if busqueda:
            sql += " AND c.texto LIKE ?"
            params.append(f"%{busqueda}%")
        if autor:
            sql += " AND c.autor LIKE ?"
            params.append(f"%{autor}%")
        if solo_respuestas is not None:
            sql += " AND c.es_respuesta = ?"
            params.append(int(solo_respuestas))
        sql += " ORDER BY (p.fecha IS NULL), p.fecha DESC, c.publicacion_url, c.fecha ASC"

        with self._lock:
            filas = self._con.execute(sql, params).fetchall()
        return [dict(f) for f in filas]

    def estadisticas(self, red: str | None = None) -> dict:
        """Numeros para el panel de resumen."""
        cond = " WHERE red = ?" if red else ""
        p = [red] if red else []
        with self._lock:
            total_pub = self._con.execute(
                f"SELECT COUNT(*) FROM publicaciones{cond}", p
            ).fetchone()[0]
            pub_con_com = self._con.execute(
                f"""SELECT COUNT(DISTINCT publicacion_url) FROM comentarios{cond}""", p
            ).fetchone()[0]
            total_com = self._con.execute(
                f"SELECT COUNT(*) FROM comentarios{cond}", p
            ).fetchone()[0]
            autores = self._con.execute(
                f"SELECT COUNT(DISTINCT autor) FROM comentarios{cond}", p
            ).fetchone()[0]
            respuestas = self._con.execute(
                f"SELECT COUNT(*) FROM comentarios{cond}"
                + (" AND" if cond else " WHERE") + " es_respuesta = 1", p
            ).fetchone()[0]
        return {
            "publicaciones_totales": total_pub,
            "publicaciones_con_comentarios": pub_con_com,
            "comentarios_totales": total_com,
            "autores_unicos": autores,
            "respuestas": respuestas,
        }

    def top_autores(self, limite: int = 15, red: str | None = None) -> list[tuple[str, int]]:
        cond = " WHERE red = ?" if red else ""
        p = [red] if red else []
        with self._lock:
            filas = self._con.execute(
                f"""SELECT autor, COUNT(*) n FROM comentarios{cond}
                    GROUP BY autor ORDER BY n DESC LIMIT ?""",
                (*p, limite),
            ).fetchall()
        return [(f["autor"], f["n"]) for f in filas]

    # ------------------------------------------------------------------ borrar

    def borrar_todo(self) -> None:
        with self._lock:
            self._con.execute("DELETE FROM comentarios")
            self._con.execute("DELETE FROM publicaciones")
            self._con.commit()

    def borrar_red(self, red: str) -> None:
        with self._lock:
            self._con.execute("DELETE FROM comentarios WHERE red = ?", (red,))
            self._con.execute("DELETE FROM publicaciones WHERE red = ?", (red,))
            self._con.commit()

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()

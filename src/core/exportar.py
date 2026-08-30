"""Exportacion de resultados a CSV y Excel.

Exporta exactamente lo que estas viendo en la tabla (respeta los filtros),
o todo, segun elijas en la interfaz.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

# Nombres de columna bonitos para el archivo final
COLUMNAS = {
    "red": "Red social",
    "publicacion_url": "URL de la publicacion",
    "fecha_publicacion": "Fecha de la publicacion",
    "tipo_publicacion": "Tipo de publicacion",
    "texto_publicacion": "Texto de la publicacion",
    "autor": "Autor del comentario",
    "fecha": "Fecha del comentario",
    "es_respuesta": "Es respuesta",
    "reacciones": "Reacciones",
    "texto": "Comentario",
}

ORDEN = [
    "red", "publicacion_url", "fecha_publicacion", "tipo_publicacion",
    "texto_publicacion", "autor", "fecha", "es_respuesta", "reacciones", "texto",
]


def _a_dataframe(filas: list[dict]) -> pd.DataFrame:
    if not filas:
        return pd.DataFrame(columns=[COLUMNAS[c] for c in ORDEN])
    df = pd.DataFrame(filas)
    for col in ORDEN:
        if col not in df.columns:
            df[col] = ""
    df = df[ORDEN].copy()
    df["es_respuesta"] = df["es_respuesta"].map(lambda v: "Si" if v else "No")
    # Recortamos el texto de la publicacion: solo sirve para reconocerla
    df["texto_publicacion"] = (
        df["texto_publicacion"].fillna("").astype(str).str.slice(0, 200)
    )
    df = df.rename(columns=COLUMNAS)
    return df


def exportar_csv(filas: list[dict], destino: str | Path) -> Path:
    """Guarda un CSV que Excel en español abre bien (separador ';' y BOM)."""
    destino = Path(destino)
    df = _a_dataframe(filas)
    # utf-8-sig = UTF-8 con BOM -> Excel respeta acentos y emojis
    df.to_csv(destino, index=False, sep=";", encoding="utf-8-sig")
    return destino


def exportar_excel(filas: list[dict], destino: str | Path) -> Path:
    """Guarda un .xlsx con tres hojas: Comentarios, Resumen por publicacion y Top autores."""
    destino = Path(destino)
    df = _a_dataframe(filas)

    # Hoja 2: cuantos comentarios tiene cada publicacion
    if filas:
        resumen = (
            df.groupby(
                ["URL de la publicacion", "Fecha de la publicacion", "Tipo de publicacion"],
                dropna=False,
            )
            .size()
            .reset_index(name="Comentarios")
            .sort_values("Comentarios", ascending=False)
        )
        conteo_autores = Counter(df["Autor del comentario"])
        autores = pd.DataFrame(
            conteo_autores.most_common(100), columns=["Autor", "Comentarios"]
        )
    else:
        resumen = pd.DataFrame(columns=["URL de la publicacion", "Comentarios"])
        autores = pd.DataFrame(columns=["Autor", "Comentarios"])

    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Comentarios", index=False)
        resumen.to_excel(writer, sheet_name="Resumen por publicacion", index=False)
        autores.to_excel(writer, sheet_name="Top autores", index=False)

        # Ajustamos el ancho de las columnas para que se lea comodo
        for nombre_hoja, tabla in (
            ("Comentarios", df),
            ("Resumen por publicacion", resumen),
            ("Top autores", autores),
        ):
            hoja = writer.sheets[nombre_hoja]
            for i, columna in enumerate(tabla.columns, start=1):
                largos = tabla[columna].astype(str).str.len()
                maximo = int(largos.max()) if len(largos) and pd.notna(largos.max()) else 12
                ancho = max(12, min(60, maximo + 2))
                hoja.column_dimensions[hoja.cell(row=1, column=i).column_letter].width = ancho
            hoja.freeze_panes = "A2"

    return destino

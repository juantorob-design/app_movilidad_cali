"""Editor PDF local para uso personal.

Todos los archivos se procesan en memoria en el equipo local. No usa Drive,
OCR remoto ni servicios externos.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

import streamlit as st
from pypdf import PdfReader, PdfWriter


@dataclass
class PageItem:
    key: str
    source: str
    source_page: int
    page: object
    rotation: int = 0
    include: bool = True


def parse_page_ranges(value: str, total: int) -> list[int]:
    """Parsea expresiones como 1-3,5 y devuelve índices únicos ordenados."""
    selected: list[int] = []
    for fragment in re.split(r"[,;\s]+", value.strip()):
        if not fragment:
            continue
        if "-" in fragment:
            start_text, end_text = fragment.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                start, end = end, start
            values = range(start, end + 1)
        else:
            values = (int(fragment),)
        for number in values:
            if number < 1 or number > total:
                raise ValueError(f"La página {number} no existe. El PDF tiene {total} páginas.")
            if number - 1 not in selected:
                selected.append(number - 1)
    return selected


def read_uploaded_files(files) -> list[PageItem]:
    pages: list[PageItem] = []
    for file_index, uploaded in enumerate(files):
        reader = PdfReader(io.BytesIO(uploaded.getvalue()))
        for page_index, page in enumerate(reader.pages):
            pages.append(
                PageItem(
                    key=f"{file_index}-{page_index}",
                    source=uploaded.name,
                    source_page=page_index + 1,
                    page=page,
                )
            )
    return pages


def build_pdf(pages: list[PageItem]) -> bytes:
    writer = PdfWriter()
    for item in pages:
        if not item.include:
            continue
        page = item.page
        if item.rotation:
            page.rotate(item.rotation)
        writer.add_page(page)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def build_split_zip(pages: list[PageItem], base_name: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(pages, start=1):
            archive.writestr(
                f"{base_name}_pagina_{index:03d}.pdf",
                build_pdf([item]),
            )
    return output.getvalue()


def render_page_editor(pages: list[PageItem]) -> list[PageItem]:
    st.caption("Desmarca las páginas que deseas eliminar. La rotación se aplica al guardar.")
    order_text = st.text_input(
        "Nuevo orden opcional",
        placeholder="Ejemplo: 3, 1, 2, 4",
        help="Usa los números mostrados en la columna Página. Déjalo vacío para conservar el orden.",
    )
    edited: list[PageItem] = []
    for position, item in enumerate(pages, start=1):
        columns = st.columns([0.7, 3.2, 1.2, 1.4])
        include = columns[0].checkbox(
            "Incluir",
            value=item.include,
            key=f"include_{item.key}",
            label_visibility="collapsed",
        )
        columns[1].write(f"**{position}.** {item.source} — página {item.source_page}")
        rotation = columns[2].selectbox(
            "Giro",
            [0, 90, 180, 270],
            index=[0, 90, 180, 270].index(item.rotation),
            key=f"rotation_{item.key}",
        )
        columns[3].caption(f"ID {position}")
        edited.append(
            PageItem(
                key=item.key,
                source=item.source,
                source_page=item.source_page,
                page=item.page,
                rotation=rotation,
                include=include,
            )
        )
    if order_text.strip():
        try:
            requested = parse_page_ranges(order_text, len(edited))
            if len(requested) != len(edited):
                st.warning("El nuevo orden debe incluir cada página exactamente una vez.")
            else:
                edited = [edited[index] for index in requested]
        except ValueError as error:
            st.error(str(error))
    return edited


def main() -> None:
    st.set_page_config(page_title="Editor PDF local", page_icon="📄", layout="wide")
    st.title("Editor PDF local")
    st.caption("Procesamiento local para uso personal. Los archivos no se suben a Internet.")
    files = st.file_uploader(
        "Selecciona uno o varios archivos PDF",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if not files:
        st.info("Carga al menos un PDF para comenzar.")
        return
    try:
        pages = read_uploaded_files(files)
    except (OSError, ValueError) as error:
        st.error(f"No se pudieron abrir los PDFs: {error}")
        return
    if not pages:
        st.warning("Los archivos no contienen páginas.")
        return

    st.success(f"{len(files)} archivo(s), {len(pages)} página(s) cargada(s).")
    edit_tab, extract_tab, split_tab = st.tabs(
        ["Editar y unir", "Extraer páginas", "Dividir PDF"]
    )
    with edit_tab:
        edited = render_page_editor(pages)
        if st.button("Generar PDF editado", type="primary"):
            included = sum(item.include for item in edited)
            if not included:
                st.error("Debes conservar al menos una página.")
            else:
                output = build_pdf(edited)
                st.download_button(
                    "Descargar PDF editado",
                    output,
                    "documento_editado.pdf",
                    "application/pdf",
                )
                st.success(f"PDF generado con {included} página(s).")

    with extract_tab:
        selected_file = st.selectbox("PDF de origen", [file.name for file in files])
        source = next(file for file in files if file.name == selected_file)
        total = len(PdfReader(io.BytesIO(source.getvalue())).pages)
        ranges = st.text_input(
            "Páginas a extraer",
            placeholder="Ejemplo: 1-3, 7, 10-12",
            key="extract_ranges",
        )
        if st.button("Extraer páginas"):
            try:
                indexes = parse_page_ranges(ranges, total)
                source_pages = read_uploaded_files([source])
                output = build_pdf([source_pages[index] for index in indexes])
                st.download_button(
                    "Descargar páginas extraídas",
                    output,
                    f"{selected_file.rsplit('.', 1)[0]}_extraido.pdf",
                    "application/pdf",
                )
            except (ValueError, IndexError) as error:
                st.error(str(error))

    with split_tab:
        split_file = st.selectbox(
            "PDF para dividir",
            [file.name for file in files],
            key="split_file",
        )
        source = next(file for file in files if file.name == split_file)
        source_pages = read_uploaded_files([source])
        mode = st.radio(
            "Modo",
            ["Un archivo por página", "Un archivo por rango"],
            horizontal=True,
        )
        if st.button("Preparar división"):
            if mode == "Un archivo por página":
                output = build_split_zip(
                    source_pages,
                    split_file.rsplit(".", 1)[0],
                )
                st.download_button(
                    "Descargar ZIP con páginas separadas",
                    output,
                    f"{split_file.rsplit('.', 1)[0]}_paginas.zip",
                    "application/zip",
                )
                st.success(f"ZIP generado con {len(source_pages)} archivos PDF.")
            else:
                st.warning(
                    "Para un rango usa la pestaña 'Extraer páginas'; "
                    "conserva el orden y permite descargar el resultado inmediatamente."
                )


if __name__ == "__main__":
    main()

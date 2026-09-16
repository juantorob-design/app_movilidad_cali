# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

datas = collect_data_files("streamlit")
datas += copy_metadata("streamlit")
datas.append(("pdf_editor.py", "."))

hiddenimports = [
    "streamlit",
    "streamlit.web.cli",
    "pypdf",
] + collect_submodules("streamlit")

a = Analysis(
    ["run_pdf_editor.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EditorPDFLocal",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="EditorPDFLocal",
)

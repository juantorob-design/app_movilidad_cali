import multiprocessing
import os
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse


def resolver_ruta(ruta_relativa):
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, ruta_relativa)


def iniciar_servidor_streamlit(app_script, port):
    base_dir = os.path.dirname(os.path.abspath(app_script))
    if base_dir:
        os.chdir(base_dir)

    from streamlit.web import bootstrap
    bootstrap._set_up_signal_handler = lambda *args, **kwargs: None
    import streamlit.web.cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        app_script,
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
        "--browser.gatherUsageStats=false",
        "--browser.serverAddress=127.0.0.1",
        "--global.developmentMode=false",
    ]
    stcli.main()


def esperar_servidor(port=8501, timeout=60):
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            request = urllib.request.Request(
                health_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def crear_aplicacion_qt(url_inicial):
    from PySide6.QtCore import QUrl, Qt, Signal
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QMainWindow,
        QStackedWidget,
        QTabWidget,
        QToolBar,
        QWidget,
        QVBoxLayout,
        QPushButton,
    )
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class PaginaWeb(QWebEnginePage):
        abrir_pestana = Signal(str, str)

        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if is_main_frame and url.scheme() == "sistema" and url.host() == "open":
                parametros = parse_qs(url.query())
                destino = unquote(parametros.get("url", [""])[0])
                titulo = unquote(parametros.get("title", ["Navegador"])[0])
                if destino.startswith(("https://", "http://")):
                    self.abrir_pestana.emit(destino, titulo)
                return False
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    class PaginaSistema(QWebEnginePage):
        abrir_pestana = Signal(str, str)

        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if is_main_frame and url.scheme() == "sistema" and url.host() == "open":
                parametros = parse_qs(url.query())
                destino = unquote(parametros.get("url", [""])[0])
                titulo = unquote(parametros.get("title", ["Navegador"])[0])
                if destino.startswith(("https://", "http://")):
                    self.abrir_pestana.emit(destino, titulo)
                return False
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    class NavegadorPrincipal(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Sistema de Desvinculaciones - Alcaldía de Cali")
            self.resize(1440, 900)
            self.perfil = QWebEngineProfile(
                "SistemaDesvinculaciones",
                self,
            )
            datos_dir = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "SistemaDesvinculaciones",
                "web_profile",
            )
            os.makedirs(datos_dir, exist_ok=True)
            self.perfil.setPersistentStoragePath(datos_dir)
            self.perfil.setCachePath(os.path.join(datos_dir, "cache"))
            self.perfil.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )
            self.perfil.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalStorageEnabled,
                True,
            )
            self.escritorio = self.crear_escritorio()
            self.sistema = self.crear_pagina_sistema()
            self.tabs = QTabWidget()
            self.tabs.setTabsClosable(True)
            self.tabs.setMovable(True)
            self.tabs.tabCloseRequested.connect(self.cerrar_pestana)
            self.contenido = QStackedWidget()
            self.contenido.addWidget(self.escritorio)
            self.contenido.addWidget(self.sistema)
            self.contenido.addWidget(self.tabs)
            self.setCentralWidget(self.contenido)
            self.crear_barra_herramientas()
            self.mostrar_escritorio()

        def crear_escritorio(self):
            escritorio = QWidget()
            escritorio.setStyleSheet(
                "QWidget { background: #0d1322; color: #f8fafc; }"
                "QLabel#title { font-size: 28px; font-weight: 800; }"
                "QLabel#subtitle { color: #38bdf8; font-size: 15px; }"
                "QPushButton { background: #1f3154; border: 1px solid #3a5278;"
                " border-radius: 10px; padding: 14px 24px; color: white; font-size: 14px; }"
                "QPushButton:hover { background: #2c4775; }"
            )
            layout = QVBoxLayout(escritorio)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            titulo = QLabel("ALCALDÍA DE SANTIAGO DE CALI")
            titulo.setObjectName("title")
            subtitulo = QLabel("SISTEMA DE DESVINCULACIONES")
            subtitulo.setObjectName("subtitle")
            boton = QPushButton("Abrir escritorio de trabajo")
            boton.clicked.connect(self.mostrar_sistema)
            layout.addWidget(titulo, alignment=Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(subtitulo, alignment=Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(26)
            layout.addWidget(boton, alignment=Qt.AlignmentFlag.AlignCenter)
            return escritorio

        def crear_pagina_sistema(self):
            pagina = PaginaSistema(self.perfil, self)
            pagina.abrir_pestana.connect(self.agregar_pestana)
            vista = QWebEngineView()
            vista.setPage(pagina)
            vista.setUrl(QUrl(url_inicial))
            return vista

        def crear_barra_herramientas(self):
            barra = QToolBar("Navegación")
            barra.setMovable(False)
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, barra)

            inicio = QAction("Inicio", self)
            inicio.triggered.connect(lambda: self.navegar_inicio())
            barra.addAction(inicio)

            atras = QAction("Atrás", self)
            atras.triggered.connect(
                lambda: self.pagina_actual() and self.pagina_actual().back()
            )
            barra.addAction(atras)

            adelante = QAction("Adelante", self)
            adelante.triggered.connect(
                lambda: self.pagina_actual() and self.pagina_actual().forward()
            )
            barra.addAction(adelante)

            recargar = QAction("Recargar", self)
            recargar.triggered.connect(
                lambda: self.pagina_actual() and self.pagina_actual().reload()
            )
            barra.addAction(recargar)

            nueva = QAction("+ Nueva pestaña", self)
            nueva.triggered.connect(lambda: self.agregar_pestana(url_inicial, "Sistema"))
            barra.addAction(nueva)

            cuenta = QAction("Cuenta Google", self)
            cuenta.triggered.connect(
                lambda: self.agregar_pestana(
                    "https://accounts.google.com/",
                    "Cuenta Google",
                )
            )
            barra.addAction(cuenta)

        def pagina_actual(self):
            widget = self.contenido.currentWidget()
            return widget if isinstance(widget, QWebEngineView) else None

        def navegar_inicio(self):
            self.mostrar_escritorio()

        def mostrar_escritorio(self):
            self.contenido.setCurrentWidget(self.escritorio)

        def mostrar_sistema(self):
            self.contenido.setCurrentWidget(self.sistema)

        def agregar_pestana(self, url, titulo):
            pagina = PaginaWeb(self.perfil, self)
            vista = QWebEngineView()
            vista.setPage(pagina)
            pagina.abrir_pestana.connect(self.agregar_pestana)
            vista.titleChanged.connect(
                lambda nuevo_titulo, vista=vista: self.actualizar_titulo(vista, nuevo_titulo)
            )
            indice = self.tabs.addTab(vista, titulo)
            self.tabs.setCurrentIndex(indice)
            vista.setUrl(QUrl(url))
            self.contenido.setCurrentWidget(self.tabs)

        def actualizar_titulo(self, vista, titulo):
            indice = self.tabs.indexOf(vista)
            if indice >= 0 and titulo:
                self.tabs.setTabText(indice, titulo[:32])

        def cerrar_pestana(self, indice):
            if self.tabs.count() > 1:
                widget = self.tabs.widget(indice)
                self.tabs.removeTab(indice)
                widget.deleteLater()
            elif self.tabs.count() == 1:
                widget = self.tabs.widget(indice)
                self.tabs.removeTab(indice)
                widget.deleteLater()
                self.mostrar_sistema()

    aplicacion = QApplication.instance() or QApplication(sys.argv)
    aplicacion.setApplicationName("Sistema de Desvinculaciones")
    ventana = NavegadorPrincipal()
    ventana.showMaximized()
    return aplicacion.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    puerto = 8501
    app_script = resolver_ruta("app_6.py")
    hilo = threading.Thread(
        target=iniciar_servidor_streamlit,
        args=(app_script, puerto),
        daemon=True,
    )
    hilo.start()
    if not esperar_servidor(puerto):
        print("Error: el servidor Streamlit no respondió a tiempo.")
        sys.exit(1)
    sys.exit(crear_aplicacion_qt(f"http://127.0.0.1:{puerto}"))

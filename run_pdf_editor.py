import os
import sys

from streamlit.web import cli as stcli


def main() -> None:
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_editor.py")
    sys.argv = ["streamlit", "run", app_path, "--server.headless=true"]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Lightweight launcher for the Company Intelligence Chat app.
Ensures env is present and runs Chainlit.
"""
import os
import sys
from pathlib import Path
import subprocess


def _validate_python_runtime() -> None:
    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        print("ERROR: Unsupported Python runtime for this project.")
        print(f"Current Python: {sys.version.split()[0]}")
        print(f"Current executable: {sys.executable}")
        print("Use Python 3.11 or 3.12, then recreate the project virtual environment.")
        print('Windows example: py -3.12 -m venv .venv')
        sys.exit(1)


def _load_dotenv(root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        print("ERROR: python-dotenv is not installed in the active Python environment.")
        print(f"Current executable: {sys.executable}")
        print("Activate the project virtual environment and run:")
        print("  python -m pip install -r requirements.txt")
        sys.exit(1)

    load_dotenv(root / ".env")


def main():
    _validate_python_runtime()

    root = Path(__file__).parent
    _load_dotenv(root)

    required = [
        "OPENAI_API_KEY", "BASE_URL", "PROJECT_ID", "API_VERSION", "MODEL",
        "PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME", "AZURE_BING_CONNECTION_ID",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print("ERROR: Missing env variables:")
        for k in missing:
            print(f"  - {k}")
        print("Create a .env from env.example and fill these in.")
        sys.exit(1)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}:{env.get('PYTHONPATH','')}"
    env["CHAINLIT_APP_ROOT"] = str(root)
    print("Launching Chainlit at http://localhost:8000")
    subprocess.run([sys.executable, "-m", "chainlit", "run", "chainlit_app/main.py", "--host", "localhost", "--port", "8000"], cwd=root, env=env, check=False)

if __name__ == "__main__":
    main()

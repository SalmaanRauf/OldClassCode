#!/usr/bin/env python3
"""
Lightweight launcher for the Company Intelligence Chat app.
Ensures env is present and runs Chainlit.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import subprocess

def main():
    root = Path(__file__).parent
    load_dotenv(root / ".env")

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
    print("Launching Chainlit at http://localhost:8000")
    subprocess.run([sys.executable, "-m", "chainlit", "run", "chainlit_app/main.py", "--host", "localhost", "--port", "8000"], cwd=root, env=env, check=False)

if __name__ == "__main__":
    main()


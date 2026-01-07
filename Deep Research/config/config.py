import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

def get_database_path():
    """Get the absolute path to the database file."""
    project_root = Path(__file__).parent.parent
    return project_root / "data" / "research.db"

class Config:
    """
    Central application configuration.

    - Holds API keys and endpoints used by the Chainlit app and tools.
    - Centralizes operational knobs (timeouts, limits) to avoid magic numbers
      scattered across the codebase.

    All values can be overridden via environment variables. Defaults are chosen
    for usability and can be tuned without code changes.
    """
    # AI Analysis APIs (Azure AI Foundry/ATLAS)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    BASE_URL = os.getenv("BASE_URL")
    PROJECT_ID = os.getenv("PROJECT_ID")
    API_VERSION = os.getenv("API_VERSION", "2024-02-15-preview")
    MODEL = os.getenv("MODEL", "gpt-4o")

    # Azure AI Foundry Agents for Bing Grounding
    PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
    MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME")
    AZURE_BING_CONNECTION_ID = os.getenv("AZURE_BING_CONNECTION_ID")

    # Deep Research (Azure AI Foundry) configuration
    DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME = os.getenv("DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME")
    BING_CONNECTION_NAME = os.getenv("BING_CONNECTION_NAME")

    # Feature flags
    ENABLE_DEEP_RESEARCH = os.getenv("ENABLE_DEEP_RESEARCH", "false").lower() in ("1", "true", "yes")

    # --- Operational settings (timeouts, limits) ---
    # Timeout for independent GWBS scope fetches (seconds)
    GWBS_SCOPE_TIMEOUT_SECONDS = int(os.getenv("GWBS_SCOPE_TIMEOUT_SECONDS", "45"))
    # Timeout for general research (single GWBS run) (seconds)
    GENERAL_RESEARCH_TIMEOUT_SECONDS = int(os.getenv("GENERAL_RESEARCH_TIMEOUT_SECONDS", "60"))
    # Timeout while waiting for follow-up research (seconds)
    FOLLOWUP_TIMEOUT_SECONDS = int(os.getenv("FOLLOWUP_TIMEOUT_SECONDS", "90"))

    @classmethod
    def validate(cls):
        """Lightweight validation and visibility into configuration state.

        Notes:
        - We only warn on missing keys to keep local/dev setups flexible.
        - Sensitive values are not printed.
        """
        required_keys = [
            "OPENAI_API_KEY", "BASE_URL", "PROJECT_ID", "API_VERSION", "MODEL",
            "PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME", "AZURE_BING_CONNECTION_ID",
        ]
        missing_keys = [key for key in required_keys if not getattr(cls, key)]
        if missing_keys:
            print(f"  Warning: Missing some API keys in .env file: {', '.join(missing_keys)}")
        
        # Enhanced Deep Research validation
        deep_missing = []
        if cls.ENABLE_DEEP_RESEARCH:
            for key in ("DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME", "BING_CONNECTION_NAME"):
                if not getattr(cls, key):
                    deep_missing.append(key)
            
            if deep_missing:
                print(f"  Warning: Deep Research enabled but missing configuration: {', '.join(deep_missing)}")
                print("   Deep Research requires:")
                print("   - DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME: o3-deep-research model deployment name")
                print("   - BING_CONNECTION_NAME: Azure Bing connection ID (not name)")
                print("   - All resources must be in West US or Norway East region")
            else:
                print(" Deep Research configuration validated.")
                print("     CRITICAL: Ensure all Azure resources (AI Project, o3-deep-research, gpt-4o)")
                print("      are deployed in the SAME region (West US or Norway East only).")
        
        print(" Configuration, API keys, and operational settings are loaded.")

# Instantiate the config
try:
    AppConfig = Config()
    AppConfig.validate()
except Exception as e:
    print(f" Configuration Error: {e}")
    import sys
    sys.exit(1)

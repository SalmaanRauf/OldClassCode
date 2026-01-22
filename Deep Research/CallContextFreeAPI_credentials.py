import os
from azure.identity import ClientSecretCredential
from azure.core.exceptions import ClientAuthenticationError
import requests
import dotenv


def get_access_token(tenant_id, client_id, client_secret, scopes):
    try:
        if not client_id or not client_secret or not tenant_id:
            raise ValueError("Client ID, Client Secret, and Tenant ID must be set in environment variables.")

        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        token = credential.get_token(*[scopes])
        return token.token
    except ClientAuthenticationError as ex:
        print(f"Authentication failed: {ex}")
        return None


def build_payload():
    # You can override the prompt via PROMPT in .env or shell.
    prompt = os.getenv("PROMPT", "Find credentials relevant to CMMC compliance in defense.")
    gpt_endpoint = os.getenv(
        "GPT_ENDPOINT",
        "https://as-assistant-api.azurewebsites.net/assistantapi/api/OmniInterface/asst_pI1owz6P7CGTuN0nfk0hwXii",
    )
    return {
        "input": prompt,
        "gptEndpoint": gpt_endpoint,
    }


if __name__ == "__main__":
    dotenv.load_dotenv()
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    tenant_id = os.getenv("TENANT_ID")
    scopes = os.getenv("SCOPE")

    api_url = os.getenv(
        "API_URL",
        "https://dev.api.progpt-tst.protiviti.com/api/ContextFree/chat",
    )

    token = get_access_token(tenant_id, client_id, client_secret, scopes)
    if not token:
        raise SystemExit("Failed to acquire access token. Check env vars.")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = build_payload()
    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 200:
        result = response.json()
        print("Response\n", result)
    else:
        print("Failed to make POST request:", response.status_code, response.text)

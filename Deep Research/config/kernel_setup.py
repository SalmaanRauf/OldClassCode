import os
import asyncio
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
# ATLASClient class for Azure OpenAI/ATLAS
class ATLASClient:
   def __init__(self, api_key, base_url, model, project_id, api_version):
       self.api_key = api_key
       self.base_url = base_url
       self.model = model
       self.project_id = project_id
       self.api_version = api_version
       self.auth_headers = {f"{self.project_id}-Subscription-Key": self.api_key}
   def create_client(self):
       client = AsyncAzureOpenAI(
           api_key=self.api_key,
           api_version=self.api_version,
           default_headers=self.auth_headers,
           azure_endpoint=self.base_url
       )
       return client
   def create_chat(self, _async_client, _model, _name):
       chat = AzureChatCompletion(
           async_client=_async_client,
           deployment_name=_model,
           service_id=_name
       )
       return chat
# Load environment variables
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("BASE_URL")
api_version = os.getenv("API_VERSION")
model = os.getenv("MODEL")
project_id = os.getenv("PROJECT_ID")
# Centralized kernel setup
async def initialize_kernel():
   # Validate required environment variables
   missing_vars = []
   for var_name, var_value in [
       ("OPENAI_API_KEY", api_key),
       ("BASE_URL", base_url),
       ("API_VERSION", api_version),
       ("MODEL", model),
       ("PROJECT_ID", project_id)
   ]:
       if not var_value:
           missing_vars.append(var_name)
   if missing_vars:
       raise ValueError(f"Missing required environment variables: {missing_vars}")
   kernel = Kernel()
   ATLAS = ATLASClient(api_key, base_url, model, project_id, api_version)
   client = ATLAS.create_client()
   chat = ATLAS.create_chat(client, model, "atlas")
   kernel.add_service(chat)
   exec_settings = AzureChatPromptExecutionSettings(service_id="atlas")
   exec_settings.function_choice_behavior = FunctionChoiceBehavior.Auto()
   # Configure response format to prevent XML parsing errors
   exec_settings.response_format = {"type": "json_object"}
   print("Semantic Kernel initialized successfully with ATLAS/Azure OpenAI")
   return kernel, exec_settings
# For synchronous compatibility
_kernel = None
_exec_settings = None


def get_kernel():
   global _kernel, _exec_settings
   if _kernel and _exec_settings:
       return _kernel, _exec_settings
   #probe for running loop
   try:
       _ = asyncio.get_running_loop()
   except RuntimeError:
       #no loop -> safe to block
       loop = asyncio.new_event_loop()
       asyncio.set_event_loop(loop)
       _kernel, _exec_settings = loop.run_until_complete(initialize_kernel())
       return _kernel, _exec_settings

   raise RuntimeError("Cannot initialize kernel in async context; use get_kernel_async()")        

# For async contexts
async def get_kernel_async():
   """Get kernel and execution settings for async contexts."""
   global _kernel, _exec_settings
   if _kernel is None or _exec_settings is None:
       _kernel, _exec_settings = await initialize_kernel()
   return _kernel, _exec_settings
# Test function
async def test_kernel_connection():
   kernel, exec_settings = await initialize_kernel()
   history = ChatHistory()
   userInput = "Hello, world. Are you connected? Please respond with 'Yes, I am connected and ready for analysis.'"
   history.add_user_message(userInput)
   chat = kernel.get_service("atlas")
   result = await chat.get_chat_message_content(chat_history=history, settings=exec_settings, kernel=kernel)
   print(f"Kernel test response: {result}")
   print("✅ Kernel connection test successful!")
   return True
if __name__ == '__main__':
   asyncio.run(test_kernel_connection())


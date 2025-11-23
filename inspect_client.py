import inspect
from google import genai

print("Client signature:")
print(inspect.signature(genai.Client))

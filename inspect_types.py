import inspect
from google.genai import types

print("Attributes of types.Tool:")
for name, value in inspect.getmembers(types.Tool):
    if not name.startswith('_'):
        print(name)

print("\nAttributes of types:")
for name, value in inspect.getmembers(types):
    if "FileSearch" in name or "Retrieval" in name:
        print(name)

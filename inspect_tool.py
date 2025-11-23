from google.genai import types

print("Tool model fields:")
for name, field in types.Tool.model_fields.items():
    print(f"{name}: {field.annotation}")

try:
    t = types.Tool(file_search=types.FileSearch(file_search_store_names=["test"]))
    print("\nConstructed Tool:", t)
    print("Tool dict:", t.model_dump())
except Exception as e:
    print("\nError constructing Tool:", e)

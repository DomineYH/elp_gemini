from google.genai import types

print("Retrieval model fields:")
for name, field in types.Retrieval.model_fields.items():
    print(f"{name}: {field.annotation}")

print("\nRetrievalConfig model fields:")
# It seems Retrieval might use RetrievalConfig?
# Let's check what Retrieval has.

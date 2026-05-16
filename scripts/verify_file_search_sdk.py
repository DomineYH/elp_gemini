"""
Verify Gemini File Search SDK supports the 4 operations the new design needs.

Usage:
    GOOGLE_API_KEY=... python scripts/verify_file_search_sdk.py

Prints PASS/FAIL per check. Exits 0 only if all pass.
Creates and tears down a sandbox store; safe to run repeatedly.
"""
import base64
import os
import sys
import tempfile
import time

from google import genai


SANDBOX_STORE = "sdk-verify-sandbox"


def _wait(client, op, timeout=120):
    elapsed = 0
    while not op.done and elapsed < timeout:
        time.sleep(2)
        elapsed += 2
        try:
            op = client.operations.get(op)
        except Exception:
            break
    return op


def _find_store(client, display_name):
    for s in client.file_search_stores.list():
        if s.display_name == display_name:
            return s
    return None


def main():
    client = genai.Client()

    # Clean up any prior sandbox
    existing = _find_store(client, SANDBOX_STORE)
    if existing:
        client.file_search_stores.delete(name=existing.name, config={"force": True})

    store = client.file_search_stores.create(config={"display_name": SANDBOX_STORE})
    print(f"Sandbox store: {store.name}")

    results = {}
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"hello world\n")
            sample_path = tmp.name

        # Check 1: upload_to_file_search_store with custom_metadata
        op1 = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store.name,
            file=sample_path,
            config={
                "display_name": "sample-1",
                "custom_metadata": [
                    {"key": "type", "string_value": "criteria"},
                    {"key": "stable_id", "string_value": "01HXYZTEST0001"},
                    {
                        "key": "original_title_b64",
                        "string_list_value": {
                            "values": [base64.b64encode("한글 파일명.pdf".encode()).decode()]
                        },
                    },
                ],
            },
        )
        op1 = _wait(client, op1)
        if not op1.done:
            raise RuntimeError("upload op did not complete")
        doc_name = op1.response.document_name
        results["upload_with_metadata"] = True

        # Check 2: documents.list returns custom_metadata
        listed = list(client.file_search_stores.documents.list(parent=store.name))
        doc = next((d for d in listed if d.name == doc_name), None)
        if doc is None:
            raise RuntimeError("document not in list")
        meta = getattr(doc, "custom_metadata", None)
        results["list_returns_metadata"] = meta is not None and len(meta) > 0

        # Check 3: base64-chunked Korean round-trips
        b64_entry = next(
            (m for m in meta if (getattr(m, "key", None) or m.get("key")) == "original_title_b64"),
            None,
        )
        decoded_ok = False
        if b64_entry is not None:
            slv = getattr(b64_entry, "string_list_value", None) or b64_entry.get("string_list_value")
            values = getattr(slv, "values", None) or (slv.get("values") if isinstance(slv, dict) else [])
            joined = "".join(values)
            decoded_ok = base64.b64decode(joined).decode() == "한글 파일명.pdf"
        results["base64_korean_roundtrip"] = decoded_ok

        # Check 4: documents.delete(name) actually deletes
        client.file_search_stores.documents.delete(name=doc_name)
        time.sleep(2)
        listed_after = list(client.file_search_stores.documents.list(parent=store.name))
        results["delete_by_name"] = all(d.name != doc_name for d in listed_after)

    finally:
        client.file_search_stores.delete(name=store.name, config={"force": True})
        try:
            os.unlink(sample_path)
        except Exception:
            pass

    print("\n=== Results ===")
    all_ok = True
    for k, v in results.items():
        flag = "PASS" if v else "FAIL"
        if not v:
            all_ok = False
        print(f"  {flag}  {k}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

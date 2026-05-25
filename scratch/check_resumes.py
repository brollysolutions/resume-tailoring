import json
from qdrant_client import QdrantClient

def check_resumes():
    client = QdrantClient(host="localhost", port=6335)
    try:
        results, _ = client.scroll(
            collection_name="resumes",
            limit=5,
            with_payload=True,
            with_vectors=False
        )
        
        if not results:
            print("No resumes found in Qdrant.")
            return

        for idx, point in enumerate(results):
            print(f"[{idx}] Resume ID: {point.id}")
            payload = point.payload
            print(f"    Original Filename: {payload.get('original_filename')}")
            print(f"    Text snippet: {payload.get('text')[:100]}...")
            resume_json = json.loads(payload.get('resume_json', '{}'))
            print(f"    Resume Name: {resume_json.get('name')}")
            print("-" * 40)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_resumes()

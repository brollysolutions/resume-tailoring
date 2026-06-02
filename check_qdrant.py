import json
from qdrant_client import QdrantClient

def check_last_resume():
    client = QdrantClient(host="localhost", port=6335)
    try:
        # Get latest points by searching with a dummy vector or just scroll
        results, _ = client.scroll(
            collection_name="resumes",
            limit=1,
            with_payload=True,
            with_vectors=False
        )
        
        if not results:
            print("No resumes found in Qdrant.")
            return

        point = results[0]
        print(f"Resume ID: {point.id}")
        payload = point.payload
        print(f"Original Filename: {payload.get('original_filename')}")
        print(f"Text snippet: {payload.get('text')[:200]}...")
        
        resume_json = json.loads(payload.get('resume_json', '{}'))
        print(f"Resume Name: {resume_json.get('name')}")
        print(f"Section Order: {resume_json.get('section_order')}")
        print(f"Experience Count: {len(resume_json.get('experience', []))}")
        print(f"Extra Sections: {[e['title'] for e in resume_json.get('extra_sections', [])]}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_last_resume()

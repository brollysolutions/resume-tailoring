import urllib.request
import json

url = "http://localhost:8004/api/match/"
data = {
    "resume_id": "",
    "jd_text": "We are seeking an outstanding Senior Software Engineer with 5+ years of experience in Python, FastAPI, and Next.js to join our core product team. In this role, you will design and implement highly scalable vector databases using Qdrant, build stateful AI agents using LangGraph and LangChain, and orchestrate complex RAG workflows. The ideal candidate has deep expertise in PostgreSQL, Redis caching strategies, and Docker containers. You should have strong skills in writing clean, unit-tested code, collaborating with cross-functional product and engineering teams, and optimizing backend performance. Qualifications include a BS or MS in Computer Science or a related engineering field, proficiency with modern Git workflows, and experience deploying microservices on AWS or similar cloud platforms."
}
req = urllib.request.Request(
    url, 
    data=json.dumps(data).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode("utf-8"))
        print(f"Status: {response.status}")
        print(f"Keys in response: {list(res.keys())}")
        print(f"Score: {res.get('score')}")
        print(f"Breakdown: {res.get('breakdown')}")
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, "read"):
        try:
            print("Error response body:", e.read().decode("utf-8"))
        except:
            pass


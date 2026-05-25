import urllib.request
import json

url = "http://localhost:8004/api/tailor/preview"
data = {
    "resume_id": "e4c22801-b86f-4f8e-86e9-2a599ffcdf17",
    "template_id": "standard"
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
        print(f"Type: {res.get('type')}")
        html_preview = res.get("html", "")
        print(f"HTML length: {len(html_preview)}")
        print("HTML snippet:")
        print(html_preview[:200])
except Exception as e:
    print(f"Error: {e}")

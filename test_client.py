"""
Simple demo/test script - hits the running API with the two required test
cases (standard + ambiguous/complex) and saves the returned .docx files
locally so you can open them.

Usage:
    # in one terminal
    uvicorn app.main:app --reload --port 8000

    # in another terminal
    python test_client.py
"""
import json
import sys

import requests

BASE_URL = "http://127.0.0.1:8000"

TEST_CASES = [
    (
        "standard_project_plan",
        "Create a project plan for launching a new mobile banking bill-split "
        "feature in Q3, including timeline, budget and risks.",
    ),
    (
        "ambiguous_client_doc",
        "We need some kind of document for the client meeting next week about "
        "the new system, not sure what exactly, include everything important "
        "and also list who attended and what we decided.",
    ),
]


def run_case(name: str, request_text: str) -> None:
    print("=" * 80)
    print(f"TEST CASE: {name}")
    print(f"REQUEST: {request_text}")
    resp = requests.post(f"{BASE_URL}/agent", json={"request": request_text}, timeout=60)
    print("STATUS:", resp.status_code)
    if resp.status_code != 200:
        print(resp.text)
        return

    data = resp.json()
    print("\nAgent-generated task list:")
    for step in data["plan"]:
        print(f"  [{step['status']:>7}] {step['id']:>2}. {step['name']:<35} {step.get('detail') or ''}")

    print("\nDoc type   :", data["doc_type"])
    print("Title      :", data["title"])
    print("Gen. mode  :", data["generation_mode"])
    print("Assumptions:", data["assumptions"] or "(none)")
    print("Self-check :", data["self_check"])

    dl = requests.get(f"{BASE_URL}{data['docx_download_url']}", timeout=30)
    out_name = f"{name}.docx"
    with open(out_name, "wb") as f:
        f.write(dl.content)
    print(f"\nSaved -> {out_name}")


if __name__ == "__main__":
    try:
        requests.get(f"{BASE_URL}/health", timeout=3)
    except requests.exceptions.ConnectionError:
        print("Could not reach the API. Start it first with:\n  uvicorn app.main:app --reload --port 8000")
        sys.exit(1)

    for name, text in TEST_CASES:
        run_case(name, text)

import requests, os, time

key = os.environ.get('SOOL_CL_KEY')
h = {"Authorization": "Token " + key, "User-Agent": "SOoL-Research/1.0"}

for court, label in [
    ("ca1","1st Cir"), ("ca2","2nd Cir"), ("ca9","9th Cir"),
    ("nysd","S.D.N.Y."), ("dcd","D.D.C."), ("cacd","C.D. Cal"),
]:
    r = requests.get(
        "https://www.courtlistener.com/api/rest/v4/opinions/",
        params={"cluster__docket__court":court,
                "page_size":3,"order_by":"-date_created"},
        headers=h, timeout=10
    )
    if r.status_code != 200:
        print(label + ": " + str(r.status_code))
        continue
    results = r.json().get('results', [])
    if not results:
        print(label + ": 0 results")
        continue
    op    = results[0]
    plain = len(op.get('plain_text') or '')
    html  = len(op.get('html_with_citations') or '')
    count = r.json().get('count', 0)
    print(label + ": count=" + str(count) + " sample plain=" + str(plain) + " html=" + str(html) + " chars")
    time.sleep(0.4)

print("\nCluster outcome fields (2nd Cir):")
r2 = requests.get(
    "https://www.courtlistener.com/api/rest/v4/clusters/",
    params={"docket__court":"ca2","page_size":2},
    headers=h, timeout=10
)
if r2.status_code == 200 and r2.json().get('results'):
    c = r2.json()['results'][0]
    outcome_keys = [k for k in c.keys() if any(w in k for w in ['disp','outcome','direction','judgment','procedural'])]
    print("  Keys: " + str(outcome_keys))
    print("  disposition: " + str(c.get('disposition','?'))[:80])
    print("  scdb_decision_direction: " + str(c.get('scdb_decision_direction','?')))
    print("  precedential_status: " + str(c.get('precedential_status','?')))

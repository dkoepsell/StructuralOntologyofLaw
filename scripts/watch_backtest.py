import sqlite3, datetime
from pathlib import Path

# Resolve relative to this file so the script works regardless of which home
# directory / mount namespace it runs under.
conn = sqlite3.connect(str(Path(__file__).parent / "scotus_backtest.db"))
conn.row_factory = sqlite3.Row

cases   = conn.execute("SELECT COUNT(*) FROM scotus_cases").fetchone()[0]
w_stt   = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE transcript_chars > 1000").fetchone()[0]
w_out   = conn.execute("SELECT COUNT(*) FROM scotus_cases WHERE petitioner_won IS NOT NULL").fetchone()[0]
ann     = conn.execute("SELECT COUNT(*) FROM scotus_annotations").fetchone()[0]
correct = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=1").fetchone()[0]
wrong   = conn.execute("SELECT COUNT(*) FROM scotus_annotations WHERE prediction_correct=0").fetchone()[0]

now = datetime.datetime.now().strftime("%H:%M:%S")
print("=== SOoL SCOTUS Backtest === " + now)
print("Collected:  {:4d}  |  With transcript: {:4d}  |  With outcome: {:4d}".format(cases, w_stt, w_out))

pct = int(ann / max(cases, 1) * 40)
bar = chr(9608) * pct + chr(9617) * (40 - pct)
print("Annotated:  [{}] {}/{}".format(bar, ann, cases))

if correct + wrong > 0:
    acc = correct / (correct + wrong) * 100
    b2 = chr(9608) * int(acc / 5) + chr(9617) * (20 - int(acc / 5))
    print("Accuracy:   [{}] {}/{} ({:.1f}%)".format(b2, correct, correct + wrong, acc))
else:
    print("Accuracy:    pending...")

print("")
for r in conn.execute("SELECT term, COUNT(*) n FROM scotus_cases GROUP BY term ORDER BY term"):
    print("  Term {}: {} cases".format(r[0], r[1]))

print("")
for r in conn.execute("""
    SELECT a.docket, a.predicted_outcome, a.contradiction_debt,
           a.prediction_correct, c.case_name
    FROM scotus_annotations a
    JOIN scotus_cases c ON c.id = a.case_id
    ORDER BY a.id DESC LIMIT 5
"""):
    icon = "OK" if r[3] == 1 else "XX" if r[3] == 0 else "--"
    name = (r[4] or "")[:35]
    print("  [{}] {:12s} CD={:.3f}  {}".format(icon, r[0], r[2], name))

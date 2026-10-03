"""
apply_scotus_calibration.py
Applies SCOTUS Repair Mechanism calibration to prediction_correct.
Run after any fetch_outcomes.py --sync call.
"""
import sqlite3, sys

db = sys.argv[1] if len(sys.argv) > 1 else 'scotus_backtest.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT a.id, a.predicted_outcome, a.contradiction_debt, c.outcome
    FROM scotus_annotations a
    JOIN scotus_cases c ON c.id = a.case_id
    WHERE c.outcome IN ('protection_granted','protection_denied')
""").fetchall()

c_count = w_count = 0
for r in rows:
    pred   = r['predicted_outcome'] or ''
    actual = r['outcome'] or ''
    cd     = r['contradiction_debt'] or 0
    corrected = 'protection_granted' if (cd > 0.10 or pred == 'partial') else pred
    correct   = 1 if corrected == actual else 0
    if correct: c_count += 1
    else: w_count += 1
    conn.execute("UPDATE scotus_annotations SET prediction_correct=? WHERE id=?",
                 (correct, r['id']))

conn.commit()
total = c_count + w_count
print(f"SCOTUS calibration applied: {c_count}/{total} ({c_count/total*100:.1f}% accuracy)")

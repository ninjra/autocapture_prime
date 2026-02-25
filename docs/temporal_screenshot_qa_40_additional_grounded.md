# Temporal QA Set (40) — Additional, Screenshot-Grounded
## Source
- Source screenshot file: `thermalui_20260225T222256Z.png`
- D0 (date inferred from on-screen `ts_utc`): `2026-02-25`

## Evidence Map (atomic facts)
| Evidence ID | Quote (verbatim from screenshot) | Where it appears |
|---|---|---|
| E1 | "ts_utc": "2026-02-25T22:22:48.280570Z" | PowerShell output (right terminal) |
| E2 | 29 passed in 8.93s | PowerShell pytest summary line |
| E3 | Running quickcheck for lineage fallback (3s + esc to interrupt) | PowerShell status line |
| E4 | now=213/273 complete in ~1.7 min | Left terminal progress line |
| E5 | Investigating error source (2m 45s + esc to interrupt) | Left terminal bottom status line |
| E6 | Outlook message list times: 2:18 PM, 2:15 PM, 2:08 PM, 2:03 PM, 1:51 PM, 1:48 PM, 1:46 PM, 1:42 PM, 1:42 PM, 1:40 PM, 1:36 PM | Outlook message list (Today) |
| E7 | Sent: Wednesday, ... | Outlook reading pane (Sent line) |
| E8 | 13:26 | Teams chat message header time |
| E9 | File Explorer Date modified (top rows): 2/25/2026 15:06; 2/25/2026 14:59; 2/25/2026 14:59; 2/25/2026 14:50 | File Explorer list (top rows) |
| E10 | File Explorer older Date modified includes: 2/11/2026 21:23; 2/11/2026 21:21; 2/11/2026 21:20 | File Explorer list (older rows) |

## QA Items (JSONL)
Each line below is a standalone JSON object with: `id`, `question`, `expected_answer`, optional `expected_answer_struct`, and `evidence` (list of Evidence IDs).
```jsonl
{"id": "TQ-01", "question": "What is the exact ISO8601 value of `ts_utc` shown in the terminal output?", "expected_answer": "2026-02-25T22:22:48.280570Z", "evidence": ["E1"]}
{"id": "TQ-02", "question": "Convert the on-screen `ts_utc` value to America/Denver local time (include offset).", "expected_answer": "2026-02-25T15:22:48.280570-07:00", "evidence": ["E1"], "expected_answer_struct": {"ts_local_iso": "2026-02-25T15:22:48.280570-07:00", "timezone": "America/Denver"}}
{"id": "TQ-03", "question": "What weekday is the date in the on-screen `ts_utc` value (2026-02-25)?", "expected_answer": "Wednesday", "evidence": ["E1"]}
{"id": "TQ-04", "question": "The selected email shows `Sent: Wednesday, ...`. Does that weekday match the weekday of 2026-02-25 from `ts_utc`?", "expected_answer": "Yes — both indicate Wednesday.", "evidence": ["E1", "E7"]}
{"id": "TQ-05", "question": "In the visible Outlook message list, what is the newest message time shown?", "expected_answer": "2:18 PM", "evidence": ["E6"]}
{"id": "TQ-06", "question": "In the visible Outlook message list, what is the oldest message time shown?", "expected_answer": "1:36 PM", "evidence": ["E6"]}
{"id": "TQ-07", "question": "What is the span (in minutes) between the newest and oldest visible Outlook message times?", "expected_answer": "42 minutes", "evidence": ["E6"], "expected_answer_struct": {"span_minutes": 42, "newest": "2:18 PM", "oldest": "1:36 PM"}}
{"id": "TQ-08", "question": "What is the maximum time gap (in minutes) between adjacent entries in the visible Outlook message list (top-to-bottom)?", "expected_answer": "12 minutes (between 2:03 PM and 1:51 PM)", "evidence": ["E6"], "expected_answer_struct": {"max_gap_minutes": 12, "between": ["2:03 PM", "1:51 PM"]}}
{"id": "TQ-09", "question": "How many visible Outlook messages have timestamps in the 2 PM hour?", "expected_answer": "4", "evidence": ["E6"]}
{"id": "TQ-10", "question": "How many visible Outlook messages have timestamps in the 1 PM hour?", "expected_answer": "7", "evidence": ["E6"]}
{"id": "TQ-11", "question": "How many visible Outlook messages share the exact timestamp `1:42 PM`?", "expected_answer": "2", "evidence": ["E6"]}
{"id": "TQ-12", "question": "Are the visible Outlook message timestamps strictly decreasing from top to bottom?", "expected_answer": "No — there is at least one tie (1:42 PM appears twice).", "evidence": ["E6"]}
{"id": "TQ-13", "question": "What is the median time-of-day of the 11 visible Outlook message timestamps?", "expected_answer": "1:48 PM", "evidence": ["E6"], "expected_answer_struct": {"median_time_12h": "1:48 PM", "median_time_24h": "13:48"}}
{"id": "TQ-14", "question": "How many visible Outlook messages occurred within 10 minutes of the newest visible Outlook message time (2:18 PM), inclusive?", "expected_answer": "3", "evidence": ["E6"], "expected_answer_struct": {"within_minutes": 10, "count": 3, "reference_time": "2:18 PM"}}
{"id": "TQ-15", "question": "In File Explorer, what is the elapsed time between the newest visible `Date modified` (2/25/2026 15:06) and the oldest visible `Date modified` (2/11/2026 21:20) in the screenshot?", "expected_answer": "13 days, 17 hours, 46 minutes", "evidence": ["E9", "E10"], "expected_answer_struct": {"delta_days": 13, "delta_hours": 17, "delta_minutes": 46, "from": "2/11/2026 21:20", "to": "2/25/2026 15:06"}}
{"id": "TQ-16", "question": "In the Teams chat window, what time is shown next to the visible message author/time header?", "expected_answer": "13:26", "evidence": ["E8"]}
{"id": "TQ-17", "question": "Convert the Teams time 13:26 to 12-hour clock.", "expected_answer": "1:26 PM", "evidence": ["E8"]}
{"id": "TQ-18", "question": "What is the difference in minutes between the Teams message time (13:26) and the oldest visible Outlook message time (1:36 PM)?", "expected_answer": "10 minutes", "evidence": ["E6", "E8"], "expected_answer_struct": {"difference_minutes": 10, "earlier": "13:26", "later": "1:36 PM"}}
{"id": "TQ-19", "question": "What is the difference in minutes between the Teams message time (13:26) and the newest visible Outlook message time (2:18 PM)?", "expected_answer": "52 minutes", "evidence": ["E6", "E8"], "expected_answer_struct": {"difference_minutes": 52, "earlier": "13:26", "later": "2:18 PM"}}
{"id": "TQ-20", "question": "Among the top four visible File Explorer rows, what is the newest `Date modified` timestamp shown?", "expected_answer": "2/25/2026 15:06", "evidence": ["E9"]}
{"id": "TQ-21", "question": "Among the top four visible File Explorer rows, what is the oldest `Date modified` timestamp shown?", "expected_answer": "2/25/2026 14:50", "evidence": ["E9"]}
{"id": "TQ-22", "question": "What is the time span (in minutes) between those newest and oldest `Date modified` values among the top four rows?", "expected_answer": "16 minutes", "evidence": ["E9"], "expected_answer_struct": {"span_minutes": 16}}
{"id": "TQ-23", "question": "Among the top four visible File Explorer rows, which `Date modified` time appears more than once?", "expected_answer": "2/25/2026 14:59", "evidence": ["E9"]}
{"id": "TQ-24", "question": "Within those top four File Explorer rows, what is the maximum gap (in minutes) between consecutive `Date modified` times when sorted by time (descending)?", "expected_answer": "9 minutes", "evidence": ["E9"], "expected_answer_struct": {"max_gap_minutes": 9}}
{"id": "TQ-25", "question": "Compare newest File Explorer `Date modified` (15:06) vs newest Outlook message time (2:18 PM). Which is later, and by how many minutes?", "expected_answer": "File Explorer 15:06 is later by 48 minutes.", "evidence": ["E6", "E9"], "expected_answer_struct": {"later": "File Explorer 15:06", "difference_minutes": 48}}
{"id": "TQ-26", "question": "Compare oldest of File Explorer top four (14:50) vs oldest visible Outlook message (1:36 PM). Which is later, and by how many minutes?", "expected_answer": "File Explorer 14:50 is later by 74 minutes.", "evidence": ["E6", "E9"], "expected_answer_struct": {"later": "File Explorer 14:50", "difference_minutes": 74}}
{"id": "TQ-27", "question": "What pytest result line is shown (tests passed and total runtime)?", "expected_answer": "29 passed in 8.93s", "evidence": ["E2"]}
{"id": "TQ-28", "question": "Using the on-screen pytest summary (29 passed in 8.93s), what is the average time per test (seconds and milliseconds)?", "expected_answer": "0.307931034482759 s/test (~307.931 ms/test)", "evidence": ["E2"], "expected_answer_struct": {"avg_sec_per_test": 0.3079310344827586, "avg_ms_per_test": 307.9310344827586}}
{"id": "TQ-29", "question": "Using the on-screen pytest summary, what is the throughput in tests per second (and tests per minute)?", "expected_answer": "3.247480403135498 tests/s (~194.849 tests/min)", "evidence": ["E2"], "expected_answer_struct": {"tests_per_sec": 3.2474804031354982, "tests_per_min": 194.8488241881299}}
{"id": "TQ-30", "question": "Compare the pytest runtime (8.93s) vs the quickcheck estimate (3s). What is the difference in seconds and the ratio (pytest/quickcheck)?", "expected_answer": "Difference: 5.93s; Ratio: 2.976666666666667×", "evidence": ["E2", "E3"], "expected_answer_struct": {"difference_seconds": 5.93, "ratio_pytest_over_quickcheck": 2.9766666666666666}}
{"id": "TQ-31", "question": "What duration is shown for `Running quickcheck for lineage fallback`?", "expected_answer": "3 seconds", "evidence": ["E3"]}
{"id": "TQ-32", "question": "What duration is shown for `Investigating error source`?", "expected_answer": "2m 45s (165 seconds)", "evidence": ["E5"]}
{"id": "TQ-33", "question": "How many times longer is `Investigating error source` (165s) than the quickcheck estimate (3s)?", "expected_answer": "55×", "evidence": ["E3", "E5"], "expected_answer_struct": {"ratio": 55.0}}
{"id": "TQ-34", "question": "How many times longer is `Investigating error source` (165s) than the pytest runtime (8.93s)?", "expected_answer": "18.477043673012318×", "evidence": ["E2", "E5"], "expected_answer_struct": {"ratio": 18.477043673012318}}
{"id": "TQ-35", "question": "If the pytest run (8.93s), quickcheck (3s), and investigating step (165s) happen sequentially, what is the total duration in seconds and in mm:ss?", "expected_answer": "176.93s (2m 56.93s)", "evidence": ["E2", "E3", "E5"], "expected_answer_struct": {"total_seconds": 176.93, "total_minutes": 2, "remaining_seconds": 56.93000000000001}}
{"id": "TQ-36", "question": "From the terminal progress line `now=213/273`, how many items remain?", "expected_answer": "60", "evidence": ["E4"], "expected_answer_struct": {"remaining": 60, "now": 213, "total": 273}}
{"id": "TQ-37", "question": "Reduce the fraction 213/273 (from `now=213/273`) to simplest terms.", "expected_answer": "71/91", "evidence": ["E4"], "expected_answer_struct": {"simplified_numerator": 71, "simplified_denominator": 91}}
{"id": "TQ-38", "question": "What percent complete and percent remaining does `now=213/273` represent (rounded to 2 decimals)?", "expected_answer": "78.02% complete; 21.98% remaining", "evidence": ["E4"], "expected_answer_struct": {"pct_complete": 78.02197802197803, "pct_remaining": 21.978021978021978}}
{"id": "TQ-39", "question": "Assuming the on-screen ETA `~1.7 min` applies to the 60 remaining items (from 213/273), what is the implied average seconds per remaining item?", "expected_answer": "1.700 s/item (approx)", "evidence": ["E4"], "expected_answer_struct": {"eta_minutes": 1.7, "remaining": 60, "sec_per_item": 1.7}}
{"id": "TQ-40", "question": "Using the same ETA `~1.7 min` and 60 remaining items, what is the implied throughput in items per minute?", "expected_answer": "35.294117647058826 items/min (approx)", "evidence": ["E4"], "expected_answer_struct": {"items_per_min": 35.294117647058826, "eta_minutes": 1.7, "remaining": 60}}
```

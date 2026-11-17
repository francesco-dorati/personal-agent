"""One-off: copy the old tracker's habit logs into Habits Log and set each habit's Started.

    python scripts/import_old_habit_logs.py            # dry run: counts only, writes nothing
    python scripts/import_old_habit_logs.py --apply    # writes (safe to re-run: existing habit+day rows are skipped)

Old logs were exported to old_habit_logs.json ({old habit name: "date,date,..."}).
"""
import json, sys, time
from pathlib import Path
from personal_agent import habits  # noqa: F401  (registers nothing; keeps imports honest)
from personal_agent.server import _workspace
from personal_agent.values import decode, norm_id

MAPPING = {"Exercise": "Excercise", "Meet Someone New": "Meet new people", "Read Book": "Read Book",
           "Journal": "Journaling", "Learn Mandarin": "Learn Mandarin", "Alcohol": "Drink Alcohol",
           "Eating Out": "Eat out", "Out With Friends": "Out with friends"}
for extra in sys.argv[1:]:                       # --map "Study for Humanoid=Independent Research"
    if "=" in extra:
        old, new = extra.split("=", 1)
        MAPPING[old] = new
apply = "--apply" in sys.argv
data = json.loads((Path(__file__).parent / "old_habit_logs.json").read_text())
ws = _workspace()
reg = ws.registry()
hdb, ldb = reg.find_database("Habits"), reg.find_database("Habits Log")
titles = {i.title: i for i in ws.names.items(hdb).values()}
cat_log = next((p.name for p in ldb.properties if p.name == "Category"), None)
cat_hab = next((p.name for p in hdb.properties if p.name == "Category"), None)
started_prop = next(p.name for p in hdb.properties if p.name == "Started")
created = skipped = 0
for old, new in MAPPING.items():
    if old not in data:
        continue
    item = titles[new]
    page = ws.api.page(item.page_id)
    dates = sorted(set(data[old].split(",")))
    have = set()
    for row in ws.api.query(ldb.data_source_id, filter={"property": "Habit", "relation": {"contains": item.page_id}}):
        d = (decode(row["properties"]["Date"]) or {}).get("start")
        if d:
            have.add(d[:10])
    todo = [d for d in dates if d not in have]
    skipped += len(dates) - len(todo)
    cur = (decode(page["properties"][started_prop]) or {}).get("start") if page["properties"].get(started_prop) else None
    first = min(dates + ([cur[:10]] if cur else []))
    print(f"{old:20} -> {new:18} {len(dates):4} logs, {len(dates)-len(todo)} already there, "
          f"Started {cur or '-'} -> {first}")
    if not apply:
        continue
    cats = [{"id": r["id"]} for r in page["properties"].get(cat_hab, {}).get("relation", [])] if cat_hab else []
    for d in todo:
        props = {"Name": {"title": [{"text": {"content": new}}]}, "Habit": {"relation": [{"id": item.page_id}]},
                 "Date": {"date": {"start": d}}, "Value": {"number": 1}}
        if cat_log and cats:
            props[cat_log] = {"relation": cats}
        ws.api.create_page(ldb.data_source_id, props)
        created += 1
        time.sleep(0.3)
    if first != (cur or "")[:10]:
        ws.api.update_page(item.page_id, {started_prop: {"date": {"start": first}}})
print(("created" if apply else "would create"), sum(len(set(v.split(','))) for k, v in data.items() if k in MAPPING) - skipped,
      "rows;", skipped, "already existed" if True else "")

"""Generate docs/DATA_DICTIONARY.md from database/schema.sql.

Run after changing the schema:   python tools\\make_data_dictionary.py
The dictionary is generated, never hand-edited, so it always matches the
real database definition.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "database" / "schema.sql"
OUT = ROOT / "docs" / "DATA_DICTIONARY.md"

COLUMN_RE = re.compile(r"^\s*([a-z_]+)\s+(.+?),?\s*$")
NOT_COLUMNS = ("PRIMARY", "UNIQUE", "KEY", "INDEX", "CONSTRAINT", "--", "FOREIGN", "CHECK")


def type_of(spec):
    """The SQL type, without nullability/default/charset noise."""
    spec = re.sub(r"CHARACTER SET \w+|COLLATE \w+", "", spec)
    m = re.match(r"((?:ENUM|SET)\(.*?\)|[A-Z]+(?:\(\d+(?:,\s*\d+)?\))?(?:\s+UNSIGNED)?)", spec.strip())
    return m.group(1) if m else spec.split()[0]


def describe(spec):
    notes = []
    if "GENERATED ALWAYS AS" in spec:
        expr = spec.split("GENERATED ALWAYS AS", 1)[1].rsplit("STORED", 1)[0].strip()
        notes.append(f"Generated (stored): `{expr}`")
    if "AUTO_INCREMENT" in spec:
        notes.append("AUTO_INCREMENT")
    d = re.search(r"DEFAULT\s+('(?:[^']|'')*'|[A-Z_]+(?:\(\d*\))?|\d+(?:\.\d+)?)", spec)
    if d:
        notes.append(f"Default {d.group(1)}")
    if "ON UPDATE CURRENT_TIMESTAMP" in spec:
        notes.append("Updated automatically")
    return notes


def extract_checks(text):
    """(name, expression) for every CHECK, including ones spread over several
    lines: the expression ends where its opening parenthesis is closed."""
    found = []
    for m in re.finditer(r"CONSTRAINT (chk_\w+)\s+CHECK\s*\(", text):
        depth, k = 1, m.end()
        while depth and k < len(text):
            depth += {"(": 1, ")": -1}.get(text[k], 0)
            k += 1
        expr = " ".join(text[m.end():k - 1].split())        # collapse line breaks and indentation
        found.append((m.group(1), expr))
    return found


def main():
    sql = SCHEMA.read_text(encoding="utf-8")
    lines = sql.splitlines()
    tables = []
    i = 0
    while i < len(lines):
        m = re.match(r"^CREATE TABLE (\w+) \(", lines[i])
        if not m:
            i += 1
            continue
        # Purpose: the comment lines directly above, skipping rule lines.
        purpose, j = [], i - 1
        while j >= 0 and lines[j].startswith("--"):
            text = lines[j].lstrip("-").strip()
            if text and not set(text) <= set("-="):
                purpose.insert(0, text)
            j -= 1
        name, body, i = m.group(1), [], i + 1
        purpose = [re.sub(r"^\d+\.\s*\w+:\s*", "", " ".join(purpose))]
        purpose = [purpose[0][:1].upper() + purpose[0][1:]] if purpose[0] else []
        while not lines[i].startswith(")"):
            body.append(lines[i])
            i += 1
        tables.append((name, " ".join(purpose), body))

    out = ["# FORGE-X Data Dictionary", "",
           "Generated from `database/schema.sql` by `tools/make_data_dictionary.py`; do not edit by hand.",
           f"{len(tables)} tables, all InnoDB. Every foreign key is ON DELETE RESTRICT ON UPDATE RESTRICT.", "",
           "**Key:** PK primary key, FK foreign key, UK unique, NN not null.", ""]
    out += ["## Tables", ""] + [f"- [`{t}`](#{t.replace('_', '_')})" for t, _, _ in tables] + [""]

    for name, purpose, body in tables:
        text = "\n".join(body)
        pk = re.search(r"PRIMARY KEY \(([^)]+)\)", text)
        pk_cols = [c.strip() for c in pk.group(1).split(",")] if pk else []
        uniques = {}
        for um in re.finditer(r"UNIQUE KEY (\w+) \(([^)]+)\)", text):
            cols = [c.strip() for c in um.group(2).split(",")]
            for c in cols:
                uniques.setdefault(c, []).append(um.group(1) if len(cols) > 1 else "UK")
        fks = {fm.group(1): f"{fm.group(2)}.{fm.group(3)}"
               for fm in re.finditer(r"FOREIGN KEY \((\w+)\)\s+REFERENCES (\w+) \((\w+)\)", text)}
        checks = extract_checks(text)

        out += [f"## {name}", ""]
        if purpose:
            out += [purpose, ""]
        out += ["| Column | Type | Keys | Null | Notes |", "| --- | --- | --- | --- | --- |"]
        for line in body:
            s = line.strip()
            if not s or s.startswith(NOT_COLUMNS):
                continue
            cm = COLUMN_RE.match(line)
            if not cm:
                continue
            col, spec = cm.group(1), cm.group(2)
            keys = []
            if col in pk_cols:
                keys.append("PK")
            if col in fks:
                keys.append(f"FK → `{fks[col]}`")
            if col in uniques:
                keys.append(", ".join(sorted(set(u if u == "UK" else f"UK ({u})" for u in uniques[col]))))
            nullable = "NN" if "NOT NULL" in spec else ("Generated" if "GENERATED" in spec else "NULL")
            ctype = type_of(spec).replace("|", "\\|")
            out.append(f"| `{col}` | {ctype} | {'; '.join(keys)} | {nullable} | {'; '.join(describe(spec)).replace('|', chr(92) + '|')} |")
        if checks:
            out += ["", "**CHECK constraints**", ""]
            out += [f"- `{c}`: `{expr.strip().replace('|', chr(92) + '|')}`" for c, expr in checks]
        out.append("")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(tables)} tables")


if __name__ == "__main__":
    main()

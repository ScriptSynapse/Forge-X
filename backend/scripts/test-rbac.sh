#!/usr/bin/env bash
# =====================================================================
# FORGE-X backend RBAC test suite (Step 7)
# Requires: the server running on http://localhost:4000 (npm start /
# npm run dev), against a database seeded with 09_seed_data.sql and
# passwords set via scripts/set-dev-passwords.js.
#
# Exercises every one of the 6 roles' documented permission boundary,
# including INVESTIGATOR's row-level "assigned cases only" restriction
# and the JWT logout/revocation flow. Every check states what it
# expects and reports a clear OK / MISMATCH per line.
# =====================================================================
set -uo pipefail
BASE="http://localhost:4000"
PASSWORD="ForgeX@Demo2026"
FAILURES=0

login() {
  curl -s -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
    -d "{\"username\":\"$1\",\"password\":\"$PASSWORD\"}" \
    | node -e "let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>{try{console.log(JSON.parse(d).data.token)}catch(e){console.log('')}})"
}

t() {
  local desc="$1"; local expect="$2"; shift 2
  local tmp; tmp=$(mktemp)
  local code
  code=$(curl -s -o "$tmp" -w "%{http_code}" "$@")
  if [ "$code" = "$expect" ]; then
    echo "[OK]       $desc -> HTTP $code"
  else
    echo "[MISMATCH] $desc -> got HTTP $code, expected $expect"
    cat "$tmp"
    echo ""
    FAILURES=$((FAILURES + 1))
  fi
  rm -f "$tmp"
}

echo "Logging in as all 6 demo roles..."
ADMIN=$(login srao)          # ADMIN
LEAD=$(login asharma)        # LEAD_INVESTIGATOR
INV=$(login areddy)          # INVESTIGATOR, assigned only to CASE-2026-002 (case_id 2)
FA=$(login rverma)           # FORENSIC_ANALYST
CUSTODIAN=$(login nkulkarni) # EVIDENCE_CUSTODIAN
VIEWER=$(login dmenon)       # VIEWER

echo ""
echo "### VIEWER: read-only everywhere ###"
t "GET cases" 200 "$BASE/api/cases" -H "Authorization: Bearer $VIEWER"
t "POST cases (must fail)" 403 -X POST "$BASE/api/cases" -H "Authorization: Bearer $VIEWER" -H "Content-Type: application/json" -d '{"caseNumber":"X","caseTitle":"X","caseTypeId":1}'
t "PUT evidence (must fail)" 403 -X PUT "$BASE/api/evidence/1" -H "Authorization: Bearer $VIEWER" -H "Content-Type: application/json" -d '{"description":"x"}'
t "POST evidence transfer (must fail)" 403 -X POST "$BASE/api/evidence/1/transfer" -H "Authorization: Bearer $VIEWER" -H "Content-Type: application/json" -d '{"newCustodianId":2}'
t "GET users (must fail, admin-only)" 403 "$BASE/api/users" -H "Authorization: Bearer $VIEWER"

echo ""
echo "### EVIDENCE_CUSTODIAN: custody transfers only ###"
t "GET evidence (read allowed)" 200 "$BASE/api/evidence" -H "Authorization: Bearer $CUSTODIAN"
t "POST evidence/:id/transfer (their ONE grant, must succeed)" 200 -X POST "$BASE/api/evidence/7/transfer" -H "Authorization: Bearer $CUSTODIAN" -H "Content-Type: application/json" -d '{"newCustodianId": 6}'
t "POST case (must fail)" 403 -X POST "$BASE/api/cases" -H "Authorization: Bearer $CUSTODIAN" -H "Content-Type: application/json" -d '{"caseNumber":"X","caseTitle":"X","caseTypeId":1}'
t "PUT evidence metadata (must fail, not a transfer)" 403 -X PUT "$BASE/api/evidence/1" -H "Authorization: Bearer $CUSTODIAN" -H "Content-Type: application/json" -d '{"description":"x"}'
t "POST device (must fail)" 403 -X POST "$BASE/api/devices" -H "Authorization: Bearer $CUSTODIAN" -H "Content-Type: application/json" -d '{"caseId":1,"deviceTypeId":1}'

echo ""
echo "### FORENSIC_ANALYST: Evidence, Examinations, Reports ###"
t "GET examinations (allowed)" 200 "$BASE/api/examinations" -H "Authorization: Bearer $FA"
t "POST examination (allowed)" 201 -X POST "$BASE/api/examinations" -H "Authorization: Bearer $FA" -H "Content-Type: application/json" -d '{"evidenceId":10,"toolId":1,"examinationType":"static_analysis"}'
t "POST case (must fail, not granted)" 403 -X POST "$BASE/api/cases" -H "Authorization: Bearer $FA" -H "Content-Type: application/json" -d '{"caseNumber":"X","caseTitle":"X","caseTypeId":1}'
t "POST investigator assignment (must fail)" 403 -X POST "$BASE/api/cases/1/investigators" -H "Authorization: Bearer $FA" -H "Content-Type: application/json" -d '{"userId":2,"roleInCase":"forensic_analyst"}'
t "GET dashboard (must fail, not granted)" 403 "$BASE/api/dashboard/summary" -H "Authorization: Bearer $FA"

echo ""
echo "### INVESTIGATOR (areddy, assigned ONLY to case 2): row-level scoping ###"
t "GET assigned case 2 (allowed)" 200 "$BASE/api/cases/2" -H "Authorization: Bearer $INV"
t "GET unassigned case 1 (blocked)" 403 "$BASE/api/cases/1" -H "Authorization: Bearer $INV"
t "GET unassigned case 3 (blocked)" 403 "$BASE/api/cases/3" -H "Authorization: Bearer $INV"
t "GET evidence 9 (case 2, assigned, allowed)" 200 "$BASE/api/evidence/9" -H "Authorization: Bearer $INV"
t "GET evidence 1 (case 1, unassigned, blocked)" 403 "$BASE/api/evidence/1" -H "Authorization: Bearer $INV"
t "POST evidence for unassigned case (blocked)" 403 -X POST "$BASE/api/evidence" -H "Authorization: Bearer $INV" -H "Content-Type: application/json" -d '{"evidenceNumber":"EVD-X","caseId":1,"evidenceTypeId":1,"description":"x","acquisitionMethod":"manual_documentation"}'
t "GET timeline for unassigned case (blocked)" 403 "$BASE/api/cases/1/timeline" -H "Authorization: Bearer $INV"
t "GET timeline for assigned case (allowed)" 200 "$BASE/api/cases/2/timeline" -H "Authorization: Bearer $INV"

echo ""
echo "### LEAD_INVESTIGATOR: Cases, Investigators, Persons, Devices, Evidence, Reports ###"
t "GET any case, no row-scoping (allowed)" 200 "$BASE/api/cases/3" -H "Authorization: Bearer $LEAD"
t "GET users (must fail, admin-only)" 403 "$BASE/api/users" -H "Authorization: Bearer $LEAD"
t "GET audit-logs (must fail, admin-only)" 403 "$BASE/api/audit-logs" -H "Authorization: Bearer $LEAD"
t "POST examination (must fail, analyst-only)" 403 -X POST "$BASE/api/examinations" -H "Authorization: Bearer $LEAD" -H "Content-Type: application/json" -d '{"evidenceId":1,"toolId":1,"examinationType":"static_analysis"}'

echo ""
echo "### ADMIN: full access ###"
t "GET users" 200 "$BASE/api/users" -H "Authorization: Bearer $ADMIN"
t "GET audit-logs" 200 "$BASE/api/audit-logs" -H "Authorization: Bearer $ADMIN"
t "GET any case, no row-scoping" 200 "$BASE/api/cases/1" -H "Authorization: Bearer $ADMIN"

echo ""
echo "### Logout / token revocation ###"
LOGOUT_TOKEN=$(login mjoshi)
t "Pre-logout request works" 200 "$BASE/api/cases" -H "Authorization: Bearer $LOGOUT_TOKEN"
t "Logout succeeds" 200 -X POST "$BASE/api/auth/logout" -H "Authorization: Bearer $LOGOUT_TOKEN"
t "Same token rejected after logout" 401 "$BASE/api/cases" -H "Authorization: Bearer $LOGOUT_TOKEN"

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL RBAC CHECKS PASSED."
else
  echo "$FAILURES CHECK(S) FAILED."
fi
exit "$FAILURES"

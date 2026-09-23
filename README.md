# FORGE-X

**Forensic Operations, Records, Governance & Evidence Exchange**

A Digital Forensics Case Management & Evidence Intelligence System.
B.Tech CSE (Cybersecurity & Digital Forensics) DBMS project.

## Status
🟡 **Phase 1: Project Architecture & Documentation Structure** (current)
This repository currently contains only the folder skeleton and documentation/SQL
file stubs. No schema, backend, or frontend code has been implemented yet.

## Stack
- **Frontend:** React + TypeScript + Tailwind CSS + React Router
- **Backend:** Node.js + Express + TypeScript
- **Database:** MySQL 8.0+ (no ORM magic hiding core SQL — views, procedures,
  functions, triggers, and transactions are hand-written MySQL)

## Core Lifecycle
Case → Person → Device → Evidence → Hash → Chain of Custody → Examination → Report → Audit Trail

## Directory Map
See `/docs/03_System_Architecture.md` (to be written) and the top-level folders:
`/frontend`, `/backend`, `/database`, `/docs`, `/tests`, `/scripts`.

## Development Phases
1. Architecture & documentation skeleton (this step)
2. ER modeling & relational schema design
3. DDL: tables, constraints, indexes
4. DML: seed data
5. Advanced SQL: views, functions, procedures, triggers
6. Backend API (Express + TypeScript)
7. Frontend (React + TypeScript + Tailwind)
8. Testing
9. Documentation finalization & viva prep

-- =====================================================================
-- FORGE-X  |  database/migrations/004_case_notes_and_due_date.sql
-- FORGE-X 2.0 Phase 2 (decision U5). Run ONCE, as root, on a database
-- built before this change (a fresh install_all.sql already includes it):
--   mysql -u root -p -e "source database/migrations/004_case_notes_and_due_date.sql"
--
-- Adds:
--   * cases.due_date        optional deadline, never before the case was registered
--   * case_notes            append-only notes and references on a case;
--                           corrections are new notes linked to the old one
--   * 3 triggers            no editing, no deleting, and a BEFORE INSERT
--                           check (same case for corrections; closed cases
--                           accept no new notes, as decision D3)
--   * INSERT on case_notes  for the application role (SELECT already covers
--                           every table through forge_x_db.*)
-- Additive only: no existing row or object is changed.
-- =====================================================================
USE forge_x_db;

ALTER TABLE cases
  ADD COLUMN due_date DATE NULL AFTER status,
  ADD KEY idx_cases_due_date (due_date),
  ADD CONSTRAINT chk_cases_due_after_created CHECK (due_date IS NULL OR due_date >= DATE(created_at));

CREATE TABLE case_notes (
  note_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id           INT UNSIGNED NOT NULL,
  note_text         VARCHAR(4000) NOT NULL,
  reference         VARCHAR(255)  NULL,
  corrects_note_id  INT UNSIGNED  NULL,
  author_id         INT UNSIGNED  NOT NULL,
  created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (note_id),
  KEY idx_case_notes_case_time (case_id, created_at),
  CONSTRAINT fk_cn_case     FOREIGN KEY (case_id)          REFERENCES cases (case_id),
  CONSTRAINT fk_cn_author   FOREIGN KEY (author_id)        REFERENCES users (user_id),
  CONSTRAINT fk_cn_corrects FOREIGN KEY (corrects_note_id) REFERENCES case_notes (note_id),
  CONSTRAINT chk_cn_text CHECK (CHAR_LENGTH(TRIM(note_text)) >= 2)
) ENGINE = InnoDB;

DELIMITER $$

CREATE TRIGGER trg_cn_no_update BEFORE UPDATE ON case_notes FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case notes cannot be edited. Add a correction note instead.';
END$$

CREATE TRIGGER trg_cn_no_delete BEFORE DELETE ON case_notes FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case notes cannot be deleted.';
END$$

CREATE TRIGGER trg_cn_before_insert BEFORE INSERT ON case_notes FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(20);
  DECLARE v_corrected_case INT UNSIGNED;
  SELECT status INTO v_status FROM cases WHERE case_id = NEW.case_id;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Notes cannot be added to a closed case.';
  END IF;
  IF NEW.corrects_note_id IS NOT NULL THEN
    SELECT case_id INTO v_corrected_case FROM case_notes WHERE note_id = NEW.corrects_note_id;
    IF v_corrected_case IS NULL OR v_corrected_case <> NEW.case_id THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A correction must refer to a note on the same case.';
    END IF;
  END IF;
END$$

DELIMITER ;

GRANT INSERT ON forge_x_db.case_notes TO 'forge_x_app_role';

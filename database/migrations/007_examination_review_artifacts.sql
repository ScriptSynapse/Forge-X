-- =====================================================================
-- FORGE-X  |  database/migrations/007_examination_review_artifacts.sql
-- FORGE-X 2.0 Phase 5 (decision U3: independent examination review).
-- Run ONCE, as root, on a database built before this change:
--   mysql -u root -p -e "source database/migrations/007_examination_review_artifacts.sql"
--
-- Adds to examinations: status 'Under Review', conclusion, submitted_at,
--   reviewed_by / reviewed_at / review_note, an independent-reviewer CHECK,
--   and a wider chk_exam_state (every existing row still passes).
-- Adds trigger trg_exam_finalised: an examination becomes Completed only
--   from Under Review with a reviewer; Completed and Cancelled examinations
--   can't be changed at all. Existing completed rows stay valid.
-- Adds examination_artifacts: append-only artifacts (3 triggers) recorded
--   only while the examination is open, for evidence linked to it.
-- Replaces sp_close_case so examinations Under Review also block closure.
-- =====================================================================
USE forge_x_db;

ALTER TABLE examinations
  MODIFY status ENUM('Pending','In Progress','Completed','Cancelled','Under Review') NOT NULL DEFAULT 'Pending',
  ADD COLUMN conclusion   TEXT         NULL AFTER findings,
  ADD COLUMN submitted_at DATETIME     NULL AFTER started_at,
  ADD COLUMN reviewed_by  INT UNSIGNED NULL AFTER completed_at,
  ADD COLUMN reviewed_at  DATETIME     NULL AFTER reviewed_by,
  ADD COLUMN review_note  VARCHAR(500) NULL AFTER reviewed_at,
  ADD CONSTRAINT fk_exam_reviewer FOREIGN KEY (reviewed_by) REFERENCES users (user_id),
  ADD CONSTRAINT chk_exam_independent CHECK (reviewed_by IS NULL OR reviewed_by <> examiner_id),
  DROP CHECK chk_exam_state,
  ADD CONSTRAINT chk_exam_state CHECK (
       (status = 'Pending'      AND started_at IS NULL     AND completed_at IS NULL)
    OR (status = 'In Progress'  AND started_at IS NOT NULL AND completed_at IS NULL)
    OR (status = 'Under Review' AND started_at IS NOT NULL AND completed_at IS NULL AND submitted_at IS NOT NULL
                                AND tools_methods IS NOT NULL AND findings IS NOT NULL)
    OR (status = 'Completed'    AND started_at IS NOT NULL AND completed_at IS NOT NULL
                                AND completed_at >= started_at
                                AND tools_methods IS NOT NULL AND findings IS NOT NULL)
    OR (status = 'Cancelled'    AND cancel_reason IS NOT NULL));

CREATE TABLE examination_artifacts (
  artifact_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  examination_id       INT UNSIGNED NOT NULL,
  evidence_id          INT UNSIGNED NULL,
  artifact_type        ENUM('File','Registry entry','Log entry','Network indicator','Email','Other') NOT NULL,
  description          VARCHAR(500) NOT NULL,
  location             VARCHAR(500) NULL,
  sha256               CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  corrects_artifact_id INT UNSIGNED NULL,
  recorded_by          INT UNSIGNED NOT NULL,
  recorded_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (artifact_id),
  KEY idx_artifacts_exam (examination_id, recorded_at),
  KEY idx_artifacts_sha256 (sha256),
  CONSTRAINT fk_art_exam     FOREIGN KEY (examination_id)       REFERENCES examinations (examination_id),
  CONSTRAINT fk_art_evidence FOREIGN KEY (evidence_id)          REFERENCES evidence (evidence_id),
  CONSTRAINT fk_art_user     FOREIGN KEY (recorded_by)          REFERENCES users (user_id),
  CONSTRAINT fk_art_corrects FOREIGN KEY (corrects_artifact_id) REFERENCES examination_artifacts (artifact_id),
  CONSTRAINT chk_art_sha256  CHECK (sha256 IS NULL OR sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_art_text    CHECK (CHAR_LENGTH(TRIM(description)) >= 2)
) ENGINE = InnoDB;

DELIMITER $$

CREATE TRIGGER trg_exam_finalised BEFORE UPDATE ON examinations FOR EACH ROW
BEGIN
  IF OLD.status IN ('Completed', 'Cancelled') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Completed and cancelled examinations cannot be changed.';
  END IF;
  IF NEW.status = 'Completed' AND (OLD.status <> 'Under Review' OR NEW.reviewed_by IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An examination is completed only by an independent review.';
  END IF;
END$$

CREATE TRIGGER trg_art_no_update BEFORE UPDATE ON examination_artifacts FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Artifacts cannot be edited. Record a correction instead.';
END$$

CREATE TRIGGER trg_art_no_delete BEFORE DELETE ON examination_artifacts FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Artifacts cannot be deleted.';
END$$

CREATE TRIGGER trg_art_before_insert BEFORE INSERT ON examination_artifacts FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(20);
  DECLARE v_other_exam INT UNSIGNED;
  SELECT status INTO v_status FROM examinations WHERE examination_id = NEW.examination_id;
  IF v_status NOT IN ('Pending', 'In Progress') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Artifacts can only be recorded while the examination is open.';
  END IF;
  IF NEW.evidence_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM examination_evidence WHERE examination_id = NEW.examination_id AND evidence_id = NEW.evidence_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The artifact must come from evidence linked to this examination.';
  END IF;
  IF NEW.corrects_artifact_id IS NOT NULL THEN
    SELECT examination_id INTO v_other_exam FROM examination_artifacts WHERE artifact_id = NEW.corrects_artifact_id;
    IF v_other_exam IS NULL OR v_other_exam <> NEW.examination_id THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A correction must refer to an artifact of the same examination.';
    END IF;
  END IF;
END$$

DROP PROCEDURE IF EXISTS sp_close_case$$
CREATE PROCEDURE sp_close_case(
  IN p_case_id   INT UNSIGNED,
  IN p_summary   VARCHAR(1000),
  IN p_closed_by INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status    VARCHAR(20) DEFAULT NULL;
  DECLARE v_reference CHAR(12);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT status, case_reference INTO v_status, v_reference
    FROM cases WHERE case_id = p_case_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The case is already closed.';
  END IF;
  IF NOT (fn_has_role(p_closed_by, 'Administrator') OR fn_is_case_lead(p_closed_by, p_case_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only an administrator or the lead investigator can close a case.';
  END IF;
  IF p_summary IS NULL OR CHAR_LENGTH(TRIM(p_summary)) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A closure summary is required.';
  END IF;
  IF EXISTS (SELECT 1 FROM examinations
              WHERE case_id = p_case_id AND status IN ('Pending','In Progress','Under Review')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Complete or cancel all examinations (including those under review) before closing the case.';
  END IF;
  IF EXISTS (SELECT 1 FROM evidence
              WHERE case_id = p_case_id
                AND current_status IN ('In Transit','Checked Out','Under Examination')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Return all evidence to storage before closing the case.';
  END IF;

  UPDATE cases
     SET status = 'Closed', closed_at = NOW(), closure_summary = p_summary
   WHERE case_id = p_case_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_closed_by, 'case.close', 'Case', v_reference, 'Success', 'Case closed', @app_ip);

  COMMIT;
END$$

DELIMITER ;

GRANT INSERT ON forge_x_db.examination_artifacts TO 'forge_x_app_role';

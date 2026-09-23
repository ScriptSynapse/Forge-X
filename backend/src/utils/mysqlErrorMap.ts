import { ApiError } from './ApiError';

interface MySqlErrorLike {
  code?: string;
  errno?: number;
  sqlMessage?: string;
  sqlState?: string;
}

/**
 * Every stored procedure and trigger in database/07_procedures.sql and
 * database/08_triggers.sql raises business-rule failures with
 * `SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '<already human-readable>'`.
 * Those come back to Node as a MySQL error with errno 1644 and the
 * exact message we wrote in SQL — so for that one case, the safest AND
 * most helpful thing to do is pass that message straight through as a
 * 400 Bad Request. This is not an accident: it is why every SIGNAL
 * message in the SQL layer was written in plain English addressed to
 * an API caller, not as an internal debug string.
 *
 * Everything else is a genuine constraint the API layer didn't already
 * catch in its own validation (defense in depth) — mapped to a
 * sensible HTTP status without leaking raw SQL identifiers to the
 * client.
 */
export function mapMySqlError(err: unknown): ApiError {
  const e = err as MySqlErrorLike;

  if (e && typeof e === 'object') {
    switch (e.errno) {
      case 1644: // ER_SIGNAL_EXCEPTION — our own SIGNAL SQLSTATE '45000' messages
        return ApiError.badRequest(e.sqlMessage ?? 'The database rejected this operation.');
      case 3819: // ER_CHECK_CONSTRAINT_VIOLATED
        return ApiError.badRequest(`Constraint violation: ${e.sqlMessage ?? 'invalid data.'}`);
      case 1062: // ER_DUP_ENTRY
        return ApiError.conflict('A record with this unique value already exists.', e.sqlMessage);
      case 1451: // ER_ROW_IS_REFERENCED_2 — FK RESTRICT blocked a delete/update
        return ApiError.conflict(
          'This record cannot be modified or deleted because other records still reference it.',
          e.sqlMessage
        );
      case 1452: // ER_NO_REFERENCED_ROW_2 — FK points at a row that doesn't exist
        return ApiError.badRequest('This request refers to a record that does not exist.', e.sqlMessage);
      case 1265: // ER_WARN_DATA_TRUNCATED — usually an invalid ENUM value under strict mode
      case 1366: // ER_TRUNCATED_WRONG_VALUE_FOR_FIELD
        return ApiError.badRequest('One or more field values are not valid for this record.', e.sqlMessage);
      case 1406: // ER_DATA_TOO_LONG
        return ApiError.badRequest('One or more field values are too long.', e.sqlMessage);
      default:
        break;
    }
  }

  return ApiError.internal('An unexpected database error occurred.');
}

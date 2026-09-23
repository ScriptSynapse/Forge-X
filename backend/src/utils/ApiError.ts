/**
 * A deliberate, expected API error (bad input, not found, unauthorized,
 * a business rule rejected by a stored procedure's SIGNAL, etc).
 * Thrown from anywhere in a route/controller and caught by the single
 * central error-handling middleware in middleware/errorHandler.ts.
 */
export class ApiError extends Error {
  public readonly statusCode: number;
  public readonly details?: unknown;

  constructor(statusCode: number, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.details = details;
  }

  static badRequest(message: string, details?: unknown) {
    return new ApiError(400, message, details);
  }
  static unauthorized(message = 'Authentication required.') {
    return new ApiError(401, message);
  }
  static forbidden(message = 'You do not have permission to perform this action.') {
    return new ApiError(403, message);
  }
  static notFound(message = 'Resource not found.') {
    return new ApiError(404, message);
  }
  static conflict(message: string, details?: unknown) {
    return new ApiError(409, message, details);
  }
  static internal(message = 'Internal server error.') {
    return new ApiError(500, message);
  }
}

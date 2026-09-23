import { NextFunction, Request, Response } from 'express';
import { ZodError } from 'zod';
import { ApiError } from '../utils/ApiError';
import { mapMySqlError } from '../utils/mysqlErrorMap';
import { env } from '../config/env';

/** Anything with a numeric `errno` is treated as a MySQL driver error. */
function looksLikeMySqlError(err: unknown): boolean {
  return typeof err === 'object' && err !== null && 'errno' in err && typeof (err as any).errno === 'number';
}

/**
 * The single place every error in the app is turned into an HTTP
 * response. Must be registered LAST, after all routes, per Express
 * convention (4-argument signature is what makes Express treat this
 * as an error handler).
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function errorHandler(err: unknown, req: Request, res: Response, _next: NextFunction): void {
  let apiError: ApiError;

  if (err instanceof ApiError) {
    apiError = err;
  } else if (err instanceof ZodError) {
    apiError = ApiError.badRequest(
      'Validation failed.',
      err.issues.map((i) => ({ path: i.path.join('.'), message: i.message }))
    );
  } else if (looksLikeMySqlError(err)) {
    apiError = mapMySqlError(err);
  } else {
    apiError = ApiError.internal();
  }

  if (apiError.statusCode >= 500) {
    // eslint-disable-next-line no-console
    console.error(`[${new Date().toISOString()}] ${req.method} ${req.originalUrl} ->`, err);
  }

  res.status(apiError.statusCode).json({
    error: {
      message: apiError.message,
      ...(apiError.details ? { details: apiError.details } : {}),
      // Stack traces only ever leave the process in development.
      ...(env.nodeEnv === 'development' && apiError.statusCode >= 500 && err instanceof Error
        ? { stack: err.stack }
        : {}),
    },
  });
}

export function notFoundHandler(req: Request, res: Response): void {
  res.status(404).json({ error: { message: `No route matches ${req.method} ${req.originalUrl}.` } });
}

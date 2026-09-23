import { NextFunction, Request, RequestHandler, Response } from 'express';

/**
 * Wraps an async Express handler so any rejected promise (thrown
 * error, including a MySQL error from an awaited query) is forwarded
 * to next(err) instead of crashing the process or hanging the request.
 * Every controller in this project uses this wrapper.
 */
export function asyncHandler(
  fn: (req: Request, res: Response, next: NextFunction) => Promise<unknown>
): RequestHandler {
  return (req, res, next) => {
    Promise.resolve(fn(req, res, next)).catch(next);
  };
}

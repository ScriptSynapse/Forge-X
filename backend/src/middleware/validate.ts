import { NextFunction, Request, Response } from 'express';
import { AnyZodObject, ZodEffects } from 'zod';

type Schema = AnyZodObject | ZodEffects<AnyZodObject>;

/**
 * Validates req.body / req.params / req.query against a Zod schema
 * shaped like { body?, params?, query? }. Throws a ZodError on failure,
 * which the central errorHandler turns into a clean 400 response
 * listing every invalid field. This is the project's primary input-
 * validation and SQL-injection defense layer for shape/type checking
 * (parameterized queries in config/db.ts are the second, structural
 * layer — user input never reaches SQL as raw text either way).
 */
export function validate(schema: Schema) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    const parsed = schema.parse({
      body: req.body,
      params: req.params,
      query: req.query,
    }) as { body?: unknown; params?: unknown; query?: unknown };

    if (parsed.body !== undefined) req.body = parsed.body;
    if (parsed.params !== undefined) req.params = parsed.params as typeof req.params;
    if (parsed.query !== undefined) req.query = parsed.query as typeof req.query;

    next();
  };
}

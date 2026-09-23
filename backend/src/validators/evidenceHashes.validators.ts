import { z } from 'zod';

const hashAlgorithmEnum = z.enum(['MD5', 'SHA1', 'SHA256', 'SHA512']);

export const listHashesSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ evidenceId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createHashSchema = z.object({
  body: z.object({
    hashAlgorithm: hashAlgorithmEnum,
    hashValue: z.string().min(8).max(128),
    isOriginal: z.boolean().optional(),
  }),
  params: z.object({ evidenceId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateHashInput = z.infer<typeof createHashSchema>['body'];

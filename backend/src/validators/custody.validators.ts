import { z } from 'zod';

export const listCustodyForEvidenceSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ evidenceId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const listCustodySchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    fromDate: z.string().optional(),
    toDate: z.string().optional(),
  }),
});

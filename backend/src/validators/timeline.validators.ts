import { z } from 'zod';

export const listTimelineSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ caseId: z.string().regex(/^\d+$/) }),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
  }),
});

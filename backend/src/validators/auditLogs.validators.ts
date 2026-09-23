import { z } from 'zod';

export const listAuditLogsSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    tableName: z.string().max(64).optional(),
    recordId: z.string().regex(/^\d+$/).optional(),
    userId: z.string().regex(/^\d+$/).optional(),
    actionType: z.enum(['INSERT', 'UPDATE', 'DELETE']).optional(),
    fromDate: z.string().optional(),
    toDate: z.string().optional(),
  }),
});

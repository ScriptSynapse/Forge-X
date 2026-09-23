import { z } from 'zod';

const reportStatusEnum = z.enum(['draft', 'submitted', 'under_review', 'approved', 'finalized']);

export const listReportsSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    caseId: z.string().regex(/^\d+$/).optional(),
    status: reportStatusEnum.optional(),
  }),
});

export const getReportSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createReportSchema = z.object({
  body: z.object({
    caseId: z.number().int().positive(),
    reportNumber: z.string().min(3).max(50),
    title: z.string().min(3).max(200),
    filePath: z.string().min(1).max(500),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const updateReportStatusSchema = z.object({
  body: z.object({
    reportStatus: reportStatusEnum,
    reviewedBy: z.number().int().positive().nullable().optional(),
  }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const addReportVersionSchema = z.object({
  body: z.object({
    filePath: z.string().min(1).max(500),
    changeSummary: z.string().max(500).nullable().optional(),
  }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateReportInput = z.infer<typeof createReportSchema>['body'];
export type UpdateReportStatusInput = z.infer<typeof updateReportStatusSchema>['body'];
export type AddReportVersionInput = z.infer<typeof addReportVersionSchema>['body'];

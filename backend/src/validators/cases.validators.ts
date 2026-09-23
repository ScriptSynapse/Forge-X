import { z } from 'zod';

const caseStatusEnum = z.enum([
  'open',
  'under_investigation',
  'pending_review',
  'closed',
  'archived',
  'cold',
]);
const casePriorityEnum = z.enum(['low', 'medium', 'high', 'critical']);

export const listCasesSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    status: caseStatusEnum.optional(),
    priority: casePriorityEnum.optional(),
    caseTypeId: z.string().regex(/^\d+$/).optional(),
    search: z.string().max(200).optional(),
  }),
});

export const getCaseSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/, 'id must be numeric') }),
  query: z.object({}).optional(),
});

export const createCaseSchema = z.object({
  body: z.object({
    caseNumber: z.string().min(3).max(40),
    caseTitle: z.string().min(3).max(200),
    caseTypeId: z.number().int().positive(),
    priority: casePriorityEnum.optional(),
    jurisdictionLocationId: z.number().int().positive().optional().nullable(),
    description: z.string().max(65535).optional().nullable(),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const updateCaseSchema = z.object({
  body: z.object({
    caseTitle: z.string().min(3).max(200).optional(),
    priority: casePriorityEnum.optional(),
    jurisdictionLocationId: z.number().int().positive().nullable().optional(),
    description: z.string().max(65535).nullable().optional(),
  }).refine((b) => Object.keys(b).length > 0, { message: 'At least one field must be provided.' }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const updateCaseStatusSchema = z.object({
  body: z.object({
    status: caseStatusEnum,
  }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateCaseInput = z.infer<typeof createCaseSchema>['body'];
export type UpdateCaseInput = z.infer<typeof updateCaseSchema>['body'];

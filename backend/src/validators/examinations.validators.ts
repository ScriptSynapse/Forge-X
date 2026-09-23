import { z } from 'zod';

const examinationTypeEnum = z.enum([
  'static_analysis', 'dynamic_analysis', 'data_recovery', 'malware_analysis',
  'network_analysis', 'file_carving', 'timeline_analysis', 'other',
]);
const examinationStatusEnum = z.enum(['scheduled', 'in_progress', 'completed', 'peer_reviewed']);

export const listExaminationsSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    evidenceId: z.string().regex(/^\d+$/).optional(),
    status: examinationStatusEnum.optional(),
  }),
});

export const getExaminationSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createExaminationSchema = z.object({
  body: z.object({
    evidenceId: z.number().int().positive(),
    toolId: z.number().int().positive(),
    examinationType: examinationTypeEnum,
    startedAt: z.string().optional(),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const updateExaminationSchema = z.object({
  body: z.object({
    examinationStatus: examinationStatusEnum.optional(),
    findingsSummary: z.string().max(65535).nullable().optional(),
    completedAt: z.string().nullable().optional(),
  }).refine((b) => Object.keys(b).length > 0, { message: 'At least one field must be provided.' }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateExaminationInput = z.infer<typeof createExaminationSchema>['body'];
export type UpdateExaminationInput = z.infer<typeof updateExaminationSchema>['body'];

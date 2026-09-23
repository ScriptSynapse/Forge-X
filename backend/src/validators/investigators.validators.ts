import { z } from 'zod';

const roleInCaseEnum = z.enum(['lead_investigator', 'co_investigator', 'forensic_analyst', 'supervisor', 'consultant']);

export const listInvestigatorsSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ caseId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const assignInvestigatorSchema = z.object({
  body: z.object({
    userId: z.number().int().positive(),
    roleInCase: roleInCaseEnum,
  }),
  params: z.object({ caseId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const unassignInvestigatorSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ caseId: z.string().regex(/^\d+$/), userId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type AssignInvestigatorInput = z.infer<typeof assignInvestigatorSchema>['body'];

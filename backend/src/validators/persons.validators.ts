import { z } from 'zod';

const genderEnum = z.enum(['male', 'female', 'other', 'unknown']);
const personRoleEnum = z.enum(['suspect', 'victim', 'witness', 'complainant', 'person_of_interest', 'owner']);

export const listPersonsSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    search: z.string().max(200).optional(),
  }),
});

export const getPersonSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createPersonSchema = z.object({
  body: z.object({
    firstName: z.string().min(1).max(100),
    lastName: z.string().min(1).max(100),
    dateOfBirth: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable().optional(),
    nationalIdNumber: z.string().max(50).nullable().optional(),
    gender: genderEnum.optional(),
    phoneNumber: z.string().max(20).nullable().optional(),
    email: z.string().email().max(150).nullable().optional(),
    address: z.string().max(65535).nullable().optional(),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const linkPersonToCaseSchema = z.object({
  body: z.object({
    personId: z.number().int().positive(),
    personRole: personRoleEnum,
    notes: z.string().max(500).nullable().optional(),
  }),
  params: z.object({ caseId: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreatePersonInput = z.infer<typeof createPersonSchema>['body'];
export type LinkPersonToCaseInput = z.infer<typeof linkPersonToCaseSchema>['body'];

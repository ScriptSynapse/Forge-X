import { z } from 'zod';

export const listUsersSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    roleId: z.string().regex(/^\d+$/).optional(),
    departmentId: z.string().regex(/^\d+$/).optional(),
    isActive: z.enum(['0', '1']).optional(),
  }),
});

export const getUserSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const updateUserSchema = z.object({
  body: z.object({
    fullName: z.string().min(1).max(150).optional(),
    roleId: z.number().int().positive().optional(),
    departmentId: z.number().int().positive().optional(),
    phoneNumber: z.string().max(20).nullable().optional(),
    isActive: z.boolean().optional(),
  }).refine((b) => Object.keys(b).length > 0, { message: 'At least one field must be provided.' }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type UpdateUserInput = z.infer<typeof updateUserSchema>['body'];

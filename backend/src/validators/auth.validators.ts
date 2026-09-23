import { z } from 'zod';

export const loginSchema = z.object({
  body: z.object({
    username: z.string().min(1, 'username is required'),
    password: z.string().min(1, 'password is required'),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export type LoginInput = z.infer<typeof loginSchema>['body'];

import { z } from 'zod';

const deviceStatusEnum = z.enum(['seized', 'in_lab', 'under_examination', 'returned', 'disposed', 'archived']);

export const listDevicesSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    caseId: z.string().regex(/^\d+$/).optional(),
    serialNumber: z.string().max(100).optional(),
    imei: z.string().max(20).optional(),
  }),
});

export const getDeviceSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createDeviceSchema = z.object({
  body: z.object({
    caseId: z.number().int().positive(),
    deviceTypeId: z.number().int().positive(),
    ownerPersonId: z.number().int().positive().nullable().optional(),
    serialNumber: z.string().max(100).nullable().optional(),
    make: z.string().max(100).nullable().optional(),
    model: z.string().max(100).nullable().optional(),
    imeiNumber: z.string().max(20).nullable().optional(),
    storageCapacityGb: z.number().nonnegative().nullable().optional(),
    seizedLocationId: z.number().int().positive().nullable().optional(),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const updateDeviceSchema = z.object({
  body: z.object({
    deviceStatus: deviceStatusEnum.optional(),
    currentLocationId: z.number().int().positive().nullable().optional(),
    ownerPersonId: z.number().int().positive().nullable().optional(),
  }).refine((b) => Object.keys(b).length > 0, { message: 'At least one field must be provided.' }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateDeviceInput = z.infer<typeof createDeviceSchema>['body'];
export type UpdateDeviceInput = z.infer<typeof updateDeviceSchema>['body'];

import { z } from 'zod';

const acquisitionMethodEnum = z.enum([
  'physical_seizure',
  'logical_extraction',
  'physical_extraction',
  'network_capture',
  'cloud_extraction',
  'manual_documentation',
]);
const integrityStatusEnum = z.enum(['intact', 'compromised', 'under_verification', 'requires_recheck']);
const hashAlgorithmEnum = z.enum(['MD5', 'SHA1', 'SHA256', 'SHA512']);

export const listEvidenceSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({}).optional(),
  query: z.object({
    page: z.string().optional(),
    pageSize: z.string().optional(),
    caseId: z.string().regex(/^\d+$/).optional(),
    integrityStatus: integrityStatusEnum.optional(),
    search: z.string().max(200).optional(),
  }),
});

export const getEvidenceSchema = z.object({
  body: z.object({}).optional(),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const createEvidenceSchema = z.object({
  body: z.object({
    evidenceNumber: z.string().min(3).max(50),
    caseId: z.number().int().positive(),
    deviceId: z.number().int().positive().nullable().optional(),
    evidenceTypeId: z.number().int().positive(),
    description: z.string().min(1).max(65535),
    acquisitionMethod: acquisitionMethodEnum,
    storageLocationId: z.number().int().positive().nullable().optional(),
  }),
  params: z.object({}).optional(),
  query: z.object({}).optional(),
});

export const updateEvidenceSchema = z.object({
  body: z.object({
    description: z.string().min(1).max(65535).optional(),
    integrityStatus: integrityStatusEnum.optional(),
    storageLocationId: z.number().int().positive().nullable().optional(),
    filePath: z.string().max(500).nullable().optional(),
    evidenceTypeId: z.number().int().positive().optional(),
  }).refine((b) => Object.keys(b).length > 0, { message: 'At least one field must be provided.' }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const verifyEvidenceSchema = z.object({
  body: z.object({
    hashAlgorithm: hashAlgorithmEnum,
    freshlyComputedHash: z.string().min(8).max(128),
  }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export const transferEvidenceSchema = z.object({
  body: z.object({
    newCustodianId: z.number().int().positive(),
    expectedCurrentCustodianId: z.number().int().positive().nullable().optional(),
    locationId: z.number().int().positive().nullable().optional(),
    remarks: z.string().max(500).nullable().optional(),
  }),
  params: z.object({ id: z.string().regex(/^\d+$/) }),
  query: z.object({}).optional(),
});

export type CreateEvidenceInput = z.infer<typeof createEvidenceSchema>['body'];
export type UpdateEvidenceInput = z.infer<typeof updateEvidenceSchema>['body'];
export type VerifyEvidenceInput = z.infer<typeof verifyEvidenceSchema>['body'];
export type TransferEvidenceInput = z.infer<typeof transferEvidenceSchema>['body'];

import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { requireCaseAssignmentViaEvidence } from '../middleware/caseAccess';
import {
  listEvidenceSchema,
  getEvidenceSchema,
  createEvidenceSchema,
  updateEvidenceSchema,
  verifyEvidenceSchema,
  transferEvidenceSchema,
} from '../validators/evidence.validators';
import * as evidenceController from '../controllers/evidence.controller';

const router = Router();

router.use(authenticate);

// INVESTIGATOR's list results are scoped to their assigned cases'
// evidence inside the controller (caseScopeSqlFilter), same pattern
// as cases.routes.ts.
router.get('/', requirePermission('evidence', 'read'), validate(listEvidenceSchema), asyncHandler(evidenceController.listEvidence));

router.get(
  '/:id',
  requirePermission('evidence', 'read'),
  requireCaseAssignmentViaEvidence('id'),
  validate(getEvidenceSchema),
  asyncHandler(evidenceController.getEvidence)
);
router.post(
  '/',
  requirePermission('evidence', 'write'),
  validate(createEvidenceSchema),
  asyncHandler(evidenceController.createEvidence)
);
router.put(
  '/:id',
  requirePermission('evidence', 'write'),
  requireCaseAssignmentViaEvidence('id'),
  validate(updateEvidenceSchema),
  asyncHandler(evidenceController.updateEvidence)
);
router.post(
  '/:id/verify',
  requirePermission('evidenceHashes', 'write'),
  requireCaseAssignmentViaEvidence('id'),
  validate(verifyEvidenceSchema),
  asyncHandler(evidenceController.verifyEvidence)
);
router.post(
  '/:id/transfer',
  requirePermission('custodyTransfer', 'write'),
  requireCaseAssignmentViaEvidence('id'),
  validate(transferEvidenceSchema),
  asyncHandler(evidenceController.transferEvidence)
);

export default router;

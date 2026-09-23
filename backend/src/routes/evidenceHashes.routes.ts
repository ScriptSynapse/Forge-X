import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { requireCaseAssignmentViaEvidence } from '../middleware/caseAccess';
import { listHashesSchema, createHashSchema } from '../validators/evidenceHashes.validators';
import * as hashesController from '../controllers/evidenceHashes.controller';

const router = Router({ mergeParams: true });

router.use(authenticate);

router.get(
  '/',
  requirePermission('evidenceHashes', 'read'),
  requireCaseAssignmentViaEvidence('evidenceId'),
  validate(listHashesSchema),
  asyncHandler(hashesController.listHashes)
);
router.post(
  '/',
  requirePermission('evidenceHashes', 'write'),
  requireCaseAssignmentViaEvidence('evidenceId'),
  validate(createHashSchema),
  asyncHandler(hashesController.createHash)
);

export default router;

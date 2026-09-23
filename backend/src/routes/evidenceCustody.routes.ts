import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { requireCaseAssignmentViaEvidence } from '../middleware/caseAccess';
import { listCustodyForEvidenceSchema } from '../validators/custody.validators';
import * as custodyController from '../controllers/custody.controller';

const router = Router({ mergeParams: true });

router.use(authenticate);
router.get(
  '/',
  requirePermission('custody', 'read'),
  requireCaseAssignmentViaEvidence('evidenceId'),
  validate(listCustodyForEvidenceSchema),
  asyncHandler(custodyController.listCustodyForEvidence)
);

export default router;

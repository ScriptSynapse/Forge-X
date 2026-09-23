import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { requireCaseAssignment } from '../middleware/caseAccess';
import { listTimelineSchema } from '../validators/timeline.validators';
import * as timelineController from '../controllers/timeline.controller';

const router = Router({ mergeParams: true });

router.use(authenticate);
router.get(
  '/',
  requirePermission('timeline', 'read'),
  requireCaseAssignment('caseId'),
  validate(listTimelineSchema),
  asyncHandler(timelineController.listTimelineForCase)
);

export default router;

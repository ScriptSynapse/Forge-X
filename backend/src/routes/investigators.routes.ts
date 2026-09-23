import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import {
  listInvestigatorsSchema,
  assignInvestigatorSchema,
  unassignInvestigatorSchema,
} from '../validators/investigators.validators';
import * as investigatorsController from '../controllers/investigators.controller';

// mergeParams so :caseId from the parent router (cases.routes.ts) is visible here
const router = Router({ mergeParams: true });

router.use(authenticate);

// Note: 'investigators' is only granted to ADMIN and LEAD_INVESTIGATOR
// in the permission matrix -- INVESTIGATOR is not listed for this
// resource at all, so no case-scoping middleware is needed here: an
// INVESTIGATOR gets 403 from requirePermission before any row-level
// check would even matter.
router.get('/', requirePermission('investigators', 'read'), validate(listInvestigatorsSchema), asyncHandler(investigatorsController.listInvestigators));
router.post(
  '/',
  requirePermission('investigators', 'write'),
  validate(assignInvestigatorSchema),
  asyncHandler(investigatorsController.assignInvestigator)
);
router.delete(
  '/:userId',
  requirePermission('investigators', 'write'),
  validate(unassignInvestigatorSchema),
  asyncHandler(investigatorsController.unassignInvestigator)
);

export default router;

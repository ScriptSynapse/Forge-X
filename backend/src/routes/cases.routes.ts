import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { requireCaseAssignment } from '../middleware/caseAccess';
import {
  listCasesSchema,
  getCaseSchema,
  createCaseSchema,
  updateCaseSchema,
  updateCaseStatusSchema,
} from '../validators/cases.validators';
import * as casesController from '../controllers/cases.controller';

const router = Router();

router.use(authenticate);

// List filtering for INVESTIGATOR (assigned cases only) is applied
// inside the controller itself (caseScopeSqlFilter) -- a 403 doesn't
// make sense for a list endpoint, so their results are narrowed at
// the SQL layer instead of blocked outright.
router.get('/', requirePermission('cases', 'read'), validate(listCasesSchema), asyncHandler(casesController.listCases));

router.get(
  '/:id',
  requirePermission('cases', 'read'),
  requireCaseAssignment('id'),
  validate(getCaseSchema),
  asyncHandler(casesController.getCase)
);
router.post(
  '/',
  requirePermission('cases', 'write'),
  validate(createCaseSchema),
  asyncHandler(casesController.createCase)
);
router.put(
  '/:id',
  requirePermission('cases', 'write'),
  requireCaseAssignment('id'),
  validate(updateCaseSchema),
  asyncHandler(casesController.updateCase)
);
router.patch(
  '/:id/status',
  requirePermission('cases', 'write'),
  requireCaseAssignment('id'),
  validate(updateCaseStatusSchema),
  asyncHandler(casesController.updateCaseStatus)
);

export default router;

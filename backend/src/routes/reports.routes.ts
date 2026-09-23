import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import {
  listReportsSchema,
  getReportSchema,
  createReportSchema,
  updateReportStatusSchema,
  addReportVersionSchema,
} from '../validators/reports.validators';
import * as reportsController from '../controllers/reports.controller';

const router = Router();

router.use(authenticate);

router.get('/', requirePermission('reports', 'read'), validate(listReportsSchema), asyncHandler(reportsController.listReports));
router.get('/:id', requirePermission('reports', 'read'), validate(getReportSchema), asyncHandler(reportsController.getReport));
router.post(
  '/',
  requirePermission('reports', 'write'),
  validate(createReportSchema),
  asyncHandler(reportsController.createReport)
);
router.patch(
  '/:id/status',
  requirePermission('reports', 'write'),
  validate(updateReportStatusSchema),
  asyncHandler(reportsController.updateReportStatus)
);
router.post(
  '/:id/versions',
  requirePermission('reports', 'write'),
  validate(addReportVersionSchema),
  asyncHandler(reportsController.addReportVersion)
);

export default router;

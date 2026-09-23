import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import * as dashboardController from '../controllers/dashboard.controller';

const router = Router();

router.use(authenticate);
router.use(requirePermission('dashboard', 'read'));
router.get('/summary', asyncHandler(dashboardController.getDashboardSummary));
router.get('/workload', asyncHandler(dashboardController.getInvestigatorWorkload));
router.get('/integrity-alerts', asyncHandler(dashboardController.getIntegrityAlerts));

export default router;

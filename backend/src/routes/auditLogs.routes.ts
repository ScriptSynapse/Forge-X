import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { listAuditLogsSchema } from '../validators/auditLogs.validators';
import * as auditLogsController from '../controllers/auditLogs.controller';

const router = Router();

router.use(authenticate);
// Audit trail is ADMIN-only in the permission matrix -- no other role
// lists it, and it is the most sensitive read surface in the system
// (every user's every tracked change).
router.get(
  '/',
  requirePermission('auditLogs', 'read'),
  validate(listAuditLogsSchema),
  asyncHandler(auditLogsController.listAuditLogs)
);

export default router;

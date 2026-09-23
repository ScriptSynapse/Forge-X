import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import {
  listExaminationsSchema,
  getExaminationSchema,
  createExaminationSchema,
  updateExaminationSchema,
} from '../validators/examinations.validators';
import * as examinationsController from '../controllers/examinations.controller';

const router = Router();

router.use(authenticate);

// 'examinations' is granted only to ADMIN, FORENSIC_ANALYST, and VIEWER
// in the permission matrix -- see config/permissions.ts's header note
// on why LEAD_INVESTIGATOR/INVESTIGATOR aren't listed here even though
// they can still see exam data embedded in an authorized evidence
// response.
router.get('/', requirePermission('examinations', 'read'), validate(listExaminationsSchema), asyncHandler(examinationsController.listExaminations));
router.get('/:id', requirePermission('examinations', 'read'), validate(getExaminationSchema), asyncHandler(examinationsController.getExamination));
router.post(
  '/',
  requirePermission('examinations', 'write'),
  validate(createExaminationSchema),
  asyncHandler(examinationsController.createExamination)
);
router.put(
  '/:id',
  requirePermission('examinations', 'write'),
  validate(updateExaminationSchema),
  asyncHandler(examinationsController.updateExamination)
);

export default router;

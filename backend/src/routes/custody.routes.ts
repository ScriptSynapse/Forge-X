import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { listCustodySchema } from '../validators/custody.validators';
import * as custodyController from '../controllers/custody.controller';

const router = Router();

router.use(authenticate);
// System-wide custody feed is not case-scoped in this API (it has no
// single case context to check against); INVESTIGATOR still has
// 'custody': read in the matrix like every other role, so this stays
// a plain permission check. Per-evidence custody (below,
// evidenceCustody.routes.ts) IS case-scoped, which covers the
// realistic "can this investigator see this item's custody trail"
// question.
router.get('/', requirePermission('custody', 'read'), validate(listCustodySchema), asyncHandler(custodyController.listCustody));

export default router;

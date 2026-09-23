import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { linkPersonToCaseSchema } from '../validators/persons.validators';
import * as personsController from '../controllers/persons.controller';

const router = Router({ mergeParams: true });

router.use(authenticate);

router.post(
  '/',
  requirePermission('persons', 'write'),
  validate(linkPersonToCaseSchema),
  asyncHandler(personsController.linkPersonToCase)
);

export default router;

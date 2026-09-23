import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { listPersonsSchema, getPersonSchema, createPersonSchema } from '../validators/persons.validators';
import * as personsController from '../controllers/persons.controller';

const router = Router();

router.use(authenticate);

router.get('/', requirePermission('persons', 'read'), validate(listPersonsSchema), asyncHandler(personsController.listPersons));
router.get('/:id', requirePermission('persons', 'read'), validate(getPersonSchema), asyncHandler(personsController.getPerson));
router.post(
  '/',
  requirePermission('persons', 'write'),
  validate(createPersonSchema),
  asyncHandler(personsController.createPerson)
);

export default router;

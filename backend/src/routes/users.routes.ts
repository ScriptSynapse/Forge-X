import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { listUsersSchema, getUserSchema, updateUserSchema } from '../validators/users.validators';
import * as usersController from '../controllers/users.controller';

const router = Router();

router.use(authenticate);
// 'users' is ADMIN-only in the permission matrix -- unlike Step 6,
// even reading the user directory now requires ADMIN, since no other
// role lists "Users" as a resource they're granted.
router.use(requirePermission('users', 'read'));

router.get('/', validate(listUsersSchema), asyncHandler(usersController.listUsers));
router.get('/:id', validate(getUserSchema), asyncHandler(usersController.getUser));
router.put(
  '/:id',
  requirePermission('users', 'write'),
  validate(updateUserSchema),
  asyncHandler(usersController.updateUser)
);

export default router;

import { Router } from 'express';
import { asyncHandler } from '../utils/asyncHandler';
import { validate } from '../middleware/validate';
import { authenticate } from '../middleware/authenticate';
import { requirePermission } from '../middleware/authorize';
import { listDevicesSchema, getDeviceSchema, createDeviceSchema, updateDeviceSchema } from '../validators/devices.validators';
import * as devicesController from '../controllers/devices.controller';

const router = Router();

router.use(authenticate);

router.get('/', requirePermission('devices', 'read'), validate(listDevicesSchema), asyncHandler(devicesController.listDevices));
router.get('/:id', requirePermission('devices', 'read'), validate(getDeviceSchema), asyncHandler(devicesController.getDevice));
router.post(
  '/',
  requirePermission('devices', 'write'),
  validate(createDeviceSchema),
  asyncHandler(devicesController.createDevice)
);
router.put(
  '/:id',
  requirePermission('devices', 'write'),
  validate(updateDeviceSchema),
  asyncHandler(devicesController.updateDevice)
);

export default router;

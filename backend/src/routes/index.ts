import { Router } from 'express';

import authRoutes from './auth.routes';
import usersRoutes from './users.routes';
import casesRoutes from './cases.routes';
import investigatorsRoutes from './investigators.routes';
import personsRoutes from './persons.routes';
import casePersonsRoutes from './casePersons.routes';
import devicesRoutes from './devices.routes';
import evidenceRoutes from './evidence.routes';
import evidenceHashesRoutes from './evidenceHashes.routes';
import evidenceCustodyRoutes from './evidenceCustody.routes';
import custodyRoutes from './custody.routes';
import examinationsRoutes from './examinations.routes';
import reportsRoutes from './reports.routes';
import timelineRoutes from './timeline.routes';
import auditLogsRoutes from './auditLogs.routes';
import dashboardRoutes from './dashboard.routes';

const router = Router();

router.use('/auth', authRoutes);
router.use('/users', usersRoutes);

// Cases, and its nested sub-resources
router.use('/cases/:caseId/investigators', investigatorsRoutes);
router.use('/cases/:caseId/persons', casePersonsRoutes);
router.use('/cases/:caseId/timeline', timelineRoutes);
router.use('/cases', casesRoutes);

router.use('/persons', personsRoutes);
router.use('/devices', devicesRoutes);

// Evidence, and its nested sub-resources
router.use('/evidence/:evidenceId/hashes', evidenceHashesRoutes);
router.use('/evidence/:evidenceId/custody', evidenceCustodyRoutes);
router.use('/evidence', evidenceRoutes);

router.use('/custody', custodyRoutes);
router.use('/examinations', examinationsRoutes);
router.use('/reports', reportsRoutes);
router.use('/audit-logs', auditLogsRoutes);
router.use('/dashboard', dashboardRoutes);

export default router;

import express, { Express, Request, Response } from 'express';
import cors from 'cors';
import helmet from 'helmet';
import { env } from './config/env';
import apiRoutes from './routes';
import { errorHandler, notFoundHandler } from './middleware/errorHandler';

export function createApp(): Express {
  const app = express();

  // --- Security middleware ---
  app.use(helmet()); // sensible security headers (CSP, no-sniff, etc.)
  app.use(
    cors({
      origin: env.corsOrigin.split(',').map((s) => s.trim()),
      credentials: true,
    })
  );
  app.use(express.json({ limit: '2mb' })); // also guards against unbounded request bodies

  // --- Health check (no auth — used by uptime monitors / container orchestrators) ---
  app.get('/health', (_req: Request, res: Response) => {
    res.status(200).json({ status: 'ok', service: 'forge-x-backend', timestamp: new Date().toISOString() });
  });

  // --- API routes ---
  app.use('/api', apiRoutes);

  // --- 404 + centralized error handling (must be registered last) ---
  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

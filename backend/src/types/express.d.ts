export interface AuthUser {
  userId: number;
  username: string;
  roleId: number;
  roleName: string;
  departmentId: number;
  fullName: string;
  jti: string;
  exp: number;
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: AuthUser;
    }
  }
}

export {};

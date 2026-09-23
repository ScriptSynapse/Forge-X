export interface PaginationParams {
  page: number;
  pageSize: number;
  offset: number;
}

/** Clamped, safe pagination parsing shared by every list endpoint. */
export function parsePagination(query: Record<string, unknown>): PaginationParams {
  const page = Math.max(1, Number(query.page) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(query.pageSize) || 20));
  return { page, pageSize, offset: (page - 1) * pageSize };
}

export function paginatedResponse<T>(data: T[], total: number, pagination: PaginationParams) {
  return {
    data,
    pagination: {
      page: pagination.page,
      pageSize: pagination.pageSize,
      total,
      totalPages: Math.ceil(total / pagination.pageSize) || 1,
    },
  };
}

"""Small pagination helper used by list pages (cases, evidence, audit logs...).

The page size is applied with SQL LIMIT/OFFSET, so only one page of rows is
ever read from MySQL. COUNT(*) gives the total for the pager.
"""
from dataclasses import dataclass
from math import ceil


def parse_page(value):
    """Turn ?page=... into a safe positive integer (bad input -> page 1)."""
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


@dataclass
class Page:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self):
        return max(1, ceil(self.total / self.per_page)) if self.per_page else 1

    @property
    def offset(self):
        return (self.page - 1) * self.per_page

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def first_item(self):
        return self.offset + 1 if self.total else 0

    @property
    def last_item(self):
        return min(self.offset + self.per_page, self.total)

    def window(self, edge=1, around=2):
        """Page numbers to show, with None where a gap ("…") belongs."""
        shown, last = [], 0
        for n in range(1, self.pages + 1):
            if n <= edge or n > self.pages - edge or abs(n - self.page) <= around:
                if last and n - last > 1:
                    shown.append(None)
                shown.append(n)
                last = n
        return shown

"""Work lease manager."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Lease:
    lease_id: str
    owner: str
    expires_at: float
    canceled: bool = False

    def expired(self) -> bool:
        return time.time() >= self.expires_at


class LeaseManager:
    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}

    def acquire(self, lease_id: str, owner: str, ttl_s: int) -> bool:
        self._cleanup()
        existing = self._leases.get(lease_id)
        if existing and not existing.expired() and not existing.canceled:
            return False
        self._leases[lease_id] = Lease(lease_id=lease_id, owner=owner, expires_at=time.time() + ttl_s)
        return True

    def release(self, lease_id: str, owner: str) -> bool:
        lease = self._leases.get(lease_id)
        if not lease or lease.owner != owner:
            return False
        self._leases.pop(lease_id, None)
        return True

    def cancel(self, lease_id: str) -> bool:
        lease = self._leases.get(lease_id)
        if not lease:
            return False
        lease.canceled = True
        return True

    def is_active(self, lease_id: str) -> bool:
        self._cleanup()
        lease = self._leases.get(lease_id)
        return bool(lease and not lease.canceled and not lease.expired())

    def _cleanup(self) -> None:
        expired = [lid for lid, lease in self._leases.items() if lease.expired() or lease.canceled]
        for lid in expired:
            self._leases.pop(lid, None)

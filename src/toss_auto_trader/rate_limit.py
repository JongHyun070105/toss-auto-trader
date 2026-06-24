from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RateLimitPolicy:
    min_interval_seconds: float = 1.0
    max_calls_per_minute: int = 30
    cooldown_seconds: float = 60.0


@dataclass
class RateLimiter:
    policy: RateLimitPolicy
    call_timestamps: list[float] = field(default_factory=list)
    cooldown_until: float = 0.0

    def can_call(self, now: float | None = None) -> bool:
        now = now or time.time()
        if now < self.cooldown_until:
            return False
        self.call_timestamps = [t for t in self.call_timestamps if now - t < 60]
        if len(self.call_timestamps) >= self.policy.max_calls_per_minute:
            return False
        if self.call_timestamps and now - self.call_timestamps[-1] < self.policy.min_interval_seconds:
            return False
        return True

    def record_call(self, now: float | None = None) -> None:
        self.call_timestamps.append(now or time.time())

    def record_429(self, now: float | None = None) -> None:
        now = now or time.time()
        self.cooldown_until = now + self.policy.cooldown_seconds

    def seconds_until_next_call(self, now: float | None = None) -> float:
        now = now or time.time()
        if now < self.cooldown_until:
            return self.cooldown_until - now
        self.call_timestamps = [t for t in self.call_timestamps if now - t < 60]
        if len(self.call_timestamps) >= self.policy.max_calls_per_minute:
            return max(0.0, 60 - (now - self.call_timestamps[0]))
        if self.call_timestamps:
            return max(0.0, self.policy.min_interval_seconds - (now - self.call_timestamps[-1]))
        return 0.0

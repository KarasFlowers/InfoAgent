import json
import time
import logging
from datetime import datetime
import statistics

from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)

class MetricsService:
    """Service to track and report daily LLM usage metrics."""
    
    @property
    def today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")
        
    async def _get_client(self):
        return await redis_service.get_client()

    async def record_tokens(self, prompt: int, completion: int) -> None:
        """Increment the daily token count."""
        client = await self._get_client()
        if not client:
            return
            
        key = f"metrics:tokens:{self.today_str}"
        try:
            # We use a pipeline for atomic increments
            async with client.pipeline(transaction=True) as pipe:
                pipe.hincrby(key, "prompt_tokens", prompt)
                pipe.hincrby(key, "completion_tokens", completion)
                pipe.hincrby(key, "total_tokens", prompt + completion)
                pipe.expire(key, 86400 * 7)  # keep for 7 days
                await pipe.execute()
        except Exception as e:
            logger.warning("Failed to record tokens in Redis: %s", e)

    async def record_latency(self, duration_sec: float) -> None:
        """Record a summary generation latency (in seconds) to a daily list."""
        client = await self._get_client()
        if not client:
            return
            
        key = f"metrics:latency:summary:{self.today_str}"
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, str(duration_sec))
                pipe.expire(key, 86400 * 7)
                await pipe.execute()
        except Exception as e:
            logger.warning("Failed to record latency in Redis: %s", e)

    async def get_daily_metrics(self, date_str: str | None = None) -> dict:
        """Get aggregated metrics for the given date (default: today)."""
        if not date_str:
            date_str = self.today_str
            
        client = await self._get_client()
        if not client:
            return {"error": "Redis not connected"}
            
        token_key = f"metrics:tokens:{date_str}"
        latency_key = f"metrics:latency:summary:{date_str}"
        
        try:
            tokens = await client.hgetall(token_key)
            latency_strs = await client.lrange(latency_key, 0, -1)
            
            latencies = [float(x) for x in latency_strs if x]
            
            p50 = statistics.median(latencies) if latencies else 0.0
            p99 = statistics.quantiles(latencies, n=100)[-1] if len(latencies) >= 2 else (latencies[0] if latencies else 0.0)
            
            return {
                "date": date_str,
                "tokens": {
                    "prompt": int(tokens.get("prompt_tokens", 0)),
                    "completion": int(tokens.get("completion_tokens", 0)),
                    "total": int(tokens.get("total_tokens", 0))
                },
                "latency": {
                    "count": len(latencies),
                    "p50_sec": round(p50, 2),
                    "p99_sec": round(p99, 2)
                }
            }
        except Exception as e:
            logger.warning("Failed to fetch metrics from Redis: %s", e)
            return {"error": "Failed to fetch metrics"}

metrics_service = MetricsService()

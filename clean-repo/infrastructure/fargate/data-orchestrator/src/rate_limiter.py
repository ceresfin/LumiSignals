"""
Rate Limiter - OANDA API rate limiting for single connection

ARCHITECTURE COMPLIANCE:
- Manages rate limiting for single OANDA API connection
- Prevents hitting OANDA API limits across all 100+ strategies
- Implements token bucket algorithm for burst handling
- Provides fair resource allocation
"""

import asyncio
import time
from typing import Optional
import structlog

logger = structlog.get_logger()


class RateLimiter:
    """
    Token bucket rate limiter for OANDA API requests
    
    Features:
    - Token bucket algorithm
    - Burst request handling
    - Fair queuing
    - Configurable limits
    """
    
    def __init__(self, max_requests_per_second: int = 10, burst_limit: int = 20):
        self.max_requests_per_second = max_requests_per_second
        self.burst_limit = burst_limit
        
        # Token bucket state
        self.tokens = float(burst_limit)
        self.last_update = time.time()
        
        # Request tracking
        self.total_requests = 0
        self.rate_limited_requests = 0
        
        # Asyncio synchronization
        self.lock = asyncio.Lock()
        
        logger.info("Rate limiter initialized", 
                   max_rps=max_requests_per_second,
                   burst_limit=burst_limit)
    
    async def acquire(self, tokens_needed: int = 1) -> bool:
        """
        Acquire tokens for API request
        
        Args:
            tokens_needed: Number of tokens required (default 1)
            
        Returns:
            bool: True if tokens acquired, False if rate limited
        """
        async with self.lock:
            current_time = time.time()
            
            # Add tokens based on elapsed time
            time_elapsed = current_time - self.last_update
            tokens_to_add = time_elapsed * self.max_requests_per_second
            
            self.tokens = min(self.burst_limit, self.tokens + tokens_to_add)
            self.last_update = current_time
            
            self.total_requests += 1
            
            # Check if we have enough tokens
            if self.tokens >= tokens_needed:
                self.tokens -= tokens_needed
                logger.debug("Rate limit tokens acquired", 
                           tokens_used=tokens_needed,
                           tokens_remaining=self.tokens)
                return True
            else:
                self.rate_limited_requests += 1
                
                # Calculate wait time for next token
                wait_time = (tokens_needed - self.tokens) / self.max_requests_per_second
                
                logger.warning("Rate limit exceeded, waiting", 
                             wait_time=f"{wait_time:.2f}s",
                             tokens_needed=tokens_needed,
                             tokens_available=self.tokens)
                
                # Wait for tokens to become available
                await asyncio.sleep(wait_time)
                
                # Recursively try again
                return await self.acquire(tokens_needed)
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics"""
        rate_limited_percentage = 0.0
        if self.total_requests > 0:
            rate_limited_percentage = (self.rate_limited_requests / self.total_requests) * 100
        
        return {
            "max_requests_per_second": self.max_requests_per_second,
            "burst_limit": self.burst_limit,
            "current_tokens": round(self.tokens, 2),
            "total_requests": self.total_requests,
            "rate_limited_requests": self.rate_limited_requests,
            "rate_limited_percentage": round(rate_limited_percentage, 2),
            "last_update": self.last_update
        }
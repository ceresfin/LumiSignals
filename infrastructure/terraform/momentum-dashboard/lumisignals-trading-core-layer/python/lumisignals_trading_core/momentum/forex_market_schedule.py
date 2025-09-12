#!/usr/bin/env python3
"""
ForexMarketSchedule - Forex market trading hours and session management

This module handles forex market schedule logic, timezone conversions,
and trading day calculations for the LumiSignals trading system.

Features:
- Forex market hours (Sunday 5pm EST to Friday 5pm EST)
- Weekend gap handling for momentum calculations
- Start-of-week logic for 24h/48h lookbacks
- Market time conversions (UTC <-> EST/EDT)
"""

import pytz
from datetime import datetime, timedelta
from typing import Optional, Union


class ForexMarketSchedule:
    """
    Handles forex market schedule and trading day logic
    
    The forex market operates:
    - Opens: Sunday 5:00 PM EST/EDT  
    - Closes: Friday 5:00 PM EST/EDT
    - Closed: Saturday and Sunday before 5:00 PM EST/EDT
    """
    
    def __init__(self):
        # Forex market timezone (EST/EDT - automatically handles DST)
        self.market_tz = pytz.timezone('US/Eastern')
        self.utc_tz = pytz.UTC
        
        # Market hours: Sunday 5pm EST to Friday 5pm EST
        self.market_open_day = 6  # Sunday (0=Monday, 6=Sunday)
        self.market_open_hour = 17  # 5 PM EST/EDT
        self.market_close_day = 4  # Friday
        self.market_close_hour = 17  # 5 PM EST/EDT
    
    def get_market_time(self, utc_time: Optional[Union[datetime, str]] = None) -> datetime:
        """
        Convert UTC time to market time (EST/EDT)
        
        Args:
            utc_time: UTC datetime object, ISO string, or None for current time
            
        Returns:
            Market time (EST/EDT) as timezone-aware datetime
        """
        if utc_time is None:
            utc_time = datetime.now(self.utc_tz)
        elif isinstance(utc_time, str):
            # Parse ISO format from OANDA API (e.g., "2025-09-12T17:30:00.000000000Z")
            if utc_time.endswith('Z'):
                # Remove nanoseconds if present
                if '.000000000Z' in utc_time:
                    utc_time = utc_time.replace('.000000000Z', 'Z')
                # Convert to timezone-aware datetime
                utc_time = datetime.fromisoformat(utc_time.replace('Z', '+00:00'))
            else:
                utc_time = datetime.fromisoformat(utc_time)
                
            # Ensure it's UTC
            if utc_time.tzinfo is None:
                utc_time = self.utc_tz.localize(utc_time)
        elif utc_time.tzinfo is None:
            # Assume naive datetime is UTC
            utc_time = self.utc_tz.localize(utc_time)
        
        # Convert to market timezone (handles EST/EDT automatically)
        return utc_time.astimezone(self.market_tz)
    
    def is_market_open(self, market_time: datetime) -> bool:
        """
        Check if forex market is open at given market time
        
        Args:
            market_time: Market time (EST/EDT) datetime object
            
        Returns:
            True if market is open, False if closed
        """
        weekday = market_time.weekday()  # 0=Monday, 6=Sunday
        hour = market_time.hour
        
        # Market closure rules:
        if weekday == 5:  # Saturday - market is closed all day
            return False
        elif weekday == 6:  # Sunday
            return hour >= self.market_open_hour  # Only open from 5pm Sunday onward
        elif weekday == 4:  # Friday
            return hour < self.market_close_hour  # Close at 5pm Friday
        else:  # Monday-Thursday
            return True  # Open 24 hours
    
    def get_last_trading_time(self, from_market_time: datetime, hours_back: Union[int, float]) -> datetime:
        """
        Get the last trading time going back specified hours, with smart weekend handling
        
        This method implements sophisticated start-of-week logic:
        - If looking back 24h+ from early trading week, uses Sunday 5pm market open
        - Otherwise, counts actual trading hours and skips weekend gaps
        
        Args:
            from_market_time: Starting market time (EST/EDT)
            hours_back: How many trading hours to go back
            
        Returns:
            Market time (EST/EDT) that represents the target trading time
        """
        current_time = from_market_time
        
        # Special start-of-week handling for 24h+ lookbacks
        if hours_back >= 24:
            current_weekday = current_time.weekday()  # 0=Monday, 6=Sunday
            current_hour = current_time.hour
            
            # Case 1: We're on Sunday after market open (5pm+)
            if current_weekday == 6 and current_hour >= self.market_open_hour:
                # Both 24h and 48h ago reference Sunday 5pm when trading week started
                sunday_5pm = current_time.replace(
                    hour=self.market_open_hour, 
                    minute=0, 
                    second=0, 
                    microsecond=0
                )
                print(f"START-OF-WEEK: Using Sunday {self.market_open_hour}:00 open for {hours_back}h lookback")
                return sunday_5pm
            
            # Case 2: We're on Monday and looking back would hit the weekend
            elif current_weekday == 0:  # Monday
                # Calculate hours since trading week started (Sunday 5pm)
                last_sunday = current_time - timedelta(days=1)  # Go back to Sunday
                sunday_5pm = last_sunday.replace(
                    hour=self.market_open_hour,
                    minute=0, 
                    second=0, 
                    microsecond=0
                )
                
                # Hours since week started
                time_since_week_start = current_time - sunday_5pm
                hours_since_week_start = time_since_week_start.total_seconds() / 3600
                
                # If looking back further than week start, use Sunday 5pm
                if hours_back > hours_since_week_start:
                    print(f"START-OF-WEEK: Using Sunday {self.market_open_hour}:00 open for {hours_back}h lookback")
                    return sunday_5pm
        
        # Normal trading hour counting for other cases
        hours_remaining = hours_back
        target_time = current_time
        
        while hours_remaining > 0:
            # Move back one hour
            target_time = target_time - timedelta(hours=1)
            
            # Only count the hour if market was open
            if self.is_market_open(target_time):
                hours_remaining -= 1
            # If market was closed, keep going back without counting
        
        return target_time
    
    def get_trading_hours_between(self, start_time: datetime, end_time: datetime) -> int:
        """
        Calculate actual trading hours between two market times
        
        Args:
            start_time: Start market time (EST/EDT)
            end_time: End market time (EST/EDT)
            
        Returns:
            Number of trading hours between the two times
        """
        if start_time > end_time:
            start_time, end_time = end_time, start_time
        
        trading_hours = 0
        current_time = start_time
        
        while current_time < end_time:
            if self.is_market_open(current_time):
                trading_hours += 1
            current_time = current_time + timedelta(hours=1)
        
        return trading_hours
    
    def get_next_market_open(self, from_market_time: Optional[datetime] = None) -> datetime:
        """
        Get the next market open time from a given market time
        
        Args:
            from_market_time: Starting market time, or None for current time
            
        Returns:
            Next market open time (EST/EDT)
        """
        if from_market_time is None:
            from_market_time = self.get_market_time()
        
        # If market is currently open, return current time
        if self.is_market_open(from_market_time):
            return from_market_time
        
        # Find next Sunday 5pm EST
        current_time = from_market_time
        
        while not self.is_market_open(current_time):
            current_time = current_time + timedelta(hours=1)
        
        return current_time
    
    def get_session_info(self, market_time: Optional[datetime] = None) -> dict:
        """
        Get detailed information about current market session
        
        Args:
            market_time: Market time to analyze, or None for current time
            
        Returns:
            Dictionary with session information
        """
        if market_time is None:
            market_time = self.get_market_time()
        
        weekday = market_time.weekday()
        hour = market_time.hour
        is_open = self.is_market_open(market_time)
        
        # Determine session
        session_name = "Unknown"
        if weekday == 6 and hour >= 17:  # Sunday 5pm+
            session_name = "Sydney Open"
        elif weekday == 0 and hour < 8:  # Monday before 8am
            session_name = "Sydney/Tokyo"
        elif weekday in [0, 1, 2, 3] and 8 <= hour < 15:  # Mon-Thu 8am-3pm
            session_name = "London"
        elif weekday in [0, 1, 2, 3] and 15 <= hour < 17:  # Mon-Thu 3pm-5pm
            session_name = "London/NY Overlap"
        elif weekday in [0, 1, 2, 3, 4] and 17 <= hour < 24:  # Mon-Fri 5pm+
            session_name = "New York"
        elif weekday == 4 and hour < 17:  # Friday before 5pm
            session_name = "New York"
        elif weekday == 5:  # Saturday
            session_name = "Market Closed"
        elif weekday == 6 and hour < 17:  # Sunday before 5pm
            session_name = "Market Closed"
        
        return {
            'market_time': market_time.isoformat(),
            'utc_time': market_time.astimezone(self.utc_tz).isoformat(),
            'is_market_open': is_open,
            'session_name': session_name,
            'weekday': market_time.strftime('%A'),
            'next_market_open': self.get_next_market_open(market_time).isoformat() if not is_open else None
        }


# Utility functions for common use cases
def get_current_market_time() -> datetime:
    """Get current market time (EST/EDT)"""
    schedule = ForexMarketSchedule()
    return schedule.get_market_time()


def is_market_currently_open() -> bool:
    """Check if forex market is currently open"""
    schedule = ForexMarketSchedule()
    current_market_time = schedule.get_market_time()
    return schedule.is_market_open(current_market_time)


def get_trading_hours_ago(hours: Union[int, float]) -> datetime:
    """Get market time from specified trading hours ago"""
    schedule = ForexMarketSchedule()
    current_market_time = schedule.get_market_time()
    return schedule.get_last_trading_time(current_market_time, hours)


# Example usage and testing
if __name__ == "__main__":
    import json
    
    schedule = ForexMarketSchedule()
    
    print("=== FOREX MARKET SCHEDULE TESTING ===\n")
    
    # Current session info
    session_info = schedule.get_session_info()
    print("Current Session Info:")
    print(json.dumps(session_info, indent=2))
    
    # Test start-of-week logic
    print(f"\n=== START-OF-WEEK LOGIC TEST ===")
    current_market_time = schedule.get_market_time()
    
    for hours_back in [1, 4, 24, 48]:
        target_time = schedule.get_last_trading_time(current_market_time, hours_back)
        print(f"{hours_back}h ago: {target_time} (Market: {schedule.is_market_open(target_time)})")
    
    print(f"\n=== UTILITY FUNCTIONS ===")
    print(f"Current market time: {get_current_market_time()}")
    print(f"Market currently open: {is_market_currently_open()}")
    print(f"24 trading hours ago: {get_trading_hours_ago(24)}")
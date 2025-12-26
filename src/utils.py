"""Utility functions for GensynRPA."""

import logging
from datetime import datetime, timedelta
from typing import Optional


def setup_logging(name: str = "GensynRPA", level: int = logging.INFO) -> logging.Logger:
    """Setup and return a configured logger."""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(level)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        
        # Format
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse date string in format 'DD.MM.YYYY HH:MM' to datetime.
    
    Args:
        date_str: Date string like '25.12.2025 14:56'
        
    Returns:
        datetime object or None if parsing fails
    """
    if not date_str or not date_str.strip():
        return None
        
    try:
        return datetime.strptime(date_str.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return None


def format_date(dt: datetime) -> str:
    """
    Format datetime to string 'DD.MM.YYYY HH:MM'.
    
    Args:
        dt: datetime object
        
    Returns:
        Formatted date string
    """
    return dt.strftime("%d.%m.%Y %H:%M")


def is_cooldown_passed(date_str: str, cooldown_hours: int = 24) -> bool:
    """
    Check if cooldown period has passed since the given date.
    
    Args:
        date_str: Last work date string in format 'DD.MM.YYYY HH:MM'
        cooldown_hours: Number of hours to wait
        
    Returns:
        True if cooldown has passed or date is empty/invalid
    """
    if not date_str or not date_str.strip():
        return True  # No previous work, can proceed
        
    last_work = parse_date(date_str)
    if last_work is None:
        return True  # Invalid date, assume can proceed
        
    now = datetime.now()
    cooldown_end = last_work + timedelta(hours=cooldown_hours)
    
    return now >= cooldown_end


def get_yes_no_status(date_str: str, cooldown_hours: int = 24) -> str:
    """
    Determine yes/no status based on cooldown.
    
    Args:
        date_str: Last work date string
        cooldown_hours: Cooldown period in hours
        
    Returns:
        'yes' if can work, 'no' otherwise
    """
    return "yes" if is_cooldown_passed(date_str, cooldown_hours) else "no"

from datetime import datetime, timedelta
import calendar
import pandas as pd


def _parse_expiry(expiry_date: str | datetime) -> datetime | None:
    """Safely parse an expiry date string to datetime."""
    if isinstance(expiry_date, datetime):
        return expiry_date
    if isinstance(expiry_date, str):
        for fmt in ["%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"]:
            try:
                return datetime.strptime(expiry_date, fmt)
            except ValueError:
                continue
    return None


def _get_last_tuesday(year: int, month: int) -> datetime:
    """
    Returns the last Tuesday of a given month.
    NSE NIFTY monthly expiry = last Tuesday of the month.
    """
    # Find the last day of the month
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    
    # Walk backward to find Tuesday (weekday 1)
    while dt.weekday() != 1:  # 1 = Tuesday
        dt -= timedelta(days=1)
    return dt


def is_monthly_expiry(expiry_date: str | datetime) -> bool:
    """
    NSE NIFTY Monthly expiry = last Tuesday of the month.
    If that Tuesday is a holiday, NSE shifts it to the previous trading day
    (typically Monday, or Friday if Monday is also a holiday).
    
    Detection logic:
    1. Find the last Tuesday of the expiry's month.
    2. If the expiry date falls within 2 calendar days before the last Tuesday
       (to handle holiday shifts), classify as MONTHLY.
    """
    dt = _parse_expiry(expiry_date)
    if dt is None:
        return False
    
    last_tue = _get_last_tuesday(dt.year, dt.month)
    
    # Exact match: expiry IS the last Tuesday
    if dt.date() == last_tue.date():
        return True
    
    # Holiday shift: expiry is 1-2 days before the last Tuesday
    # (Monday shift = 1 day, Friday shift = 4 days but that's extreme)
    diff = (last_tue - dt).days
    if 1 <= diff <= 2:
        # Additional check: the expiry should be on Mon or Fri 
        # (not mid-week, which would be a different weekly)
        if dt.weekday() in (0, 4):  # Monday=0, Friday=4
            return True
    
    return False


def get_expiry_type(expiry_date: str | datetime) -> str:
    """
    Returns 'MONTHLY' or 'WEEKLY' based on NSE NIFTY expiry rules.
    - Weekly: Every Tuesday
    - Monthly: Last Tuesday of the month (or previous trading day if holiday)
    """
    return "MONTHLY" if is_monthly_expiry(expiry_date) else "WEEKLY"


def sort_expiries(expiries: list[str]) -> list[str]:
    """Sorts a list of DD-Mon-YYYY strings chronologically."""
    def try_parse(x):
        try:
            return datetime.strptime(x, "%d-%b-%Y")
        except (ValueError, IndexError):
            return datetime.max
    return sorted(expiries, key=try_parse)


def get_dte_from_string(expiry_date: str) -> int:
    """Calculates days from today to the given DD-Mon-YYYY expiry."""
    dt = _parse_expiry(expiry_date)
    if dt is None:
        return 7  # Default to weekly fallback if parsing fails
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (dt - today).days
    return max(0, delta)

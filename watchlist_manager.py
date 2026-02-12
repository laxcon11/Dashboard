import json
import os
import logging
from NSE_Config import PRESET_WATCHLISTS

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WATCHLIST_FILE = "watchlists.json"

def load_watchlists():
    """Load watchlists from JSON file or return defaults."""
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading watchlists: {e}")
            return PRESET_WATCHLISTS.copy()
    else:
        # Initialize with presets if file doesn't exist
        save_watchlists(PRESET_WATCHLISTS)
        return PRESET_WATCHLISTS.copy()

def save_watchlists(watchlists):
    """Save watchlists to JSON file."""
    try:
        with open(WATCHLIST_FILE, 'w') as f:
            json.dump(watchlists, f, indent=4)
        logger.info("Watchlists saved successfully.")
        return True
    except Exception as e:
        logger.error(f"Error saving watchlists: {e}")
        return False

def add_watchlist(name, symbols):
    """Add a new watchlist or update existing one."""
    watchlists = load_watchlists()
    watchlists[name] = symbols
    return save_watchlists(watchlists)

def delete_watchlist(name):
    """Delete a watchlist by name."""
    watchlists = load_watchlists()
    if name in watchlists:
        del watchlists[name]
        return save_watchlists(watchlists)
    return False

def get_watchlist_names():
    """Get list of available watchlist names."""
    watchlists = load_watchlists()
    return list(watchlists.keys())

def get_symbols(name):
    """Get symbols for a specific watchlist."""
    watchlists = load_watchlists()
    return watchlists.get(name, [])

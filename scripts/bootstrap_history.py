"""
Bootstrap Historical Data for Nifty 200
Backfills 1 year of OHLCV data into the local history parquet 
to prime the 200DMA breadth indicator.
"""

import sys
import logging
from pathlib import Path
import pandas as pd

# Add ROOT to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_fetch import batch_download, persist_local_nse_updates
from NSE_Config import NIFTY_200

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def bootstrap():
    logger.info("Starting historical bootstrap for %d symbols (NIFTY 200)", len(NIFTY_200))
    
    # Using 1y to ensure we have significantly more than 200 trading days
    # (Approx 252 trading days in a year)
    period = "1y"
    
    # Download in chunks to avoid overwhelming API or memory
    chunk_size = 50
    chunks = [NIFTY_200[i:i + chunk_size] for i in range(0, len(NIFTY_200), chunk_size)]
    
    total_downloaded = 0
    
    for i, chunk in enumerate(chunks):
        logger.info("Processing chunk %d/%d (%d symbols)...", i+1, len(chunks), len(chunk))
        
        try:
            # Download 1y history
            data = batch_download(chunk, period=period)
            
            # Filter out empty results
            valid_updates = {s: df for s, df in data.items() if df is not None and not df.empty}
            
            if valid_updates:
                # Persist to local nse_230_history.parquet
                persist_local_nse_updates(valid_updates)
                total_downloaded += len(valid_updates)
                logger.info("Successfully persisted %d symbols in this chunk.", len(valid_updates))
            else:
                logger.warning("No valid data received for this chunk.")
                
        except Exception as e:
            logger.error("Error processing chunk %d: %s", i+1, e)

    logger.info("Bootstrap complete. Total symbols primed with 1y history: %d/%d", 
                total_downloaded, len(NIFTY_200))

if __name__ == "__main__":
    bootstrap()

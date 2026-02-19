"""
Unit Tests for NSE Dashboard Indicators
Tests RSI, EMA, ATR calculations against known values
"""

import unittest
import pandas as pd
from datetime import datetime
import os
import sys

# Adjust path to import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analytics

class TestIndicatorCalculations(unittest.TestCase):
    
    def setUp(self):
        """Create sample data for testing"""
        # Create 50 days of sample price data
        dates = pd.date_range(end=datetime.now(), periods=50, freq='D')
        
        # Sample closing prices (known pattern for testing)
        self.sample_data = pd.DataFrame({
            'Close': [
                100, 102, 101, 103, 105, 104, 106, 108, 107, 109,
                111, 110, 112, 114, 113, 115, 117, 116, 118, 120,
                119, 121, 123, 122, 124, 126, 125, 127, 129, 128,
                130, 132, 131, 133, 135, 134, 136, 138, 137, 139,
                141, 140, 142, 144, 143, 145, 147, 146, 148, 150
            ],
            'High': [
                102, 104, 103, 105, 107, 106, 108, 110, 109, 111,
                113, 112, 114, 116, 115, 117, 119, 118, 120, 122,
                121, 123, 125, 124, 126, 128, 127, 129, 131, 130,
                132, 134, 133, 135, 137, 136, 138, 140, 139, 141,
                143, 142, 144, 146, 145, 147, 149, 148, 150, 152
            ],
            'Low': [
                99, 101, 100, 102, 104, 103, 105, 107, 106, 108,
                110, 109, 111, 113, 112, 114, 116, 115, 117, 119,
                118, 120, 122, 121, 123, 125, 124, 126, 128, 127,
                129, 131, 130, 132, 134, 133, 135, 137, 136, 138,
                140, 139, 141, 143, 142, 144, 146, 145, 147, 149
            ],
            'Open': [
                100, 102, 101, 103, 105, 104, 106, 108, 107, 109,
                111, 110, 112, 114, 113, 115, 117, 116, 118, 120,
                119, 121, 123, 122, 124, 126, 125, 127, 129, 128,
                130, 132, 131, 133, 135, 134, 136, 138, 137, 139,
                141, 140, 142, 144, 143, 145, 147, 146, 148, 150
            ],
            'Volume': [100000] * 50
        }, index=dates)
    
    def test_rsi_calculation_range(self):
        """Test RSI is within 0-100 range"""
        rsi = analytics.calculate_rsi(self.sample_data, period=14)
        valid_rsi = rsi.dropna()
        self.assertTrue((valid_rsi >= 0).all())
        self.assertTrue((valid_rsi <= 100).all())
    
    def test_rsi_uptrend(self):
        """Test RSI in strong uptrend (should be > 50)"""
        rsi = analytics.calculate_rsi(self.sample_data, period=14)
        recent_rsi = rsi.tail(10).mean()
        self.assertGreater(recent_rsi, 50, "RSI should be > 50 in uptrend")
    
    def test_ema_calculation(self):
        """Test EMA is calculated correctly"""
        ema_20 = analytics.calculate_ema(self.sample_data, 20)
        self.assertFalse(ema_20.isnull().all())
        self.assertGreater(ema_20.iloc[-1], ema_20.iloc[-10])
    
    def test_ema_ordering(self):
        """Test EMA ordering in uptrend (shorter EMA > longer EMA)"""
        ema_20 = analytics.calculate_ema(self.sample_data, 20)
        ema_50 = analytics.calculate_ema(self.sample_data, 50)
        self.assertGreater(ema_20.iloc[-1], ema_50.iloc[-1])
    
    def test_atr_positive(self):
        """Test ATR is always positive"""
        atr = analytics.calculate_atr(self.sample_data, period=14)
        valid_atr = atr.dropna()
        self.assertTrue((valid_atr > 0).all(), "ATR should always be positive")
    
    def test_gap_detection(self):
        """Test gap detection logic"""
        # Create data with known gap
        gap_data = self.sample_data.copy()
        gap_data['Open'] = gap_data['Open'].astype(float)
        gap_data.loc[gap_data.index[-1], 'Open'] = gap_data['Close'].iloc[-2] * 1.03  # 3% gap
        gap, gap_pct = analytics.detect_gap(gap_data)
        self.assertAlmostEqual(gap_pct, 3.0, delta=0.5)
    
    def test_breakout_detection(self):
        """Test breakout detection"""
        # Create breakout scenario
        breakout_data = self.sample_data.copy()
        prior_high = breakout_data['High'].iloc[-21:-1].max()
        breakout_data.loc[breakout_data.index[-1], 'Close'] = prior_high + 5
        signal = analytics.detect_breakout(breakout_data, window=20)
        self.assertTrue(signal)
    
    def test_volume_ratio(self):
        """Test volume ratio calculation"""
        # Create data with high volume
        vol_data = self.sample_data.copy()
        vol_data.loc[vol_data.index[-1], 'Volume'] = 300000  # 3x average
        ratio = analytics.calculate_volume_ratio(vol_data)
        self.assertAlmostEqual(ratio, 3.0, delta=0.5)
    
    def test_division_by_zero_protection(self):
        """Test that division by zero doesn't crash"""
        # Create data with zero volume
        zero_vol_data = self.sample_data.copy()
        zero_vol_data['Volume'] = 0
        ratio = analytics.calculate_volume_ratio(zero_vol_data)
        self.assertEqual(ratio, 0)

def run_tests():
    """Run all tests and generate report"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestIndicatorCalculations))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

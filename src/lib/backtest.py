
class BacktestSnapshot:
    def __init__(self, backtest_row_dict):
        """
        Initialize from the new backtest row dictionary structure
        """
        self.date = backtest_row_dict.get('Date')
        self.open = backtest_row_dict.get('Open', 0)
        self.high = backtest_row_dict.get('High', 0)
        self.low = backtest_row_dict.get('Low', 0)
        self.close = backtest_row_dict.get('Close', 0)
        self.prev_close = backtest_row_dict.get('Prev Close', 0)
        self.decision = backtest_row_dict.get('Decision', 'STAY')
        self.entry_price = backtest_row_dict.get('EntryPrice', '')
        self.exit_price = backtest_row_dict.get('ExitPrice', '')
        self.pnl = backtest_row_dict.get('P/L', 0.0)
        self.cumulative_pnl = backtest_row_dict.get('Cum. P/L', 0.0)

    def to_dict(self):
        """
        Convert back to dictionary format for CSV export or analysis
        """
        return {
            'Date': self.date.strftime('%Y-%m-%d') if hasattr(self.date, 'strftime') else str(self.date),
            'Open': self.open,
            'High': self.high,
            'Low': self.low,
            'Close': self.close,
            'Prev Close': self.prev_close,
            'Decision': self.decision,
            'EntryPrice': self.entry_price,
            'ExitPrice': self.exit_price,
            'P/L': self.pnl,
            'Cum. P/L': self.cumulative_pnl
        }
    
    def has_entry(self):
        """Check if this snapshot contains an entry"""
        return self.entry_price != '' and self.entry_price != 0
    
    def has_exit(self):
        """Check if this snapshot contains an exit"""
        return self.exit_price != '' and self.exit_price != 0
    
    def is_profitable(self):
        """Check if this trade was profitable"""
        return self.pnl > 0 if self.pnl != 0 else False

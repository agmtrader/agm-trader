
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
        self.position = backtest_row_dict.get('Position', 0)
        self.portfolio_value = backtest_row_dict.get('Portfolio Value', 0.0)
        self.returns = backtest_row_dict.get('Returns', 0.0)
        self.cumulative_returns = backtest_row_dict.get('Cumulative Returns', 0.0)

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
            'Position': self.position,
            'Portfolio Value': self.portfolio_value,
            'Returns': self.returns,
            'Cumulative Returns': self.cumulative_returns
        }
    
    # Legacy helper methods removed (has_entry, has_exit, is_profitable) as we no longer track individual trades here

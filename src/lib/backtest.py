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
        self.entry_price = backtest_row_dict.get('Entry Price', 0.0)
        self.exit_price = backtest_row_dict.get('Exit Price', 0.0)
        self.realised_pnl = backtest_row_dict.get('Realised PnL', 0.0)
        self.unrealised_pnl = backtest_row_dict.get('Unrealised PnL', 0.0)
        self.cumulative_pnl = backtest_row_dict.get('Cumulative PnL', 0.0)

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
            'Cumulative Returns': self.cumulative_returns,
            'Entry Price': self.entry_price,
            'Exit Price': self.exit_price,
            'Realised PnL': self.realised_pnl,
            'Unrealised PnL': self.unrealised_pnl,
            'Cumulative PnL': self.cumulative_pnl
        }

class TradeSnapshot:
    """Represents a completed trade for backtest output"""

    def __init__(self, side: str, qty: int, entry_date, entry_price: float):
        self.side = side  # 'LONG' or 'SHORT'
        self.qty = qty
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.exit_date = None
        self.exit_price = None
        self.exit_reason = None  # TP / SL / EXIT_SIGNAL / END_OF_DATA

    def close(self, exit_date, exit_price: float, exit_reason: str = None):
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = exit_reason

    @property
    def pnl_abs(self):
        if self.exit_price is None:
            return None
        sign = 1 if self.side == 'LONG' else -1
        return (self.exit_price - self.entry_price) * sign * self.qty

    @property
    def pnl_pct(self):
        if self.pnl_abs is None:
            return None
        return self.pnl_abs / (self.entry_price * self.qty)

    def to_dict(self):
        # Ensure dates are serialized as ISO strings for JSON compatibility
        entry_date_str = (
            self.entry_date.isoformat()
            if hasattr(self.entry_date, "isoformat")
            else str(self.entry_date)
        )
        exit_date_str = (
            self.exit_date.isoformat()
            if self.exit_date is not None and hasattr(self.exit_date, "isoformat")
            else (str(self.exit_date) if self.exit_date is not None else None)
        )

        return {
            'Side': self.side,
            'Qty': self.qty,
            'Entry Date': entry_date_str,
            'Entry Price': self.entry_price,
            'Exit Date': exit_date_str,
            'Exit Price': self.exit_price,
            'Exit Reason': self.exit_reason,
            'PNL $': self.pnl_abs,
            'PNL %': self.pnl_pct,
        }

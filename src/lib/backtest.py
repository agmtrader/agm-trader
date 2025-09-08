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

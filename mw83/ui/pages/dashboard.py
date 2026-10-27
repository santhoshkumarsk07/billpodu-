"""Today at a glance. Every number comes from the database."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from ...db import today_str
from ...money import fmt
from ...services import reports
from ..common import AppContext, button, hint_label, hrow, run_in_background, title_label


class Card(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        t = QLabel(title)
        t.setObjectName("card_title")
        self.value = QLabel("…")
        self.value.setObjectName("card_value")
        lay.addWidget(t)
        lay.addWidget(self.value)


class DashboardPage(QWidget):
    def __init__(self, ctx: AppContext, go_to=None):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.go_to = go_to
        lay = QVBoxLayout(self)
        self.heading = title_label("Today")
        lay.addLayout(hrow(self.heading, None, button("Refresh", self.refresh), stretch=False))
        grid = QGridLayout()
        self.cards = {}
        spec = [("sales", "Today's sales (Rs.)"), ("bills", "Bills today"), ("items", "Items sold today"),
                ("discounts", "Discounts given (Rs.)"), ("cash", "Cash collected (Rs.)"),
                ("upi", "UPI collected (Rs.)"), ("card", "Card collected (Rs.)"), ("refunds", "Refunds today (Rs.)"),
                ("low_stock", "Low / out-of-stock items"), ("stock_cost", "Stock value at cost (Rs.)"),
                ("stock_sale", "Stock value at selling price (Rs.)"), ("stock_units", "Pieces in stock")]
        for i, (key, title) in enumerate(spec):
            c = Card(title)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)
        lay.addLayout(grid)
        lay.addWidget(hint_label("Collections are net of refunds paid out the same day by that method."))
        if go_to:
            lay.addLayout(hrow(button("Start billing  (F1)", lambda: go_to("Billing / POS"), primary=True),
                               button("See low-stock items", lambda: go_to("Inventory")),
                               button("Reports", lambda: go_to("Reports"))))
        lay.addStretch(1)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        day = today_str()
        self.heading.setText(f"Today — {day[8:10]}-{day[5:7]}-{day[0:4]}")
        default_min = self.ctx.settings.get_int("default_min_stock")
        run_in_background(self.ctx, lambda conn: reports.dashboard(conn, day, default_min), self.show_data, self,
                          "loading the dashboard")

    def show_data(self, d: dict):
        for key, card in self.cards.items():
            v = d.get(key, 0)
            card.value.setText(str(v) if key in ("bills", "items", "low_stock", "stock_units") else fmt(v))

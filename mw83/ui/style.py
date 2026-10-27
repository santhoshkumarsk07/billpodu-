"""A calm light theme with large, readable controls for the shop counter."""

STYLE = """
* { font-size: 10.5pt; }
QMainWindow, QWidget#page { background: #f6f7f9; }
QListWidget#sidebar { background: #1f2a37; color: #e5e7eb; border: none; outline: 0; padding-top: 6px; }
QListWidget#sidebar::item { padding: 11px 14px; border-left: 4px solid transparent; }
QListWidget#sidebar::item:selected { background: #2f3e50; color: white; border-left: 4px solid #f59e0b; }
QListWidget#sidebar::item:hover { background: #283646; }
QLabel#brand { background: #111827; color: #fbbf24; font-size: 14pt; font-weight: bold; padding: 14px; }
QLabel#hint { color: #6b7280; }
QLabel#title { font-size: 17pt; font-weight: bold; color: #111827; padding: 2px 0 6px 0; }
QLabel#error { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; border-radius: 4px; padding: 6px 10px;
               font-weight: bold; }
QLabel#ok { background: #dcfce7; color: #166534; border: 1px solid #86efac; border-radius: 4px; padding: 6px 10px; }
QLabel#total { font-size: 26pt; font-weight: bold; color: #111827; }
QLabel#change { font-size: 18pt; font-weight: bold; color: #166534; }
QLabel#card_value { font-size: 18pt; font-weight: bold; color: #111827; }
QLabel#card_title { color: #6b7280; }
QFrame#card { background: white; border: 1px solid #e5e7eb; border-radius: 8px; }
QLineEdit, QComboBox, QDateEdit, QSpinBox, QPlainTextEdit { background: white; border: 1px solid #cbd5e1;
           border-radius: 4px; padding: 5px; }
QLineEdit:focus, QComboBox:focus, QDateEdit:focus { border: 2px solid #2563eb; }
QLineEdit#scan { font-size: 16pt; padding: 8px; border: 2px solid #f59e0b; }
QPushButton { background: white; border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 12px; }
QPushButton:hover { background: #eef2ff; }
QPushButton:disabled { color: #9ca3af; }
QPushButton#primary { background: #2563eb; color: white; border: 1px solid #1d4ed8; font-weight: bold; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #fff1f2; color: #b91c1c; border: 1px solid #fecaca; }
QPushButton#big { font-size: 13pt; font-weight: bold; padding: 10px 16px; background: #16a34a; color: white;
                  border: 1px solid #15803d; }
QPushButton#big:hover { background: #15803d; }
QTableWidget { background: white; gridline-color: #e5e7eb; selection-background-color: #bfdbfe;
               selection-color: #111827; }
QHeaderView::section { background: #eef0f3; padding: 5px; border: none; border-right: 1px solid #e5e7eb;
                       font-weight: bold; }
QGroupBox { background: white; border: 1px solid #e5e7eb; border-radius: 6px; margin-top: 14px; padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: bold; }
QTabWidget::pane { border: 1px solid #e5e7eb; background: white; }
"""

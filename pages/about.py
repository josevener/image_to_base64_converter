"""Developer Toolbox company information page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from ui.components.tool_page import ToolPage


class AboutPage(ToolPage):
    """Displays product attribution and the Zentrix Solutions website."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel("Developer Toolbox")
        name.setObjectName("pageTitle")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        company = QLabel("Developed by Zentrix Solutions")
        company.setAlignment(Qt.AlignmentFlag.AlignCenter)
        website = QLabel('<a href="https://zentrix-solutions.vercel.app">zentrix-solutions.vercel.app</a>')
        website.setAlignment(Qt.AlignmentFlag.AlignCenter)
        website.setOpenExternalLinks(True)
        layout.addWidget(name)
        layout.addWidget(company)
        layout.addWidget(website)

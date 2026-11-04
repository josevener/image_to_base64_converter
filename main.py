"""Application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from app import ApplicationController


if __name__ == "__main__":
    application = QApplication(sys.argv)
    controller = ApplicationController()
    application.aboutToQuit.connect(controller.shutdown)
    controller.show()
    sys.exit(application.exec())

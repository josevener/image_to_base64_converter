"""Metadata page view."""
from ui.components.tool_page import PlaceholderPage


class MetadataPage(PlaceholderPage):
    def __init__(self) -> None:
        super().__init__("Image Metadata")

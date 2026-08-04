"""Compatibility exports; new code imports from :mod:`services.image_service`."""

from services.image_service import ConversionResult, SUPPORTED_EXTENSIONS, convert_image, is_supported_image

__all__ = ["ConversionResult", "SUPPORTED_EXTENSIONS", "convert_image", "is_supported_image"]

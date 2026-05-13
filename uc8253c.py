"""
UC8253C E-Paper Display Driver
A standalone Python library for the WeAct 3.7" E-Paper display.

Features:
    - 4-wire SPI Interface.
    - Ping-Pong Differential Buffering support.
    - Multiple refresh modes (FULL, FAST, PARTIAL).
    - Support for Pillow (PIL) images.

Dependencies:
    pip install spidev RPi.GPIO Pillow
"""

import time
from typing import List, Optional, Union

import RPi.GPIO as GPIO
import spidev
from PIL import Image


class UC8253C:
    """
    Driver for the WeAct 3.7" UC8253C E-Paper Display.

    Attributes:
        MODE_FULL (str): High quality refresh mode.
        MODE_FAST (str): Fast single-flash refresh mode.
        MODE_PARTIAL (str): Ultra-fast no-flash refresh mode.
    """

    # Hardware Command IDs
    _CMD_PANEL_SETTING = 0x00
    _CMD_POWER_OFF = 0x02
    _CMD_POWER_ON = 0x04
    _CMD_DEEP_SLEEP = 0x07
    _CMD_DATA_START_1 = 0x10  # Memory Bank 1
    _CMD_DISPLAY_REFRESH = 0x12
    _CMD_DATA_START_2 = 0x13  # Memory Bank 2
    _CMD_VCOM_DATA_INTERVAL = 0x50
    _CMD_CASCADE_SETTING = 0xE0
    _CMD_FORCE_TEMP = 0xE5

    # Native resolution (screen is physically 240x416)
    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    # Refresh Mode Constants
    MODE_FULL = "FULL"
    MODE_FAST = "FAST"
    MODE_PARTIAL = "PARTIAL"

    def __init__(
        self,
        rst_pin: int = 17,
        dc_pin: int = 25,
        busy_pin: int = 24,
        spi_bus: int = 0,
        spi_device: int = 0,
        rotation: int = 90,
    ) -> None:
        """
        Initializes the UC8253C display.

        Args:
            rst_pin: GPIO pin number for Reset.
            dc_pin: GPIO pin number for Data/Command.
            busy_pin: GPIO pin number for Busy signal.
            spi_bus: SPI bus number.
            spi_device: SPI device number.
            rotation: Display rotation (0, 90, 180, or 270 degrees).
        """
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin

        if rotation not in [0, 90, 180, 270]:
            print(f"[UC8253C] Warning: Invalid rotation {rotation}, defaulting to 0.")
            self.rotation = 0
        else:
            self.rotation = rotation

        # State tracking
        self.is_sleeping = True
        self.current_mode = self.MODE_FULL
        self._is_swapped = False

        # Adjust screen orientation based on rotation
        if self.rotation in [90, 270]:
            self.width, self.height = self._NATIVE_HEIGHT, self._NATIVE_WIDTH
        else:
            self.width, self.height = self._NATIVE_WIDTH, self._NATIVE_HEIGHT

        # 1 bit per pixel (Black/White). Total bytes = (240 * 416) / 8
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

        try:
            self._init_gpio()
            self._init_spi(spi_bus, spi_device)
        except Exception as e:
            print(f"[UC8253C] Error: Hardware initialization failed: {e}")
            self.close()
            raise

    def __enter__(self) -> "UC8253C":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # Low-Level SPI & GPIO

    def _init_spi(self, bus: int, device: int) -> None:
        """Sets up the hardware SPI connection."""
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

    def _init_gpio(self) -> None:
        """Sets up the Pi's GPIO pins."""
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(
        self, cmd: int, data: Optional[Union[int, List[int], bytearray]] = None
    ) -> None:
        """
        Sends a command byte, followed by optional data bytes.

        Args:
            cmd: Command byte.
            data: Optional data payload (int, list of ints, or bytearray).
        """
        try:
            GPIO.output(self.dc_pin, GPIO.LOW)
            self.spi.writebytes([cmd])

            if data is not None:
                GPIO.output(self.dc_pin, GPIO.HIGH)
                if isinstance(data, int):
                    self.spi.writebytes([data])
                elif isinstance(data, list):
                    self.spi.writebytes(data)
                else:
                    # Optimized for large payloads
                    self.spi.writebytes2(data)
        except Exception as e:
            print(f"[UC8253C] Error: SPI write failed: {e}")

    def _wait_busy(self, timeout_secs: float = 5.0) -> bool:
        """
        Polls the Busy pin until the display is ready.

        Args:
            timeout_secs: Max time to wait before timing out.

        Returns:
            True if ready, False on timeout.
        """
        time.sleep(0.02)
        start = time.time()

        try:
            while GPIO.input(self.busy_pin) == 0:
                time.sleep(0.01)
                if (time.time() - start) > timeout_secs:
                    print("[UC8253C] Error: Hardware busy timeout.")
                    return False
        except Exception as e:
            print(f"[UC8253C] Error: Failed to read busy pin: {e}")
            return False

        time.sleep(0.02)
        return True

    def _hardware_reset(self) -> None:
        """Physically resets the display controller."""
        try:
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.05)
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.05)
            self._is_swapped = False
            self.is_sleeping = False
        except Exception as e:
            print(f"[UC8253C] Error: Hardware reset failed: {e}")

    def _wake_up(self) -> bool:
        """Wakes the display from deep sleep."""
        self._hardware_reset()
        if not self._wait_busy():
            return False

        self._write(self._CMD_POWER_ON)
        if not self._wait_busy():
            return False

        # Initialize registers
        self._write(self._CMD_PANEL_SETTING, [0x1F, 0x0D])
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        self.is_sleeping = False
        return True

    # Refresh Mode Management

    def set_full_refresh(self) -> None:
        """Sets hardware to high-quality full refresh mode."""
        self.current_mode = self.MODE_FULL
        if not self.is_sleeping:
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

    def set_fast_refresh(self) -> None:
        """Sets hardware to fast single-flash refresh mode."""
        self.current_mode = self.MODE_FAST
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x5F)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def set_partial_refresh(self) -> None:
        """Sets hardware to partial no-flash mode."""
        self.current_mode = self.MODE_PARTIAL
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x6E)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def _apply_current_mode(self) -> None:
        """Ensures hardware registers match the current software mode."""
        if self.current_mode == self.MODE_FULL:
            self.set_full_refresh()
        elif self.current_mode == self.MODE_FAST:
            self.set_fast_refresh()
        elif self.current_mode == self.MODE_PARTIAL:
            self.set_partial_refresh()

    # Public API

    def clear(self, auto_sleep: bool = True) -> None:
        """
        Fills the display with white.

        Args:
            auto_sleep: If True, puts the display to sleep after clearing.
        """
        if self.is_sleeping:
            if not self._wake_up():
                return

        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        white_payload = bytearray([0xFF] * self.buffer_size)

        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        self._write(cmd_old, white_payload)
        self._write(cmd_new, white_payload)

        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        self.buffer_old = white_payload
        self._is_swapped = not self._is_swapped

        self._apply_current_mode()

        if auto_sleep:
            self.sleep()

    def update(self, image: Image.Image, auto_sleep: bool = True) -> bool:
        """
        Updates the display with a Pillow Image.

        Args:
            image: A PIL Image object (should match display dimensions).
            auto_sleep: If True, puts the display to sleep after updating.

        Returns:
            True if successful, False otherwise.
        """
        if image.width != self.width or image.height != self.height:
            print(
                f"[UC8253C] Error: Dimension mismatch: Expected {self.width}x{self.height}, got {image.width}x{image.height}"
            )
            return False

        if self.is_sleeping:
            if not self._wake_up():
                return False
            self._apply_current_mode()

        try:
            # Handle rotation
            if self.rotation != 0:
                # Rotate image to native orientation for the controller
                image_to_send = image.rotate(-self.rotation, expand=True)
            else:
                image_to_send = image

            # Convert to 1-bit and then to bytes
            current_buffer = bytearray(image_to_send.convert("1").tobytes())
        except Exception as e:
            print(f"[UC8253C] Error: Image processing failed: {e}")
            return False

        # Determine Bank Mapping
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        self._write(self._CMD_DISPLAY_REFRESH)
        if not self._wait_busy():
            return False

        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped

        if auto_sleep:
            self.sleep()

        return True

    def sleep(self) -> None:
        """Puts the display into deep sleep to prevent damage."""
        if self.is_sleeping:
            return

        try:
            self._write(self._CMD_POWER_OFF)
            self._wait_busy()
            self._write(self._CMD_DEEP_SLEEP, 0xA5)
            self.is_sleeping = True
        except Exception as e:
            print(f"[UC8253C] Error: Failed to enter deep sleep: {e}")

    def close(self) -> None:
        """Releases GPIO and SPI resources."""
        try:
            self.sleep()
        except Exception:
            pass

        try:
            if hasattr(self, "spi"):
                self.spi.close()
            GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
        except Exception as e:
            print(f"[UC8253C] Error: Cleanup failed: {e}")

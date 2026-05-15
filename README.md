# UC8253C E-Paper Display Driver

Python library for the **WeAct 3.7" E-Paper Display (UC8253C controller chip, 240x416px)**.

---

## Features

- **Multiple Refresh Modes**:
  - `FULL`: High quality, removes ghosting, take most time.
  - `FAST`: Single-flash update, requires full refresh occasionally to prevent ghosting.
  - `PARTIAL`: Fast, partial refresh with no flashing, ideal for UI elements, requires full every 5-7 refreshes.
- **Pillow (PIL) Integration**: Render images, text, and graphics using the Pillow library.
- **Safe Hardware Management**: Automatic deep sleep and GPIO cleanup to prevent hardware damage.

---

## Hardware Setup

### Raspberry Pi Pinout (Default)

| E-Paper Pin    | Pi GPIO (BCM) | Physical Pin        |
| :------------- | :------------ | :------------------ |
| **VCC**        | 3.3V          | 1 or 17             |
| **GND**        | Ground        | 6, 9, 14, 20, or 25 |
| **DIN (MOSI)** | GPIO 10       | 19                  |
| **CLK (SCLK)** | GPIO 11       | 23                  |
| **CS**         | GPIO 8        | 24                  |
| **DC**         | GPIO 25       | 22                  |
| **RST**        | GPIO 17       | 11                  |
| **BUSY**       | GPIO 24       | 18                  |

### Enable SPI

Ensure SPI is enabled on your Raspberry Pi:

```bash
sudo raspi-config
# Interface Options -> SPI -> Yes
```

---

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

_Note: Requirements include `spidev`, `RPi.GPIO`, and `Pillow`._

---

## Usage

### Using Full Refresh

```python
from PIL import Image, ImageDraw, ImageFont
from uc8253c import UC8253C

# Initialize display
with UC8253C(rotation=90) as display:
    # Create a new white image
    img = Image.new("1", (display.width, display.height), 255)
    draw = ImageDraw.Draw(img)

    # Draw some shapes
    draw.text((10, 10), "Hello UC8253C!", fill=0)
    draw.rectangle([20, 40, 60, 80], outline=0, fill=0)

    # Update the display
    display.update(img)
```

### Using Partial Refresh

```python
from PIL import Image, ImageDraw
from uc8253c import UC8253C

display = UC8253C(rotation=90)
display.set_partial_refresh()

# Perform many small updates without screen flashing
for i in range(10):
    # Create dynamic image (e.g., a counter)
    img = Image.new("1", (display.width, display.height), 255)
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), f"Iteration: {i}", fill=0)

    # Update the display without putting it to sleep immediately
    display.update(img, auto_sleep=False)

display.sleep()
display.close()
```

---

## Ping-Pong Buffering

The UC8253C controller contains two internal memory banks.

1. The library keeps track of the "Previous" state and the "Current" state.
2. It sends the previous image to Bank 1 and the new image to Bank 2.
3. The display hardware compares these banks and only triggers a physical state change for pixels that differ.

This allows partial refresh.

---

## License

This project is open-source. Feel free to use it in your own projects!

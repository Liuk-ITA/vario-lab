# Parts and purchasing

## Basic build: no soldering

| Quantity | Component | Manufacturer part | Where to buy |
|---|---|---|---|
| 1 | M5Stack StickS3 | K150 / Mouser170-K150 | [M5Stack](https://shop.m5stack.com/products/m5sticks3-esp32s3-mini-iot-dev-kit), [Mouser](https://www.mouser.it/c/?q=K150) |
| 1 | Adafruit BMP581 STEMMA QT breakout | 6407 | [Adafruit](https://www.adafruit.com/product/6407), [Mouser](https://www.mouser.it/c/?q=Adafruit%206407) |
| 1 | Grove to STEMMA QT/Qwiic cable,100mm | Adafruit4528 | [Adafruit](https://www.adafruit.com/product/4528), [Mouser](https://www.mouser.it/c/?q=Adafruit%204528) |
| 1 | USB-C data cable suitable for your computer | Any compatible data cable | Use an existing cable if available |

[Download the BOM CSV](../assets/bom.csv) to import manufacturer, part number and
quantity into Mouser's BOM tool. This is a parts list, not a shared cart. Check
stock, pricing and connector pinout before ordering. The BOM contains no personal data.

Choose **StickS3**, not StickC Plus/Plus2, and **BMP581**, not BMP580/BMP585.
The sensor's QT cable is sold separately. No external amplifier, speaker or battery
is required for the basic assembly.

## Optional wired-header build

Use four short insulated wires, or a QT pigtail with suitable terminations, instead
of the Grove adapter. Soldering, insulation and strain relief may be needed.
External buttons are not part of this initial assembly guide.

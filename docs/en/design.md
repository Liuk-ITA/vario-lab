# Why this design?

## Few components, useful experiments

StickS3 includes a display, speaker, battery and USB interface. The Adafruit
breakout makes Bosch's BMP581 available as an assembled board with accessible
connectors. A short adapter cable makes the basic build possible without soldering.
The sensor choice targets accurate, responsive pressure measurement; precision
of the complete flying instrument remains something to measure, not assume.

## Fixed acquisition, selectable interpretation

BMP581 acquisition uses NORMAL80Hz, pressure16x and temperature4x oversampling,
IIRoff,400kHz I2C and FIFOpressure+temperature with watermark4. The FIFO handles
short scheduling delays; its finite capacity does not permit arbitrary pauses.
Each sample receives a reconstructed nominal time, not a hardware timestamp.

Parallel filters make it possible to compare different responses on the same
signal. Visual smoothing and sound control are separate so a readable number
does not force an equally slow acoustic response. The lab makes these choices
available for replay and listening experiments as well as live input.

## Open, and candid about AI

The project is vibe ~~coded~~ engineered: AI-assisted implementation is paired
with measured checks and hands-on feedback. Source is available under MIT.
Reusing it requires preserving the copyright and license notices, not keeping
an unchangeable splash screen. Startup illustrations and sounds are original.

The BLE keyboard remains experimental. IMU sensor fusion is not implemented.
Comparative presets are adaptations of filtering principles, not replicas of
commercial variometers. See the [firmware credits](https://github.com/Liuk-ITA/vibevario/blob/main/NOTICE.md).

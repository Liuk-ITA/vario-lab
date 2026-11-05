# Features and controls

## Built-in controls

| Control | Action |
|---|---|
| A short press | Next enabled filter |
| A held | Cycle enabled timbres |
| B short press | Cycle volume levels, including mute |
| B held | Set a new relative-altitude reference |

The current menu includes Kalman, regression, low-pass, double-EMA and adapted
SkyBean filtering. Dolce, Ricco, Dispari and FM ferma are original synthesized
timbres; sound pattern, base pitch and volume are independent settings.
The configurator controls which choices participate in each cycle.

## Display and audio

Vertical speed is shown in m/s. The number and bar have separate visual smoothing
from the sound. Battery voltage is shown at the top. Relative altitude comes from
pressure relative to a startup reference; allow the initial calibration to finish.
Sensor temperature can be affected by the enclosure and is not automatically
ambient-air temperature. The startup signature is followed by normal measurement.

## XCTrack

The current BLE name is **StickVario**. Telemetry uses NUS/LK8EX1; standard BLE
battery and temperature services are also exposed. Telemetry has been tried on
a phone. Optional BLE keyboard pairing is unresolved and is not needed for the
basic variometer. External buttons remain outside the initial build instructions.

## Current limits

This is a bench prototype. Flight response, enclosure airflow, battery runtime
and speaker audibility still need field evaluation. Applying settings and saving
them are different actions; saving deliberately pauses acquisition for flash I/O.

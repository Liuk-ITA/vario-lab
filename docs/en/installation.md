# Install and configure

VibeVario is a MicroPython application running on **UIFlow2 for StickS3**, not a
replacement ESP32 system image. For a new device, prepare UIFlow2 using the
[official StickS3 instructions](https://docs.m5stack.com/en/core/StickS3).

## Browser tools

- [Open the web installer](../../install/): choose an application and USB port,
then try it in RAM or explicitly choose persistent installation.
- [Open the configurator](../../config/): read settings, preview choices, apply
changes to the running session, or save them for the next start.
- [Open Vario Lab](../../): replay recordings, compare filters and sound profiles.

The lab, configurator, installer and guides support English and Italian. Use the
language selector at the top right; switching tool language preserves the session.

USB/BLE access requires a compatible browser and an explicit device choice.
A USB connection cannot be shared simultaneously by the installer, lab and a
terminal. RAM execution is temporary; saving settings does not install the app.

The public firmware release and website deployment are being prepared. Until then,
use the local application/manifest from a source build. See the
[firmware developer guide](https://github.com/Liuk-ITA/vibevario/blob/main/docs/development.md).

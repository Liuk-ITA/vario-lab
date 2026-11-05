# Configurator

Static EN/IT USB/BLE configuration UI. Open `/config/` on localhost or HTTPS.
Device protocol: JSON requests version1, USB @CFG/@CF1 framing, custom BLE service.
Read settings, choose enabled filter/timbre/volume/frequency/pattern cycles, preview,
Apply for RAM or Save for persistence. SAVE deliberately pauses acquisition for I/O.
Changing keyboard support requires saved settings and restart; Android pairing is
still experimental. Settings save does not install firmware or change startup mode.
Raw protocol data and user input are not translated by the UI language selector.

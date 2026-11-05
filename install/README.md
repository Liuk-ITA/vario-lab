# Installer

Static EN/IT application installer using Web Serial and raw REPL. Normal operation
requires compatible UIFlow2 on StickS3; the bundled Python file is not a system image.
Sources: included mirror, public GitHub release, manifest URL or selected local files.
Validate board, byte count, UTF-8 and SHA256 before RAM upload or file installation.
Persistent automatic startup is explicit and uses a backed-up main.py launcher;
boot.py is preserved. Existing owned launchers can be restored through boot controls.

The optional ESP32-S3 system-image path is separately gated. ESP Web Tools loads
only after explicit selection/verification; no full-system binary is bundled.
Browser USB permissions and device writes always require a user action.
The test suite uses API doubles and a filesystem mirror for the boot helper;
passing tests is not a claim of physical browser USB validation.

# Installation

!!! note "Windows Only"
    {{ app_name }} is developed and tested on Windows.

{{ app_name }} is a portable application for Windows. It does not require an installer.

1. Open the [latest release](https://github.com/RoyiAvital/RoyiFileManager/releases/latest).
2. Download `{{ app_name }}-<version>-windows-x86_64.zip`.
3. Extract the ZIP file to a folder of your choice.
4. Run `{{ app_name }}.exe` from the extracted folder.

!!! tip "Portable Application"
    Keep all extracted files together. You can move the entire {{ app_name }} folder
    to another location whenever needed.

Settings are saved in `UserSettings` beside the application. See
[Configuration](configuration.md). To add plug-ins, see
[Manual installation](plugins/index.md#manual-installation).

## Upgrading

1. Close {{ app_name }} completely.
2. Back up your `UserSettings` folder.
3. Extract the new release ZIP and copy your `UserSettings` folder into the new directory (or overwrite the application files while keeping `UserSettings`).
4. Start {{ app_name }} and run **Settings: Update settings file template** from the Command Center (++ctrl+shift+p++) to append any new commented defaults to `UserSettings\AppSettings.yaml`.

Existing values, comments, favorites and custom plug-ins in `UserSettings` are preserved. Check the [release notes](https://github.com/RoyiAvital/RoyiFileManager/blob/main/CHANGELOG.md) for any version-specific migration notes.
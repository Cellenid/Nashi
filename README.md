<!--
# SPDX-FileCopyrightText: Copyright 2025 Eden Emulator Project
# SPDX-License-Identifier: GPL-3.0-or-later

# SPDX-FileCopyrightText: 2018 yuzu Emulator Project
# SPDX-License-Identifier: GPL-2.0-or-later
-->

<p align="center">
  <img src="dist/branding/nashi_icon_with_logo.png" alt="Nashi" width="600">
</p>

# Nashi

Nashi is an experimental, open-source Nintendo Switch and Switch 2 emulator written in C++. It is a fork of [Lichii](https://github.com/zortos293/Lichii), which itself builds on Eglantine, Eden, yuzu and Sudachi. Nashi focuses on bringing together fixes from across the community forks and on performance work, backed by an automated test bench.

The name comes from the Japanese pear, continuing the fruit lineage of yuzu, sudachi and lichii.

This is an independent fork, not an official release of any upstream project. Nashi is not affiliated with Nintendo.

## Downloads and setup

Download Nashi only from this repository's [releases page](https://github.com/Cellenid/Nashi/releases) or its GitHub Actions artifacts. Nashi has no other download site.

On Windows, extract the entire build archive and run **nashi.exe**. Only use games and system files you have legally obtained from your own console. Games, keys and firmware are not included and will never be provided.

### Existing saves and settings

Nashi keeps the existing Eden/Eglantine/Lichii data directories and configuration keys. It does not move or delete saves, settings or shader caches. Back up your saves before testing experimental builds.

## Compatibility

Compatibility and performance vary by game, hardware and driver. Rendering errors, stutters and crashes remain possible. Passing automated tests does not establish that a game renders correctly, and this project makes no universal frame rate guarantee.

When [reporting an issue](https://github.com/Cellenid/Nashi/issues), include:

- The exact build, game version, CPU, GPU and driver version.
- Relevant settings and steps to reproduce the problem.
- A screenshot and the log from the affected session, after checking it for personal information.

Do not upload game files, keys, firmware or private account information.

## Building and contributing

See the [build guide](docs/Build.md), [user documentation](docs/user/README.md) and [coding guidelines](docs/Coding.md). Some inherited documentation and internal build target names still use upstream names. The GUI build target remains `yuzu`; its output is `nashi.exe` on Windows and `nashi` on other desktop platforms.

Keep changes focused and distinguish code level checks from actual gameplay testing.

## Artwork

The current logo and icons are inherited from Lichii (art by YOB, yobslab) and will be replaced by Nashi's own artwork. Windows, Linux and macOS icon resources are generated from [dist/branding](dist/branding) by [Generate-NashiIcons.ps1](tools/Generate-NashiIcons.ps1).

## Credits and license

Nashi inherits the work of the Lichii, Eglantine, Eden, yuzu and Sudachi projects and their contributors, including Lichii's developer zortos293 and Eglantine's original developer Camille LaVey. Original copyright notices and third party licenses are retained.

Nashi is distributed under the GPL. See [LICENSE.txt](LICENSE.txt) and the source files for applicable license terms.

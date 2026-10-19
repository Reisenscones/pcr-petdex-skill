# Upstream provenance

This is the code-only template distributed with pcr-petdex-skill. Character
models, textures, generated frames, local state and native export tools are not
included. The two reference configurations are retained for rebuilding from
user-provided materials. Portability changes add JSON skeleton resolution,
fallback to a built character, explicit asset provenance for new characters,
and an isolated preview launcher. The main character's directory, internal id,
defaults and example commands are normalized to ho-chan throughout this fresh
project template. These changes have received static checks
only; no fresh-machine or runtime reproduction was performed for this package.

This project contains a local derivative of GooglePiggy DesktopPet's Windows implementation.

- Repository: https://github.com/Myf-ricey/GooglePiggy_DesktopPet
- Revision: 938c40e1253511baeb8b3318ab6d3a75cbff876a
- Original software license: MIT, preserved in LICENSE.
- Original artwork notice: retained with its original scope in ASSET-NOTICE.md, alongside the Ho-chan attribution.
- Local changes: Ho-chan launcher, a complete Ho-chan PNG skin, portrait edge handles, fixed-view export tool, previews, rendering optimizations, hand-anchored dragging, native context menus, isolated Codex hooks, independent Codex autostart and verification tools.
- Character packs: ホウオウ (134731) and キョウカ（ゴシック） (139031), with persistent runtime switching and configuration-based registration for additional characters.

Ho-chan artwork is sourced from [redive.estertion.win](https://redive.estertion.win/). Copyright belongs to Cygames (© Cygames), including the character models, textures and animations and their exported frames, portraits and previews. Local source files are kept in source/spine/ and source/reference-frames/. The upstream MIT software license does not grant rights to this separate artwork.

All active animation references and edge handles use character artwork. Only the neutral success-effect PNGs remain from the original artwork. The legacy GIF pipeline, stock animations, platform icons, updater, redundant menus and transparent sleep overlays have been removed. Win32 bindings live in win32_api.py and the native base in pcr_pet.py. The event bridge is implemented directly in hooks/codex-hochan-hook.ps1; hook and autostart installers manage their own entries. Original author attribution and the true upstream URL above are preserved for provenance.

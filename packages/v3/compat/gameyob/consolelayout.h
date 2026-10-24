// SPDX-License-Identifier: MIT
#pragma once

// 256 four-bit 8x8 glyphs occupy 8 KiB at tile base 0. Map base 22 is
// separate, matches the menu's palette/highlight map, and fits in VRAM C.
enum { GAMEYOB_CONSOLE_MAP_BASE=22, GAMEYOB_CONSOLE_TILE_BASE=0 };

# CLeds Scenario Parameters Reference Guide

This document lists all active effect scenario parameters, their descriptions, valid adjustment ranges, and step sizes for both the PWA interface and the hardware menus.

\---

## 🛠️ Color Parameters

All color parameters can be set in three different ways:

1. **Desired Color:** Pick any RGB value from the PWA's color wheel/square selector.
2. **🎲 Random Color (`RM`):** Selects a randomized color from the active system palette.
3. **🌈 Rainbow Color (`R`):** Applies a shifting gradient/rainbow color dynamically.

|Parameter Name|Target|Valid Input Values|
|-|-|-|
|`color\_p`|Primary Color (e.g. Bar 0, comet head, wave main)|`\[R, G, B]`, `"RM"`, `"R"`|
|`color\_s`|Secondary Color (e.g. Bar 1, peak marks, wave background)|`\[R, G, B]`, `"RM"`, `"R"`|
|`color\_t`|Tertiary Color (e.g. Bar 2, orbit body, secondary spectrum)|`\[R, G, B]`, `"RM"`, `"R"`|
|`color\_q`|Quaternary Color (e.g. Bar 3, edge sparkles)|`\[R, G, B]`, `"RM"`, `"R"`|

\---

## ⚡ Timing, Speeds \& Delays

|Parameter Name|Description|Range|Step Size|
|-|-|-|-|
|`speed`|Core animation velocity|`0.1` to `10.0`|`0.1`|
|`delay`|Minimum render delay between frame calculations (ms)|`1` to `5000`|`50`|
|`color\_interval\_ms`|Interval before picking new colors in RM mode (ms)|`1` to `5000`|`50`|
|`palette\_shift\_speed`|Speed of smooth colors shifting along the palette|`0.0` to `1.0`|`0.05`|
|`decay\_rate`|Decay multiplier for fading trails and heat maps|`0.001` to `0.2`|`0.005`|

\---

## 🧭 Layout, Position \& Dimensions

|Parameter Name|Description|Range|Step Size|
|-|-|-|-|
|`pos` / `pos\_0`–`pos\_3`|Start position offset of bars/comets along the strip|`0` to `150`|`2`|
|`height` / `height\_0`–`height\_3`|Target height or vertical length of static/dynamic elements|`-150` to `150`|`2`|
|`max\_height` / `wave\_height`|Upper vertical bounds for active render elements|`1` to `150`|`2`|
|`bar\_size` / `braid\_length`|Core thickness or pixel counts of active shapes/stripes|`1` to `150`|`2`|
|`min\_len` / `max\_len`|Size bounds for randomized particles and comet tails|`1` to `150`|`2`|
|`direction`|Movement orientation direction (up/down or left/right)|`-1` or `1`|`2`|
|`center\_offset`|Offsets elements relative to the physical matrix center|`-50` to `50`|`1`|

\---

## 🪐 Physics \& Particle Dynamics

|Parameter Name|Description|Range|Step Size|
|-|-|-|-|
|`gravity`|Pull strength of active attraction centers (gravity wells)|`0.1` to `10.0`|`0.1`|
|`wind`|Horizontal force applied to active floating particles|`-2.0` to `2.0`|`0.05`|
|`bounce`|Restitution factor (elasticity) when colliding with boundaries|`0.0` to `1.0`|`0.05`|
|`friction`|Friction/air resistance damping particle speed|`0.0` to `1.0`|`0.05`|
|`swallow\_radius`|Distance at which particles are swallowed by black holes|`0.5` to `10.0`|`0.1`|
|`mass`|Heavy gravity center mass parameter|`5` to `1000`|`10`|
|`particles` / `max\_particles`|Maximum active floating particle counts on screen|`5` to `1000`|`5`|
|`particle\_count`|Startup particle counts for gravity simulations|`5` to `200`|`5`|
|`n\_orbiters` / `planet\_count`|Counts of orbiting bodies around gravity wells|`1` to `10`|`1`|

\---

## ✨ Visual Effects, Sparks \& Noise

|Parameter Name|Description|Range|Step Size|
|-|-|-|-|
|`intensity`|Heat output scaling factor for flame simulations|`0` to `300`|`5`|
|`cooling`|Cooling coefficient for fire decay|`0` to `300`|`5`|
|`sparking`|Probability of generating new hot sparks at base of flames|`0` to `300`|`5`|
|`ghosting` / `ghosting\_factor`|Phosphor trail decay duration (smaller values clear faster)|`0.0` to `1.0`|`0.05`|
|`rnd\_fac`|Random perturbation factor applied to movements|`0.0` to `1.0`|`0.05`|
|`angle`|Phase angle for spiral, radar, or coordinate rotations|`0.0` to `360.0`|`5.0`|
|`hue\_offset`|Fixed offset shift applied to palette selections|`0.0` to `360.0`|`10.0`|
|`arms` / `n\_dots` / `num\_snakes`|Multi-arm count for spirals or dynamic elements|`1` to `36`|`1`|
|`spacing` / `cycles` / `size`|Width/pixel periods of repeating waves or stripes|`0` (or `1`) to `50`|`1`|
|`color\_mode`|Preset color palettes mapping index (`-1` to `4`)|`-1` to `4`|`1`|




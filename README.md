# Leds System Controller

Leds system is a high-performance, real-time sound-reactive LED display and physics-based animation system designed for the **ESP32-S3** microcontroller running custom **MicroPython** firmware.

By offloading timing-critical tasks (such as pixel rendering, I2S audio capture, Fast Fourier Transform (FFT) analysis, and infrared decoding) to custom native C modules running asynchronously on **Core 1**, CLeds achieves extremely smooth visual rendering (up to 25+ FPS) without blocking the MicroPython interpreter or disrupting Wi-Fi operations on Core 0.

\---

## 🚀 Key Features

* **Progressive Web App (PWA) Dashboard:** Integrates a responsive, glassmorphic PWA that works offline. Allows full control over active modes, effect scenarios, dynamic parameters, autoplay timers, timezone settings, and quick favorites, alongside real-time monitoring of internal telemetry and external OpenWeatherMap forecast data.
* **Static IP Connection:** Supports configuring a fixed IP address to connect directly without searching the serial console for DHCP leases.
* **Dual LED Strip Controller:** Drives two physical, addressable LED grids (e.g., WS2812B strips on `LED1` and `LED2`) with separate config parameters and render loops.
* **Text Overlay Engine:** Renders zoned layout overlays (static text, scrolling text, or dynamic clock time) directly over active visual effects.
* **Sound-Reactive Visualizations:** Real-time audio spectrum analysis grouping audio inputs into logarithmic bands, detecting BPM/beat markers, and mapping raw frequencies to visual dynamics.
* **Physics \& Particles Engine:** Real-time particle simulations including gravity wells, spring forces, bouncing physics, comets, orbits, and black holes.
* **Multi-Sensor Integration:** Collects environmental data (temperature, humidity, barometric pressure) and ambient light levels (luminance in lux) to dynamically adjust LED behavior.
* **Astronomic \& NTP Clock Sync:** Synchronizes high-precision hardware real-time clock (RTC) via NTP and calculates sunrise/sunset positions for automatic night-time dimming.
* **Motion-Activated Power Savings:** Integrates a PIR motion sensor to automatically put the device into lightsleep mode when no presence is detected, waking up instantly on movement.
* **Infrared Control:** Includes a non-blocking IR remote decoder and recording sequence allowing users to adjust parameters, select effects, and cycle favorite presets.

\---

## 🔌 Hardware Pin Configuration (ESP32-S3)

Below is the pin assignment configured in \[init.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/init.py):

|Component / Function|GPIO Pin|Type|Details|
|-|-|-|-|
|**LED1 Control Pin**|`GPIO 2`|Output|WS2812B LED grid 1 driver|
|**LED2 Control Pin**|`GPIO 42`|Output|WS2812B LED grid 2 driver|
|**I2C SCL**|`GPIO 47`|Output|SoftI2C Clock for sensors|
|**I2C SDA**|`GPIO 21`|In/Out|SoftI2C Data for sensors|
|**I2S SCK (BCLK)**|`GPIO 13`|Output|Audio I2S Bit Clock|
|**I2S WS (LRCK)**|`GPIO 12`|Output|Audio I2S Word Select|
|**I2S SD (DIN)**|`GPIO 14`|Input|Audio I2S Data (INMP441)|
|**IR Receiver OUT**|`GPIO 39`|Input|Infrared receiver module (TSOP38238)|
|**Active Buzzer**|`GPIO 45`|Output|Acoustic signal buzzer|
|**PIR Motion Sensor**|`GPIO 20`|Input|Presence detector (Ext0 wakeup pin)|
|**B1 Button (L)**|`GPIO 7`|Input|Physical interrupt-driven buttons|
|**B2 Button (R)**|`GPIO 4`|Input|Physical interrupt-driven buttons|
|**B3 Button (Minus)**|`GPIO 5`|Input|Physical interrupt-driven buttons|
|**B4 Button (Plus)**|`GPIO 6`|Input|Physical interrupt-driven buttons|
|**B5 Button (Center)**|`GPIO 15`|Input|Physical interrupt-driven buttons|
|**B6 Button (L1)**|`GPIO 41`|Input|Physical interrupt-driven buttons|
|**B7 Button (L2)**|`GPIO 40`|Input|Physical interrupt-driven buttons|

\---

## 🏗️ System Architecture

CLeds is divided into two distinct execution layers to ensure both performance and ease of configuration:

```mermaid
---

config:

&#x20; layout: elk

\---

flowchart TD

&#x20; subgraph MicroPython\_Layer\["MicroPython Layer (Core 0)"]

&#x20;   class MicroPython\_Layer indigo

&#x20;   main\["main.py: App Loop \& Controls"]:::indigo

&#x20;   init\["init.py: Hardware \& Sensors"]:::indigo

&#x20;   effects\["effects.py: Visual Renderers"]:::indigo

&#x20;   helpers\["helpers.py: Math \& Colors"]:::indigo

&#x20;   mapper\["ir\_remote\_mapper.py: Action Mapper"]:::indigo

&#x20;   web\["web\_server.py: Non-Blocking Web Server"]:::indigo

&#x20;   wifi\["wifi\_manager.py"]:::indigo

&#x20;   bme\["bme280.py"]:::indigo

&#x20;   bh\["bh1750.py"]:::indigo

&#x20;   ds\["ds3231.py"]:::indigo



&#x20;   main --> init

&#x20;   main --> effects

&#x20;   effects --> helpers

&#x20;   main --> mapper

&#x20;   main --> web

&#x20;   init --> wifi

&#x20;   init --> bme

&#x20;   init --> bh

&#x20;   init --> ds

&#x20; end



&#x20; subgraph Custom\_C\_Modules\["Custom C Modules (Core 1 / Hardware)"]

&#x20;   class Custom\_C\_Modules teal

&#x20;   leddisplay\_c\["leddisplay: Text Rendering \& Layout"]:::teal

&#x20;   fft\_c\["fft\_core1: I2S \& FFT - Core 1 task"]:::teal

&#x20;   ir\_c\["ir\_core1: RMT IR Decoders - Core 1 task"]:::teal

&#x20;   aleds\_c\["aleds\_rgb: Native Pixel Driver"]:::teal

&#x20; end



&#x20; main --> fft\_c

&#x20; effects --> leddisplay\_c

&#x20; main --> ir\_c

&#x20; init --> aleds\_c



&#x20; classDef indigo stroke:#818cf8,fill:#eef2ff;

&#x20; classDef teal stroke:#2dd4bf,fill:#f0fdfa;```

### 1\. Python Application \& Drivers

* **\[main.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/main.py):** The master coordinator and scheduler. Drives the main loop, manages targeted frame rates (FPS limiting), processes IR actions, tracks UI overlay message timeouts, handles menu states, polls the web server, and automatically advances between visual scenes.
* **\[init.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/init.py):** Initializes hardware peripherals, manages RTC fallback, connects to local Wi-Fi, retrieves time via NTP, reads temperature/pressure/light sensors, calculates gamma-correction lookup tables, saves persistent settings, and manages PIR-based deep sleep transitions.
* **\[web\_server.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/web\_server.py):** Non-blocking HTTP socket server running on Core 0. Streams API status and effects catalog lists efficiently, and serves PWA static files.
* **\[effects.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/effects.py):** The primary effects engine. Features the massive `AudioEffects` class containing advanced rendering code: split audio bars, gravity oscillators, comets, analog/digital clock overlays, noise gates, and color filters.
* **\[helpers.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/helpers.py):** Mathematics library containing fast linear interpolation (`lerp`), `smoothstep`, beat validation thresholds, and helper methods to query, scale, and offset color palettes in real-time.
* **\[ir\_remote\_mapper.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/ir\_remote\_mapper.py):** Handles IR input matching and dynamic learning sequences. Parses configuration commands from flash (`/ir\_map.conf`) and assigns raw codes to application events.

### 2\. Custom C Modules (The "Superpowers")

To achieve maximum rendering speed, the system offloads critical CPU-intensive logic to native C modules placed in \[custom\_modules/](file:///h:/Mój dysk/CLeds/CLeds\_leds/custom\_modules):

* **\[leddisplay](file:///h:/Mój dysk/CLeds/CLeds\_leds/custom\_modules/leddisplay/README.md):**
A high-speed LED text grid layout renderer. Manages up to 8 independent rendering horizontal zones, smooth sliding and fading character-level transitions, custom scrolling speeds, and character/zone blinking masks. It uses a built-in `4x7` font and supports dynamic font dictionaries loaded at runtime with zero memory allocation.
* **\[fft\_core1](file:///h:/Mój dysk/CLeds/CLeds\_leds/custom\_modules/fft\_core1/README.md):**
Processes incoming I2S audio samples directly from the microphone in a dedicated FreeRTOS task pinned to **Core 1**. It performs Hanning windowing, Radix-2 FFT, logarithmic band grouping (up to 24 bands), and extracts spectral flux features (energy, BPM, and beat indicators). Results are exposed directly to MicroPython as zero-allocation read-only buffers (`memoryview`).
* **\[ir\_core1](file:///h:/Mój dysk/CLeds/CLeds\_leds/custom\_modules/ir\_core1/README.md):**
Uses the ESP32-S3's hardware RMT peripheral to decode incoming IR commands in a non-blocking background task on **Core 1**. Supports NEC and generic LED protocols with long-press thresholds, incorporating workarounds for ESP32-S3 RMT hardware lockups.
* **\[aleds\_rgb](file:///h:/Mój dysk/CLeds/CLeds\_leds/custom\_modules/aleds\_rgb/README.md):**
An optimized, native C driver for addressable RGB LED strips. Replaces slow Python pixel loops with fast C buffer serialization, supporting custom timing tables, brightness adjustments, color component orders (e.g., GRB, RGB), and direct array-like subscription indexing.

\---

## 📁 File Structure

```text
CLeds\_leds/
├── custom\_modules/         # MicroPython Custom C Modules
│   ├── aleds\_rgb/          # WS2812 native C driver
│   ├── fft\_core1/          # Core 1 I2S \& Audio FFT processor
│   ├── ir\_core1/           # Core 1 hardware RMT IR decoder
│   └── leddisplay/         # Text formatting and matrix layout engine
├── lib/                    # Python library modules \& drivers
│   ├── astro3.py           # Sun calculations (sunrise, sunset, twilight)
│   ├── bh1750.py           # BH1750 luminance sensor driver
│   ├── bme280.py           # BME280 temperature, humidity, \& pressure driver
│   ├── ds3231.py           # DS3231 high-precision I2C RTC driver
│   ├── settings\_manager.py # JSON configuration file serializer
│   ├── switches.py         # Rotary encoders, buttons, and joystick debouncers
│   └── wifi\_manager.py     # WiFi connection manager
├── credentials.py          # Local WiFi and API credentials configuration
├── effects.py              # Visual effect render routines and calculations
├── helpers.py              # Fast color lookups and interpolation utilities
├── icon.svg                # Vector icon asset for the PWA grid
├── index.html              # Single-page PWA control panel and dashboard
├── init.py                 # Hardware initializations and timer services
├── ir\_map.conf             # Decoded IR actions configuration map
├── ir\_remote\_mapper.py     # IR code recorder and command mapper
├── main.py                 # Application bootstrapper and scheduling loop
├── manifest.json           # Web app configuration manifest for PWA installation
├── scenarios.json          # Preconfigured visual scenes database (scenarios)
├── settings.json           # User preferences and startup settings
├── sw.js                   # Service Worker script for offline static caching
└── web\_server.py           # HTTP server for status updates and remote actions
```

\---

## ⚙️ Build and Compilation Guide

To integrate the custom C modules and build your own CLeds MicroPython firmware:

1. **Clone MicroPython Repository:**

```bash
   git clone https://github.com/micropython/micropython.git
   cd micropython
   git checkout v1.28.0  # Or compatible version
   ```

2. **Register Custom C Modules:**
Create or update a `micropython.cmake` file in your custom modules directory (e.g., `custom\_modules/`) containing links to each module:

```cmake
   # Include all custom subdirectories
   include(${CMAKE\_CURRENT\_LIST\_DIR}/aleds\_rgb/micropython.cmake)
   include(${CMAKE\_CURRENT\_LIST\_DIR}/fft\_core1/micropython.cmake)
   include(${CMAKE\_CURRENT\_LIST\_DIR}/ir\_core1/micropython.cmake)
   include(${CMAKE\_CURRENT\_LIST\_DIR}/leddisplay/micropython.cmake)
   ```

3. **Build the Firmware for ESP32-S3:**
Use the ESP-IDF toolchain configured for your board:

```bash
   cd ports/esp32
   make submodules
   make BOARD=ESP32\_GENERIC\_S3 USER\_C\_MODULES=/path/to/CLeds\_leds/custom\_modules
   ```

4. **Flash to Device:**

```bash
   esptool.py --chip esp32s3 --port /dev/ttyUSB0 write\_flash -z 0x0 firmware.bin
   ```

\---

## 🎮 Setup \& Usage

### 1\. Configure Credentials

Edit the \[credentials.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/credentials.py) file to set up your network details:

```python
WIFI\_SSID = "Your\_WiFi\_SSID"
WIFI\_PASSWORD = "Your\_WiFi\_Password"
WIFI\_AP\_SSID = "ESP32-AP"         # Fallback Access Point SSID
WIFI\_AP\_PASSWORD = "password123"   # AP Password
OPENWEATHER\_API\_KEY = "..."       # Optional Weather API Key
```

### 2\. Learn or Map IR Remote Commands

On startup, if `IR\_CONFIG\_READY` is set to `False` in \[main.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/main.py#L43), the system will enter **IR learning mode**.

* Follow the serial output prompt on stdout (REPL interface).
* Press the corresponding button on your remote control for each mapped action.
* The system will automatically write the mapped result to `/ir\_map.conf`.
* Once finished, set `IR\_CONFIG\_READY = True` in \[main.py](file:///h:/Mój dysk/CLeds/CLeds\_leds/main.py#L43).

### 3\. Customize Scenarios

You can edit \[scenarios.json](file:///h:/Mój dysk/CLeds/CLeds\_leds/scenarios.json) to append new visual modes or alter properties. For example:

```json
{
  "mode": "plasma",
  "speed": 0.5,
  "ghosting": 0.95,
  "desc": "Slow Ghostly Plasma"
}
```

The system automatically loads these scenarios on boot and provides controls to cycle between them using physical buttons or IR mapping commands.

### 4\. PWA Dashboard \& Remote Control

Once Wi-Fi connects (in STA client mode or AP fallback mode), the controller starts a non-blocking web server on port 80.

* **Accessing the Dashboard:** Open your browser and navigate to `http://<device-ip>/`.
* **PWA Installation:** Open the browser menu and select **Add to Home Screen** (or tap **Install** on the prompt banner) to run CLeds as a standalone offline application.
* **Static IP Address:** If you want a fixed address, go to the settings panel in the PWA, enable **Static IP**, enter your preferred network settings (e.g. static IP: `192.168.101.150`), and save.
* **Quick Favorites:** Click the **star button** next to the scenario selector to add an effect to your favorites. A new **⭐ Quick Favorites** section will instantly appear for fast one-tap activations.
* **Clock Sync \& DST:** Any changes to time zone offsets or the Daylight Saving Time (DST) switch will immediately shift the system and external RTC clocks in real-time.

\---

## 📜 License

This project is licensed under the PolyForm Noncommercial License 1.0.0 - see the LICENSE details for info.
Copyright (c) Tomasz Zgrys (Digital-Apprentice) - 2022-2026.


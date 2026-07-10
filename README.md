# CLeds Controller System V2

CLeds is a high-performance, real-time sound-reactive LED display and physics-based animation system designed for the **ESP32-S3** microcontroller running custom **MicroPython** firmware. 

By offloading timing-critical tasks (such as pixel rendering, I2S audio capture, Fast Fourier Transform (FFT) analysis, and infrared decoding) to custom native C modules running asynchronously on **Core 1**, CLeds achieves extremely smooth visual rendering (up to 25+ FPS) without blocking the MicroPython interpreter or disrupting Wi-Fi operations on Core 0.

---

## 🚀 Key Features

* **Progressive Web App (PWA) Dashboard:** Integrates a responsive, glassmorphic PWA that works offline. Allows full control over active modes, effect scenarios, dynamic parameters, autoplay timers, timezone settings, and quick favorites, alongside real-time monitoring of internal telemetry and external OpenWeatherMap forecast data.
* **Static IP Connection:** Supports configuring a fixed IP address to connect directly without searching the serial console for DHCP leases.
* **Dual LED Strip Controller:** Drives two physical, addressable LED grids (e.g., WS2812B strips on `LED1` and `LED2`) with separate config parameters and render loops.
* **Text Overlay Engine:** Renders zoned layout overlays (static text, scrolling text, or dynamic clock time) directly over active visual effects.
* **Sound-Reactive Visualizations:** Real-time audio spectrum analysis grouping audio inputs into logarithmic bands, detecting BPM/beat markers, and mapping raw frequencies to visual dynamics.
* **Physics & Particles Engine:** Real-time particle simulations including gravity wells, spring forces, bouncing physics, comets, orbits, and black holes.
* **Multi-Sensor Integration:** Collects environmental data (temperature, humidity, barometric pressure) and ambient light levels (luminance in lux) to dynamically adjust LED behavior.
* **Astronomic & NTP Clock Sync:** Synchronizes high-precision hardware real-time clock (RTC) via NTP and calculates sunrise/sunset positions for automatic night-time dimming.
* **Motion-Activated Power Savings:** Integrates a PIR motion sensor to automatically put the device into lightsleep mode when no presence is detected, waking up instantly on movement.
* **Infrared Control:** Includes a non-blocking IR remote decoder and recording sequence allowing users to adjust parameters, select effects, and cycle favorite presets.

---

## 🔌 Hardware Pin Configuration (ESP32-S3)

Below is the pin assignment configured in [init.py](file:///h:/Mój dysk/CLeds/CLeds_leds/init.py):

| Component / Function | GPIO Pin | Type | Details |
| :--- | :--- | :--- | :--- |
| **LED1 Control Pin** | `GPIO 2` | Output | WS2812B LED grid 1 driver |
| **LED2 Control Pin** | `GPIO 42` | Output | WS2812B LED grid 2 driver |
| **I2C SCL** | `GPIO 47` | Output | SoftI2C Clock for sensors |
| **I2C SDA** | `GPIO 21` | In/Out | SoftI2C Data for sensors |
| **I2S SCK (BCLK)** | `GPIO 13` | Output | Audio I2S Bit Clock |
| **I2S WS (LRCK)** | `GPIO 12` | Output | Audio I2S Word Select |
| **I2S SD (DIN)** | `GPIO 14` | Input | Audio I2S Data (INMP441) |
| **IR Receiver OUT** | `GPIO 39` | Input | Infrared receiver module (TSOP38238) |
| **Active Buzzer** | `GPIO 45` | Output | Acoustic signal buzzer |
| **PIR Motion Sensor** | `GPIO 20` | Input | Presence detector (Ext0 wakeup pin) |
| **B1 Button (L)** | `GPIO 7` | Input | Physical interrupt-driven buttons |
| **B2 Button (R)** | `GPIO 4` | Input | Physical interrupt-driven buttons |
| **B3 Button (Minus)**| `GPIO 5` | Input | Physical interrupt-driven buttons |
| **B4 Button (Plus)** | `GPIO 6` | Input | Physical interrupt-driven buttons |
| **B5 Button (Center)**| `GPIO 15`| Input | Physical interrupt-driven buttons |
| **B6 Button (L1)** | `GPIO 41`| Input | Physical interrupt-driven buttons |
| **B7 Button (L2)** | `GPIO 40`| Input | Physical interrupt-driven buttons |

---

## 🏗️ System Architecture

CLeds is divided into two distinct execution layers to ensure both performance and ease of configuration:

```mermaid
graph TD
    subgraph MicroPython Layer (Core 0)
        main[main.py: App Loop & Controls] --> init[init.py: Hardware & Sensors]
        main --> effects[effects.py: Visual Renderers]
        effects --> helpers[helpers.py: Math & Colors]
        main --> mapper[ir_remote_mapper.py: Action Mapper]
        main --> web[web_server.py: Non-Blocking Web Server]
        init --> wifi[wifi_manager.py]
        init --> bme[bme280.py]
        init --> bh[bh1750.py]
        init --> ds[ds3231.py]
    end
    
    subgraph Custom C Modules (Core 1 / Hardware)
        leddisplay_c[leddisplay: Text Rendering & Layout]
        fft_c[fft_core1: I2S & FFT - Core 1 task]
        ir_c[ir_core1: RMT IR Decoders - Core 1 task]
        aleds_c[aleds_rgb: Native Pixel Driver]
    end

    effects --> leddisplay_c
    main --> ir_c
    init --> aleds_c
    main --> fft_c
```

### 1. Python Application & Drivers
* **[main.py](file:///h:/Mój dysk/CLeds/CLeds_leds/main.py):** The master coordinator and scheduler. Drives the main loop, manages targeted frame rates (FPS limiting), processes IR actions, tracks UI overlay message timeouts, handles menu states, polls the web server, and automatically advances between visual scenes.
* **[init.py](file:///h:/Mój dysk/CLeds/CLeds_leds/init.py):** Initializes hardware peripherals, manages RTC fallback, connects to local Wi-Fi, retrieves time via NTP, reads temperature/pressure/light sensors, calculates gamma-correction lookup tables, saves persistent settings, and manages PIR-based deep sleep transitions.
* **[web_server.py](file:///h:/Mój dysk/CLeds/CLeds_leds/web_server.py):** Non-blocking HTTP socket server running on Core 0. Streams API status and effects catalog lists efficiently, and serves PWA static files.
* **[effects.py](file:///h:/Mój dysk/CLeds/CLeds_leds/effects.py):** The primary effects engine. Features the massive `AudioEffects` class containing advanced rendering code: split audio bars, gravity oscillators, comets, analog/digital clock overlays, noise gates, and color filters.
* **[helpers.py](file:///h:/Mój dysk/CLeds/CLeds_leds/helpers.py):** Mathematics library containing fast linear interpolation (`lerp`), `smoothstep`, beat validation thresholds, and helper methods to query, scale, and offset color palettes in real-time.
* **[ir_remote_mapper.py](file:///h:/Mój dysk/CLeds/CLeds_leds/ir_remote_mapper.py):** Handles IR input matching and dynamic learning sequences. Parses configuration commands from flash (`/ir_map.conf`) and assigns raw codes to application events.

### 2. Custom C Modules (The "Superpowers")
To achieve maximum rendering speed, the system offloads critical CPU-intensive logic to native C modules placed in [custom_modules/](file:///h:/Mój dysk/CLeds/CLeds_leds/custom_modules):

* **[leddisplay](file:///h:/Mój dysk/CLeds/CLeds_leds/custom_modules/leddisplay/README.md):** 
  A high-speed LED text grid layout renderer. Manages up to 8 independent rendering horizontal zones, smooth sliding and fading character-level transitions, custom scrolling speeds, and character/zone blinking masks. It uses a built-in `4x7` font and supports dynamic font dictionaries loaded at runtime with zero memory allocation.
* **[fft_core1](file:///h:/Mój dysk/CLeds/CLeds_leds/custom_modules/fft_core1/README.md):** 
  Processes incoming I2S audio samples directly from the microphone in a dedicated FreeRTOS task pinned to **Core 1**. It performs Hanning windowing, Radix-2 FFT, logarithmic band grouping (up to 24 bands), and extracts spectral flux features (energy, BPM, and beat indicators). Results are exposed directly to MicroPython as zero-allocation read-only buffers (`memoryview`).
* **[ir_core1](file:///h:/Mój dysk/CLeds/CLeds_leds/custom_modules/ir_core1/README.md):** 
  Uses the ESP32-S3's hardware RMT peripheral to decode incoming IR commands in a non-blocking background task on **Core 1**. Supports NEC and generic LED protocols with long-press thresholds, incorporating workarounds for ESP32-S3 RMT hardware lockups.
* **[aleds_rgb](file:///h:/Mój dysk/CLeds/CLeds_leds/custom_modules/aleds_rgb/README.md):** 
  An optimized, native C driver for addressable RGB LED strips. Replaces slow Python pixel loops with fast C buffer serialization, supporting custom timing tables, brightness adjustments, color component orders (e.g., GRB, RGB), and direct array-like subscription indexing.

---

## 📁 File Structure

```text
CLeds_leds/
├── custom_modules/         # MicroPython Custom C Modules
│   ├── aleds_rgb/          # WS2812 native C driver
│   ├── fft_core1/          # Core 1 I2S & Audio FFT processor
│   ├── ir_core1/           # Core 1 hardware RMT IR decoder
│   └── leddisplay/         # Text formatting and matrix layout engine
├── lib/                    # Python library modules & drivers
│   ├── astro3.py           # Sun calculations (sunrise, sunset, twilight)
│   ├── bh1750.py           # BH1750 luminance sensor driver
│   ├── bme280.py           # BME280 temperature, humidity, & pressure driver
│   ├── ds3231.py           # DS3231 high-precision I2C RTC driver
│   ├── settings_manager.py # JSON configuration file serializer
│   ├── switches.py         # Rotary encoders, buttons, and joystick debouncers
│   └── wifi_manager.py     # WiFi connection manager
├── credentials.py          # Local WiFi and API credentials configuration
├── effects.py              # Visual effect render routines and calculations
├── helpers.py              # Fast color lookups and interpolation utilities
├── icon.svg                # Vector icon asset for the PWA grid
├── index.html              # Single-page PWA control panel and dashboard
├── init.py                 # Hardware initializations and timer services
├── ir_map.conf             # Decoded IR actions configuration map
├── ir_remote_mapper.py     # IR code recorder and command mapper
├── main.py                 # Application bootstrapper and scheduling loop
├── manifest.json           # Web app configuration manifest for PWA installation
├── scenarios.json          # Preconfigured visual scenes database (scenarios)
├── settings.json           # User preferences and startup settings
├── sw.js                   # Service Worker script for offline static caching
└── web_server.py           # HTTP server for status updates and remote actions
```

---

## ⚙️ Build and Compilation Guide

To integrate the custom C modules and build your own CLeds MicroPython firmware:

1. **Clone MicroPython Repository:**
   ```bash
   git clone https://github.com/micropython/micropython.git
   cd micropython
   git checkout v1.28.0  # Or compatible version
   ```

2. **Register Custom C Modules:**
   Create or update a `micropython.cmake` file in your custom modules directory (e.g., `custom_modules/`) containing links to each module:
   ```cmake
   # Include all custom subdirectories
   include(${CMAKE_CURRENT_LIST_DIR}/aleds_rgb/micropython.cmake)
   include(${CMAKE_CURRENT_LIST_DIR}/fft_core1/micropython.cmake)
   include(${CMAKE_CURRENT_LIST_DIR}/ir_core1/micropython.cmake)
   include(${CMAKE_CURRENT_LIST_DIR}/leddisplay/micropython.cmake)
   ```

3. **Build the Firmware for ESP32-S3:**
   Use the ESP-IDF toolchain configured for your board:
   ```bash
   cd ports/esp32
   make submodules
   make BOARD=ESP32_GENERIC_S3 USER_C_MODULES=/path/to/CLeds_leds/custom_modules
   ```

4. **Flash to Device:**
   ```bash
   esptool.py --chip esp32s3 --port /dev/ttyUSB0 write_flash -z 0x0 firmware.bin
   ```

---

## 🎮 Setup & Usage

### 1. Configure Credentials
Edit the [credentials.py](file:///h:/Mój dysk/CLeds/CLeds_leds/credentials.py) file to set up your network details:
```python
WIFI_SSID = "Your_WiFi_SSID"
WIFI_PASSWORD = "Your_WiFi_Password"
WIFI_AP_SSID = "ESP32-AP"         # Fallback Access Point SSID
WIFI_AP_PASSWORD = "password123"   # AP Password
OPENWEATHER_API_KEY = "..."       # Optional Weather API Key
```

### 2. Learn or Map IR Remote Commands
On startup, if `IR_CONFIG_READY` is set to `False` in [main.py](file:///h:/Mój dysk/CLeds/CLeds_leds/main.py#L43), the system will enter **IR learning mode**.
* Follow the serial output prompt on stdout (REPL interface).
* Press the corresponding button on your remote control for each mapped action.
* The system will automatically write the mapped result to `/ir_map.conf`.
* Once finished, set `IR_CONFIG_READY = True` in [main.py](file:///h:/Mój dysk/CLeds/CLeds_leds/main.py#L43).

### 3. Customize Scenarios
You can edit [scenarios.json](file:///h:/Mój dysk/CLeds/CLeds_leds/scenarios.json) to append new visual modes or alter properties. For example:
```json
{
  "mode": "plasma",
  "speed": 0.5,
  "ghosting": 0.95,
  "desc": "Slow Ghostly Plasma"
}
```

The system automatically loads these scenarios on boot and provides controls to cycle between them using physical buttons or IR mapping commands.

### 4. PWA Dashboard & Remote Control
Once Wi-Fi connects (in STA client mode or AP fallback mode), the controller starts a non-blocking web server on port 80.
* **Accessing the Dashboard:** Open your browser and navigate to `http://<device-ip>/`.
* **PWA Installation:** Open the browser menu and select **Add to Home Screen** (or tap **Install** on the prompt banner) to run CLeds as a standalone offline application.
* **Static IP Address:** If you want a fixed address, go to the settings panel in the PWA, enable **Static IP**, enter your preferred network settings (e.g. static IP: `192.168.101.150`), and save.
* **Quick Favorites:** Click the **star button** next to the scenario selector to add an effect to your favorites. A new **⭐ Quick Favorites** section will instantly appear for fast one-tap activations.
* **Clock Sync & DST:** Any changes to time zone offsets or the Daylight Saving Time (DST) switch will immediately shift the system and external RTC clocks in real-time.

---

## 📜 License
This project is licensed under the MIT License - see the LICENSE details for info.
Copyright (c) Tomasz Zgrys (Digital-Apprentice) - 2022-2026.

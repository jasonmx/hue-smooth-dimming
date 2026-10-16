# Hue Smooth Dimmer

Smooth, continuous dimming for Philips Hue lights in Home Assistant. Plus: set brightness, color temperature, color and scenes **without turning the lights on**.

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz/) ![Installs](https://img.shields.io/badge/dynamic/json?color=blue&label=Installs&query=hue_dimmer.total&url=https://analytics.home-assistant.io/custom_integrations.json) [![Latest Version](https://img.shields.io/github/v/release/jasonmx/philips-hue-smooth-dimmer?sort=date)](https://github.com/jasonmx/philips-hue-smooth-dimmer/releases) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/jasonmx)

This integration extends the core Philips Hue integration and lets you:
* **Smooth Dimming:** use third-party buttons to dim your Hue lights smoothly.
* **Set Lights While Off:** set scenes, brightness, color and color temperature without turning the lights on.

## How It Helps You 🔅💡🔆

* **Smooth Dimming:** Dimming is continuous and precise. No more jittery repeat loops and dimming overshoots.
* **Set While Off:** Prepare your lights to turn on how you want them. No more color flashes or brightness extremes as lights turn on.
* **Zero Setup:** Finds your lights automatically via the core Philips Hue integration.

## Get Started

### Requirements
* Philips Hue Bridge V2 or Pro (V3)
* **[Philips Hue integration](https://www.home-assistant.io/integrations/hue)** set up and connected to that bridge
* Not supported: Hue bulbs paired directly to Zigbee2MQTT, ZHA or deCONZ without a bridge

### Install from HACS
1. Open the Hue Smooth Dimmer HACS repository

[![Open the Hue Smooth Dimmer HACS repository in your Home Assistant instance.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jasonmx&repository=philips-hue-smooth-dimmer&category=integration)

2. Click **Download**
3. Restart Home Assistant
4. Add the integration

[![Add Hue Smooth Dimmer to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hue_dimmer)

## Usage

### Smooth Dimming

Use these 3 actions in the HA Automations editor:

| Action | Description |
| :--- | :--- |
| `hue_dimmer.raise` | Start raising brightness |
| `hue_dimmer.lower` | Start lowering brightness |
| `hue_dimmer.stop` | Freeze brightness |

| Field | Actions | Description |
| :--- | :--- | :--- |
| `target` | all | Hue lights and groups (required) |
| `sweep_time` | raise, lower | Duration of a full 0–100% sweep (default 5s) |
| `limit` | raise | Max brightness (default 100%) |
| `limit` | lower | Min brightness (default 0%). Light turns off at 0%. Choose 0.4%+ to keep light on |

To dim multiple lights perfectly, target a **Hue Group** instead of separate lights. Your Hue Bridge will then sync them with group-wide Zigbee messages.

#### YAML Example: Two-button dimmer

```yaml
left_button_held:
  - action: hue_dimmer.lower

right_button_held:
  - action: hue_dimmer.raise

buttons_released:
  - action: hue_dimmer.stop
```

---

### Set Scenes, Brightness, Color & Color Temperature While Light Is Off

Lets you set scenes, brightness, color and CT while lights are off, so that they turn on consistently how you want them without unwanted flashes.

| Action | Description |
| :--- | :--- |
| `hue_dimmer.set_scene` | Set a Hue scene without turning lights on |
| `hue_dimmer.set_attributes` | Set brightness, color temp or color without changing on/off state |
| `hue_dimmer.get_attributes` | Get brightness, color temp and color (RGB, HS, XY). Returns one record per target |

`get_attributes` reports a light's real values when it's off and during brightness transitions, when HA's reported values are wrong.

| Field | Actions | Description |
| :--- | :--- | :--- |
| `target` | set_scene | Hue scenes (required) |
| `target` | set_attributes, get_attributes | Hue lights and groups (required) |
| `brightness` | set_attributes | Brightness level (%) |
| `min_brightness` | set_attributes | Enforce a minimum brightness (%) |
| `max_brightness` | set_attributes | Enforce a maximum brightness (%) |
| `color_temp_kelvin` | set_attributes | Color temperature (K) |
| `rgb_color` | set_attributes | Color as `[red, green, blue]` (0–255 each) |
| `hs_color` | set_attributes | Color as `[hue, saturation]` (0–360, 0–100) |
| `xy_color` | set_attributes | Color as `[x, y]` |

#### Automation Examples

##### YAML Example: Set Scene for Next Turn-On

```yaml
description: Stage the Relax scene in the living room at 22:00, without turning the lights on.
triggers:
  - trigger: time
    at: "22:00:00"
actions:
  - action: hue_dimmer.set_scene
    target:
      entity_id: scene.living_room_relax
```

##### GUI Example: Set Next Turn-On Brightness

When lights turn off for an hour, set brightness for next turn-on.

![Set turn-on behavior](examples/update-lights-after-turn-off--step-2.png)

To set up this automation:

1. Go to **Settings > Automations**
2. Click **Create automation** and **Create new automation**
3. Open the ⋮ menu and switch view to **Edit in YAML**
4. Copy-paste the YAML below (replacing HA's placeholder YAML)
5. Switch view back to **Edit in visual editor**
6. Select the ["When something changes" entry](examples/update-lights-after-turn-off--step-1.png?raw=true) and add your Hue light(s).
7. Select the "Set turn-on behavior" entry and choose your settings. Don't touch the Targets section.
8. Click **Save**

```yaml
description: >
  When lights turn off for an hour, set brightness for next turn-on.
triggers:
  - trigger: state
    entity_id: []
    from:
      - "on"
    to:
      - "off"
    for:
      hours: 1
      minutes: 0
      seconds: 0
actions:
  - action: hue_dimmer.set_attributes
    target:
      entity_id: "{{ trigger.entity_id }}"
    data:
      max_brightness: 80
      min_brightness: 30
      alias: Set turn-on behavior for the lights
mode: parallel
max: 10
```

If you add more than 10 lights, increase "max: 10" accordingly.

***

## Known Limitation

**Brightness reports the end value during a transition.** When a raise or lower starts, the Hue bridge reports the target brightness straight away (for example 100%), then checks the light's real brightness about 10 seconds later. During that window, dashboards, switch indicators and automations that read brightness see the end value, not the light's actual level.

Dimming itself is unaffected: the integration tracks the real brightness internally, so stopping and restarting a dim carries on from where the light actually is. If an automation needs the real level mid-transition, read it with `hue_dimmer.get_attributes`, which returns the integration's predicted brightness rather than the bridge's end value.

***

## Uninstall

This integration follows standard integration removal.

1. Open the integration

[![Open the Hue Smooth Dimmer integration in your Home Assistant instance.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=hue_dimmer)

2. Open the ⋮ menu and choose **Delete**

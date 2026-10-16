# Release checklist

Run this on a live Home Assistant install with a real Hue bridge **before tagging any release or
release candidate**. It covers what CI can't: the bridge's actual transition and reporting behaviour.

Takes about ten minutes. Run the actions from **Developer Tools → Actions** in YAML mode. Replace
`light.test_lamp` with a dimmable, colour-capable Hue light and `light.test_room` with a Hue room or
zone that has at least two lights.

Keep **Settings → System → Logs** open, filtered on `hue_dimmer`.

## 0. Install

- [ ] Install the build being released (HACS: *Redownload* and pick the version, or copy
      `custom_components/hue_dimmer/` over the old one). Restart HA.
- [ ] Write down the HA version and bridge model and firmware. They go in the release notes.

## 1. Load and lifecycle

- [ ] *Settings → Devices & services*: Hue Smooth Dimmer shows as loaded, and the log has no errors.
- [ ] Reload the integration (⋮ → *Reload*). Then run step 2.1. It still works.
- [ ] Disable the integration entry, call any `hue_dimmer` action: it fails with a "not loaded"
      message, not "action not found". Re-enable it.

## 2. Transitions (run each on `light.test_lamp`, then `light.test_room`)

1. [ ] **Raise.** Set the light to about 20%, then:
   ```yaml
   action: hue_dimmer.raise
   target: { entity_id: light.test_lamp }
   data: { sweep_time: 5 }
   ```
   Brightness climbs smoothly to 100% in about 4 seconds, with no steps or flashes.
2. [ ] **Lower to off.** `hue_dimmer.lower` with no data. Fades smoothly and the light **turns off**
      at the end.
3. [ ] **Raise from off.** With the light off, `hue_dimmer.raise`. The light turns on and climbs from
      the bottom. It doesn't jump to its previous brightness first.
4. [ ] **Lower to a limit.** From 100%, `hue_dimmer.lower` with `data: { limit: 30 }`. Stops at 30%
      and stays on.
5. [ ] **Dim, stop, dim** (the core behaviour). `raise` with `sweep_time: 10` from 10%. After about
      3 seconds call `hue_dimmer.stop`. Within 5 seconds call `raise` again. The light holds where
      it stopped, then continues **from that point**. It doesn't jump to 100% or back down. Repeat
      with `lower`.
6. [ ] **Stop when idle.** Call `hue_dimmer.stop` on a light that isn't moving. No visible change.
      Note whether the log shows anything (open question: should stop errors log at warning?).

## 3. Set attributes without turning on (run each on `light.test_lamp`, then `light.test_room`)

Lights and groups take different code paths: a group is written light by light, so check **every**
light in the room, not just the room's own state.

1. [ ] Turn the target off, then:
   ```yaml
   action: hue_dimmer.set_attributes
   target: { entity_id: light.test_lamp }
   data: { brightness: 40, color_temp_kelvin: 2700 }
   ```
   It **stays off**. Turn it on with a plain `light.turn_on`: it comes on at 40%, warm white (for the
   room, every light in it).
2. [ ] Turn it off, call `set_attributes` with `data: { rgb_color: [255, 0, 0] }`. Turn it on: red.
3. [ ] **Clamping.** Target on at 20%, `set_attributes` with `data: { min_brightness: 50 }`: goes to
      50%. Target at 70%, same call: no change.

## 4. Get attributes (run each on `light.test_lamp`, then `light.test_room`)

A group's values are the average of its member lights, so give every light in the room the same
settings first by repeating step 3.1.

1. [ ] Repeat step 3.1 and turn the target off, then:
   ```yaml
   action: hue_dimmer.get_attributes
   target: { entity_id: light.test_lamp }
   ```
   Tick *Return response*. Brightness is 40 and `color_temp_kelvin` about 2700, even though it's off.
2. [ ] **Mid-transition.** Start `raise` from 10% with `sweep_time: 10`. After about 3 seconds call
      `get_attributes`. Brightness is somewhere around 40%, **not** 100% (the bridge reports the end
      value; the integration predicts the real one).

## 5. Set scene

Use `light.test_room` and two of its static scenes with clearly different colours, here
`scene.test_room_a` and `scene.test_room_b`.

1. [ ] Recall A, turn the room off, then:
   ```yaml
   action: hue_dimmer.set_scene
   target: { entity_id: scene.test_room_b }
   ```
   The room **stays off**. Turn it on with a plain `light.turn_on`: every light comes on in B's
   colours and brightness.
2. [ ] With the room **on** in A, `set_scene` B. The lights change to B straight away and stay on.
3. [ ] **No stale snapshot.** Edit B in the Hue app (change one light's colour), turn the room off,
      `set_scene` B, turn it on. The edited colour is used.
4. [ ] **Off in scene.** Use a scene where one light is off. With the room on, `set_scene` it: that
      light turns off and the others change.
5. [ ] **All-Day scene.** Target an All-Day scene. Nothing changes, and the log shows the
      "doesn't support All-Day (smart) scenes yet" warning.
6. [ ] **Dynamic scene.** Room off, `set_scene` a dynamic scene, turn on. The lights come on in its
      first colours and don't animate.
7. [ ] **Large room.** On a room or zone with 10+ lights, every light updates and the log has no 429
      errors.
8. [ ] (Two bridges only) A scene on the second bridge works.

## 6. Wrap up

- [ ] The log has no new warnings or errors other than ones the steps above expected.
- [ ] Put the HA version, bridge model and firmware, and the date in the release notes or the
      release PR.

If any step fails, don't tag. File an issue with the step number and the log excerpt.

When a release adds or changes an action, add or update its steps here in the same PR.

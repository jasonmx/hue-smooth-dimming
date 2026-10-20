DOMAIN = "hue_dimmer"
NAME = "Hue Smooth Dimming"
LEGACY_NAMES = ("Philips Hue Smooth Dimmer", "Hue Smooth Dimmer")  # Earlier entry titles; migrated on setup

SERVICE_RAISE = "raise"
SERVICE_LOWER = "lower"
SERVICE_STOP = "stop"
SERVICE_SET_ATTRIBUTES = "set_attributes"
SERVICE_GET_ATTRIBUTES = "get_attributes"
SERVICE_SET_SCENE = "set_scene"

DEFAULT_SWEEP_TIME = 5
DEFAULT_MAX_BRIGHTNESS = 100.0
DEFAULT_MIN_BRIGHTNESS = 0.0

API_SETTLE_SECONDS = 15

MIN_BRIGHTNESS_STEP = 0.4  # 1/254, the smallest step a Hue light can make
BRIGHTNESS_EPSILON = 0.1  # Below this, brightness counts as zero or unchanged

DIR_UP = "up"
DIR_DOWN = "down"
DIR_NONE = "none"

// MediaHub motion vocabulary — GENERATED from src/mediahub/motion/.
// Do not edit by hand; run scripts/regen_motion_tokens.py.
// The single source of truth is the Python preset registry; a guard
// test (tests/test_motion_tokens_sync.py) fails if this drifts.

export type MotionKeyframe = { offset: number; value: number; easing: string };
export type MotionChannels = Record<string, MotionKeyframe[]>;
export type MotionPresetTokens = {
  name: string;
  family: string;
  energy: string;
  direction: string;
  durationFrames: number;
  loop: boolean;
  photo: boolean;
  channels: MotionChannels;
};
export type MotionTokenBundle = {
  version: number;
  fps: number;
  easings: Record<string, { bezier: number[] }>;
  presets: Record<string, MotionPresetTokens>;
  reduced: Record<string, MotionPresetTokens>;
};

export const MOTION_TOKENS: MotionTokenBundle = {
  "easings": {
    "ease_in_cubic": {
      "bezier": [
        0.55,
        0.055,
        0.675,
        0.19
      ]
    },
    "ease_in_out_cubic": {
      "bezier": [
        0.645,
        0.045,
        0.355,
        1.0
      ]
    },
    "ease_in_out_sine": {
      "bezier": [
        0.445,
        0.05,
        0.55,
        0.95
      ]
    },
    "ease_in_quad": {
      "bezier": [
        0.55,
        0.085,
        0.68,
        0.53
      ]
    },
    "ease_out_back": {
      "bezier": [
        0.34,
        1.56,
        0.64,
        1.0
      ]
    },
    "ease_out_cubic": {
      "bezier": [
        0.215,
        0.61,
        0.355,
        1.0
      ]
    },
    "ease_out_expo": {
      "bezier": [
        0.19,
        1.0,
        0.22,
        1.0
      ]
    },
    "ease_out_quad": {
      "bezier": [
        0.25,
        0.46,
        0.45,
        0.94
      ]
    },
    "linear": {
      "bezier": [
        0.0,
        0.0,
        1.0,
        1.0
      ]
    }
  },
  "fps": 30,
  "presets": {
    "blur_in": {
      "channels": {
        "blur": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 16.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ],
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.7,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 14,
      "energy": "calm",
      "family": "in",
      "loop": false,
      "name": "blur_in",
      "photo": false
    },
    "breathe": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.5,
            "value": 1.03
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 96,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "breathe",
      "photo": false
    },
    "drift": {
      "channels": {
        "translateX": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.5,
            "value": 6.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 90,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "drift",
      "photo": false
    },
    "drop_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.3,
            "value": 1.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": -64.0
          },
          {
            "easing": "ease_out_back",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "down",
      "durationFrames": 16,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "drop_in",
      "photo": false
    },
    "fade_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 12,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "fade_in",
      "photo": false
    },
    "fade_out": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 8,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "fade_out",
      "photo": false
    },
    "float": {
      "channels": {
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.5,
            "value": -8.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 84,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "float",
      "photo": false
    },
    "ken_burns_in": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 1.06
          }
        ]
      },
      "direction": "in",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "ken_burns_in",
      "photo": true
    },
    "ken_burns_out": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.06
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "out",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "ken_burns_out",
      "photo": true
    },
    "pan_down": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.08
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.08
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 48.0
          }
        ]
      },
      "direction": "down",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "pan_down",
      "photo": true
    },
    "pan_left": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.08
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.08
          }
        ],
        "translateX": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": -48.0
          }
        ]
      },
      "direction": "left",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "pan_left",
      "photo": true
    },
    "pan_right": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.08
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.08
          }
        ],
        "translateX": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 48.0
          }
        ]
      },
      "direction": "right",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "pan_right",
      "photo": true
    },
    "pan_up": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.08
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.08
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": -48.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": true,
      "name": "pan_up",
      "photo": true
    },
    "pop": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.4,
            "value": 1.0
          }
        ],
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.6
          },
          {
            "easing": "ease_out_back",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "in",
      "durationFrames": 12,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "pop",
      "photo": false
    },
    "pulse": {
      "channels": {
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.5,
            "value": 1.06
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 48,
      "energy": "standard",
      "family": "loop",
      "loop": true,
      "name": "pulse",
      "photo": false
    },
    "rise": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.7,
            "value": 1.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 40.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 16,
      "energy": "calm",
      "family": "in",
      "loop": false,
      "name": "rise",
      "photo": false
    },
    "scale_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.6,
            "value": 1.0
          }
        ],
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.82
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "in",
      "durationFrames": 14,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "scale_in",
      "photo": false
    },
    "sink": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_quad",
            "offset": 1.0,
            "value": 0.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_cubic",
            "offset": 1.0,
            "value": 24.0
          }
        ]
      },
      "direction": "down",
      "durationFrames": 10,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "sink",
      "photo": false
    },
    "slide_left": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.6,
            "value": 1.0
          }
        ],
        "translateX": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 64.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "left",
      "durationFrames": 14,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_left",
      "photo": false
    },
    "slide_right": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.6,
            "value": 1.0
          }
        ],
        "translateX": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": -64.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "right",
      "durationFrames": 14,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_right",
      "photo": false
    },
    "slide_up": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.6,
            "value": 1.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 60.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 14,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_up",
      "photo": false
    },
    "snap_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.35,
            "value": 1.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 28.0
          },
          {
            "easing": "ease_out_expo",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 10,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "snap_in",
      "photo": false
    },
    "tumble": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 0.6,
            "value": 1.0
          }
        ],
        "rotate": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": -12.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ],
        "translateY": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 36.0
          },
          {
            "easing": "ease_out_cubic",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 18,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "tumble",
      "photo": false
    },
    "wiggle": {
      "channels": {
        "rotate": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.25,
            "value": 2.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 0.75,
            "value": -2.0
          },
          {
            "easing": "ease_in_out_sine",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 36,
      "energy": "electric",
      "family": "loop",
      "loop": true,
      "name": "wiggle",
      "photo": false
    },
    "zoom_out": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_quad",
            "offset": 1.0,
            "value": 0.0
          }
        ],
        "scale": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_cubic",
            "offset": 1.0,
            "value": 0.9
          }
        ]
      },
      "direction": "out",
      "durationFrames": 10,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "zoom_out",
      "photo": false
    }
  },
  "reduced": {
    "blur_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 8,
      "energy": "calm",
      "family": "in",
      "loop": false,
      "name": "blur_in",
      "photo": false
    },
    "breathe": {
      "channels": {},
      "direction": "none",
      "durationFrames": 96,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "breathe",
      "photo": false
    },
    "drift": {
      "channels": {},
      "direction": "none",
      "durationFrames": 90,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "drift",
      "photo": false
    },
    "drop_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "down",
      "durationFrames": 8,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "drop_in",
      "photo": false
    },
    "fade_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "fade_in",
      "photo": false
    },
    "fade_out": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_quad",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "none",
      "durationFrames": 8,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "fade_out",
      "photo": false
    },
    "float": {
      "channels": {},
      "direction": "up",
      "durationFrames": 84,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "float",
      "photo": false
    },
    "ken_burns_in": {
      "channels": {},
      "direction": "in",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "ken_burns_in",
      "photo": true
    },
    "ken_burns_out": {
      "channels": {},
      "direction": "out",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "ken_burns_out",
      "photo": true
    },
    "pan_down": {
      "channels": {},
      "direction": "down",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "pan_down",
      "photo": true
    },
    "pan_left": {
      "channels": {},
      "direction": "left",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "pan_left",
      "photo": true
    },
    "pan_right": {
      "channels": {},
      "direction": "right",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "pan_right",
      "photo": true
    },
    "pan_up": {
      "channels": {},
      "direction": "up",
      "durationFrames": 120,
      "energy": "calm",
      "family": "loop",
      "loop": false,
      "name": "pan_up",
      "photo": true
    },
    "pop": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "in",
      "durationFrames": 8,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "pop",
      "photo": false
    },
    "pulse": {
      "channels": {},
      "direction": "none",
      "durationFrames": 48,
      "energy": "standard",
      "family": "loop",
      "loop": false,
      "name": "pulse",
      "photo": false
    },
    "rise": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 8,
      "energy": "calm",
      "family": "in",
      "loop": false,
      "name": "rise",
      "photo": false
    },
    "scale_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "in",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "scale_in",
      "photo": false
    },
    "sink": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_quad",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "down",
      "durationFrames": 8,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "sink",
      "photo": false
    },
    "slide_left": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "left",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_left",
      "photo": false
    },
    "slide_right": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "right",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_right",
      "photo": false
    },
    "slide_up": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "slide_up",
      "photo": false
    },
    "snap_in": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 8,
      "energy": "electric",
      "family": "in",
      "loop": false,
      "name": "snap_in",
      "photo": false
    },
    "tumble": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 0.0
          },
          {
            "easing": "ease_out_quad",
            "offset": 1.0,
            "value": 1.0
          }
        ]
      },
      "direction": "up",
      "durationFrames": 8,
      "energy": "standard",
      "family": "in",
      "loop": false,
      "name": "tumble",
      "photo": false
    },
    "wiggle": {
      "channels": {},
      "direction": "none",
      "durationFrames": 36,
      "energy": "electric",
      "family": "loop",
      "loop": false,
      "name": "wiggle",
      "photo": false
    },
    "zoom_out": {
      "channels": {
        "opacity": [
          {
            "easing": "ease_out_cubic",
            "offset": 0.0,
            "value": 1.0
          },
          {
            "easing": "ease_in_quad",
            "offset": 1.0,
            "value": 0.0
          }
        ]
      },
      "direction": "out",
      "durationFrames": 8,
      "energy": "standard",
      "family": "out",
      "loop": false,
      "name": "zoom_out",
      "photo": false
    }
  },
  "version": 1
} as const;

export default MOTION_TOKENS;

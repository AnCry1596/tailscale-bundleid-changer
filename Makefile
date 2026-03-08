THEOS_PACKAGE_SCHEME = rootless
ARCHS = arm64

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = Bypass

Bypass_FILES = Tweak.x
Bypass_CFLAGS = -fobjc-arc
Bypass_LDFLAGS = -ldl

# No filter — injected directly into Tailscale via dylib injection, not via substrate filter
# Bypass_FILTER = annnekkk.modified.tailscale

include $(THEOS)/makefiles/tweak.mk

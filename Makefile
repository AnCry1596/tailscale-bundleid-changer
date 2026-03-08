THEOS_PACKAGE_SCHEME = rootless
ARCHS = arm64

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = Bypass

Bypass_FILES = Tweak.x
Bypass_CFLAGS = -fobjc-arc

include $(THEOS)/makefiles/tweak.mk

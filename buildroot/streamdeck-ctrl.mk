################################################################################
#
# streamdeck-ctrl
#
################################################################################

STREAMDECK_CTRL_VERSION = 1.0.0
STREAMDECK_CTRL_SITE = $(call github,hackboxguy,streamdeck-ctrl,v$(STREAMDECK_CTRL_VERSION))
STREAMDECK_CTRL_LICENSE = MIT
STREAMDECK_CTRL_LICENSE_FILES = LICENSE

define STREAMDECK_CTRL_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/usr/lib/streamdeck-ctrl
	cp -r $(@D)/streamdeck_ctrl/*.py $(TARGET_DIR)/usr/lib/streamdeck-ctrl/

	mkdir -p $(TARGET_DIR)/usr/share/streamdeck-ctrl/fonts
	cp $(@D)/fonts/DejaVuSans-Bold.ttf $(TARGET_DIR)/usr/share/streamdeck-ctrl/fonts/

	mkdir -p $(TARGET_DIR)/usr/bin
	install -m 0755 $(@D)/buildroot/streamdeck-ctrl.wrapper \
		$(TARGET_DIR)/usr/bin/streamdeck-ctrl

	mkdir -p $(TARGET_DIR)/etc/streamdeck-ctrl/icons
	install -m 0644 $(@D)/config/example-layout.json \
		$(TARGET_DIR)/etc/streamdeck-ctrl/layout.json

	mkdir -p $(TARGET_DIR)/etc/udev/rules.d
	install -m 0644 $(@D)/99-streamdeck.rules \
		$(TARGET_DIR)/etc/udev/rules.d/99-streamdeck.rules

	mkdir -p $(TARGET_DIR)/etc/systemd/system
	sed -e 's|{INSTALL_DIR}|/usr/lib/streamdeck-ctrl|g' \
		-e 's|{USER}|root|g' \
		-e 's|{CONFIG_PATH}|/etc/streamdeck-ctrl/layout.json|g' \
		$(@D)/streamdeck-ctrl.service.in \
		> $(TARGET_DIR)/etc/systemd/system/streamdeck-ctrl.service

	mkdir -p $(TARGET_DIR)/etc/tmpfiles.d
	echo "d /run/streamdeck-ctrl 0755 root root -" > \
		$(TARGET_DIR)/etc/tmpfiles.d/streamdeck-ctrl.conf
endef

$(eval $(generic-package))

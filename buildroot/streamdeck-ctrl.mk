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
	# Install Python package preserving directory structure for imports
	mkdir -p $(TARGET_DIR)/usr/lib/streamdeck-ctrl/streamdeck_ctrl
	cp -r $(@D)/streamdeck_ctrl/*.py \
		$(TARGET_DIR)/usr/lib/streamdeck-ctrl/streamdeck_ctrl/

	# Install bundled font alongside the package
	mkdir -p $(TARGET_DIR)/usr/lib/streamdeck-ctrl/fonts
	cp $(@D)/fonts/DejaVuSans-Bold.ttf \
		$(TARGET_DIR)/usr/lib/streamdeck-ctrl/fonts/

	# Install wrapper script
	mkdir -p $(TARGET_DIR)/usr/bin
	install -m 0755 $(@D)/buildroot/streamdeck-ctrl.wrapper \
		$(TARGET_DIR)/usr/bin/streamdeck-ctrl

	# Install default config
	mkdir -p $(TARGET_DIR)/etc/streamdeck-ctrl/icons
	install -m 0644 $(@D)/config/example-layout.json \
		$(TARGET_DIR)/etc/streamdeck-ctrl/layout.json

	# Install udev rule
	mkdir -p $(TARGET_DIR)/etc/udev/rules.d
	install -m 0644 $(@D)/99-streamdeck.rules \
		$(TARGET_DIR)/etc/udev/rules.d/99-streamdeck.rules

	# Generate systemd service from template
	mkdir -p $(TARGET_DIR)/etc/systemd/system
	sed -e 's|{INSTALL_DIR}|/usr/lib/streamdeck-ctrl|g' \
		-e 's|{USER}|root|g' \
		-e 's|{CONFIG_PATH}|/etc/streamdeck-ctrl/layout.json|g' \
		$(@D)/streamdeck-ctrl.service.in \
		> $(TARGET_DIR)/etc/systemd/system/streamdeck-ctrl.service

	# Runtime directory for Unix socket
	mkdir -p $(TARGET_DIR)/etc/tmpfiles.d
	echo "d /run/streamdeck-ctrl 0755 root root -" > \
		$(TARGET_DIR)/etc/tmpfiles.d/streamdeck-ctrl.conf
endef

$(eval $(generic-package))

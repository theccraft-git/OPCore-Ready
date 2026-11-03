"""In-app USB port mapping.

Discovery and UTBMap.kext generation follow USBToolBox
(https://github.com/USBToolBox/tool) by Dhinak G. The Windows dump comes
from USBToolBox's usbdump.exe. OpCore then installs UTBMap.kext and
replaces the existing UTBDefault entry in config.plist without moving it.
"""

import binascii
import copy
import itertools
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time


USB_LOW = 0
USB_FULL = 1
USB_HIGH = 2
USB_SUPER = 3
USB_SUPER_PLUS = 4
USB_SPEED_UNKNOWN = 9999

USB_UHCI = 0x00
USB_OHCI = 0x10
USB_EHCI = 0x20
USB_XHCI = 0x30
USB_CONTROLLER_UNKNOWN = 9999

PORT_TYPE_NAMES = {
    0: "Type A",
    1: "Type Mini-AB",
    2: "ExpressCard",
    3: "USB 3 Type A",
    4: "USB 3 Type B",
    5: "USB 3 Type Micro-B",
    6: "USB 3 Type Micro-AB",
    7: "USB 3 Type Power-B",
    8: "Type C - USB 2 only",
    9: "Type C - with switch",
    10: "Type C - without switch",
    255: "Internal",
}

SPEED_NAMES = {
    USB_LOW: "USB 1.1",
    USB_FULL: "USB 1.1",
    USB_HIGH: "USB 2.0",
    USB_SUPER: "USB 3.0",
    USB_SUPER_PLUS: "USB 3.1 Gen 2",
    USB_SPEED_UNKNOWN: "Unknown",
}

CONTROLLER_NAMES = {
    USB_UHCI: "USB 1.1 (UHCI)",
    USB_OHCI: "USB 1.1 (OHCI)",
    USB_EHCI: "USB 2.0 (EHCI)",
    USB_XHCI: "USB 3.0 (XHCI)",
    USB_CONTROLLER_UNKNOWN: "Unknown",
}

CONNECTION_STATUS_NAMES = {
    0: "NoDeviceConnected",
    1: "DeviceConnected",
    2: "DeviceFailedEnumeration",
    3: "DeviceGeneralFailure",
    4: "DeviceCausedOvercurrent",
    5: "DeviceNotEnoughPower",
    6: "DeviceNotEnoughBandwidth",
    7: "DeviceHubNestedTooDeeply",
    8: "DeviceInLegacyHub",
    9: "DeviceEnumerating",
    10: "DeviceReset",
}

SERVICE_TO_CLASS = {
    "usbxhci": USB_XHCI,
    "usbehci": USB_EHCI,
    "usbohci": USB_OHCI,
    "usbuhci": USB_UHCI,
}

CREATE_NO_WINDOW = 0x08000000

INFO_PLIST_TEMPLATE = {
    "CFBundleDevelopmentRegion": "English",
    "CFBundleGetInfoString": "v1.1",
    "CFBundleIdentifier": "com.dhinakg.USBToolBox.map",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleName": "UTBMap",
    "CFBundlePackageType": "KEXT",
    "CFBundleShortVersionString": "1.1",
    "CFBundleSignature": "????",
    "CFBundleVersion": "1.1",
    "IOKitPersonalities": {},
    "OSBundleRequired": "Root",
}


def hexswap(input_hex):
    pairs = [input_hex[i:i + 2] for i in range(0, len(input_hex), 2)]
    return "".join(reversed(pairs)).upper()


def port_data(number):
    return binascii.a2b_hex(hexswap(hex(int(number))[2:].zfill(8)))


def kext_base_name(bundle_path):
    if not bundle_path:
        return ""
    return os.path.splitext(os.path.basename(str(bundle_path).replace("\\", "/")))[0].lower()


def replace_utbdefault_entry(config_data):
    """Replace the UTBDefault Kernel -> Add entry with UTBMap at the same index.

    Returns the index that now holds UTBMap, or None when neither kext is present
    and USBToolBox.kext is missing so there is no safe slot to use.
    """
    kernel = config_data.setdefault("Kernel", {})
    kernel_add = kernel.setdefault("Add", [])

    def utbmap_entry(existing=None):
        entry = dict(existing or {})
        entry["Arch"] = entry.get("Arch") or "Any"
        entry["BundlePath"] = "UTBMap.kext"
        entry["Comment"] = entry.get("Comment") or "USB port map"
        entry["Enabled"] = entry.get("Enabled", True)
        entry["ExecutablePath"] = ""
        entry["MaxKernel"] = entry.get("MaxKernel", "")
        entry["MinKernel"] = entry.get("MinKernel", "")
        entry["PlistPath"] = "Contents/Info.plist"
        return entry

    usbtoolbox_index = None
    utbmap_index = None
    for index, entry in enumerate(kernel_add):
        name = kext_base_name(entry.get("BundlePath"))
        if name == "utbdefault":
            kernel_add[index] = utbmap_entry(entry)
            return index
        if name == "utbmap":
            utbmap_index = index
        elif name == "usbtoolbox":
            usbtoolbox_index = index

    if utbmap_index is not None:
        kernel_add[utbmap_index] = utbmap_entry(kernel_add[utbmap_index])
        return utbmap_index

    if usbtoolbox_index is not None:
        kernel_add.insert(usbtoolbox_index + 1, utbmap_entry())
        return usbtoolbox_index + 1

    return None


class USBMapper:
    def __init__(self, utils):
        self.utils = utils
        self.root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        self.map_dir = os.path.join(self.root_dir, "USBMap")
        self.usbdump_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "resources", "usbdump.exe")
        self.history_path = os.path.join(self.map_dir, "usb.json")
        self.kext_path = os.path.join(self.map_dir, "UTBMap.kext")
        self.controllers = None
        self.controllers_historical = None
        self.settings = {
            "show_friendly_types": True,
            "auto_bind_companions": True,
            "add_comments_to_map": True,
        }
        self._load_history()

    def has_map(self):
        return os.path.isfile(os.path.join(self.kext_path, "Contents", "Info.plist"))

    def _load_history(self):
        if os.path.isfile(self.history_path):
            try:
                with open(self.history_path, "r") as handle:
                    self.controllers_historical = json.load(handle)
            except (OSError, ValueError):
                self.controllers_historical = None

    def _save_history(self):
        if not self.controllers_historical:
            return
        self.utils.create_folder(self.map_dir)
        with open(self.history_path, "w") as handle:
            json.dump(self.controllers_historical, handle, indent=4, sort_keys=True)

    def run(self, result_dir=None):
        if os.name != "nt":
            self.utils.head("Map USB Ports")
            print("")
            print("USB port discovery uses USBToolBox's Windows dump tool.")
            print("Run OpCore-Ready on Windows to map ports.")
            print("")
            self.utils.request_input()
            return False

        if not os.path.isfile(self.usbdump_path):
            self.utils.head("Map USB Ports")
            print("")
            print("usbdump.exe is missing:")
            print("  {}".format(self.usbdump_path))
            print("")
            self.utils.request_input()
            return False

        while True:
            self.utils.head("Map USB Ports")
            print("")
            print("Ports are read with USBToolBox (usbdump) on this PC.")
            print("The map is saved as UTBMap.kext and takes the place of UTBDefault.kext.")
            print("")
            print("Saved map: {}".format(self.kext_path if self.has_map() else "Not built yet"))
            if result_dir and os.path.isfile(os.path.join(result_dir, "EFI", "OC", "config.plist")):
                print("EFI:       {}".format(result_dir))
            else:
                print("EFI:       Build OpenCore EFI first, or map now and it will be applied on build")
            print("")
            print("1. Discover Ports")
            print("2. Select Ports and Build UTBMap.kext")
            print("3. Apply Saved Map to EFI")
            print("")
            print("B. Back")
            print("")
            option = self.utils.request_input("Select an option: ").strip().lower()
            if option in ("b", "q", ""):
                return self.has_map()
            if option == "1":
                self.discover_ports()
            elif option == "2":
                if self.select_ports():
                    self._apply_if_possible(result_dir)
            elif option == "3":
                self._apply_if_possible(result_dir, require_efi=True)

    def _apply_if_possible(self, result_dir, require_efi=False):
        if not self.has_map():
            self.utils.head("Apply USB Map")
            print("")
            print("Build a map first (option 2).")
            print("")
            self.utils.request_input()
            return False

        config_path = os.path.join(result_dir or "", "EFI", "OC", "config.plist")
        if not result_dir or not os.path.isfile(config_path):
            self.utils.head("USB Map Saved")
            print("")
            print("UTBMap.kext is saved at:")
            print("  {}".format(self.kext_path))
            print("")
            if require_efi:
                print("No OpenCore EFI was found. Build the EFI, then apply the map.")
            else:
                print("It will replace UTBDefault.kext in config.plist when the EFI is built.")
            print("")
            self.utils.request_input()
            return False

        try:
            index = self.apply_to_efi(result_dir)
        except Exception as error:
            self.utils.head("Apply USB Map")
            print("")
            print("Could not apply the USB map.")
            print(str(error))
            print("")
            self.utils.request_input()
            return False

        self.utils.head("USB Map Applied")
        print("")
        print("UTBDefault.kext was removed from EFI\\OC\\Kexts.")
        print("UTBMap.kext was installed in its place.")
        if index is None:
            print("config.plist had no UTBDefault or USBToolBox entry to update.")
        else:
            print("config.plist Kernel -> Add entry {} is now UTBMap.kext.".format(index + 1))
        print("USBToolBox.kext is unchanged and still has to load before the map.")
        print("")
        self.utils.request_input()
        return True

    def apply_to_efi(self, result_dir):
        if not self.has_map():
            raise Exception("UTBMap.kext has not been built.")

        kexts_directory = os.path.join(result_dir, "EFI", "OC", "Kexts")
        config_path = os.path.join(result_dir, "EFI", "OC", "config.plist")
        if not os.path.isdir(kexts_directory) or not os.path.isfile(config_path):
            raise Exception("OpenCore EFI is missing Kexts or config.plist.")

        config_data = self.utils.read_file(config_path)
        if not config_data:
            raise Exception("Could not read config.plist.")

        destination = os.path.join(kexts_directory, "UTBMap.kext")
        if os.path.isdir(destination):
            shutil.rmtree(destination)
        shutil.copytree(self.kext_path, destination)

        default_kext = os.path.join(kexts_directory, "UTBDefault.kext")
        if os.path.isdir(default_kext):
            shutil.rmtree(default_kext)

        index = replace_utbdefault_entry(config_data)
        self.utils.write_file(config_path, config_data)
        return index

    def discover_ports(self):
        self.utils.head("Port Discovery")
        print("")
        print("Plug in a device for each port you want to map, including USB 2 and USB 3.")
        print("The list refreshes every few seconds. Ports stay remembered after you unplug.")
        print("")
        print("Reading USB controllers...")
        try:
            self._refresh_controllers()
        except Exception as error:
            print("")
            print("Could not read USB controllers.")
            print(str(error))
            print("")
            self.utils.request_input()
            return

        while True:
            self.utils.head("Port Discovery")
            print("")
            self._print_controllers(self.controllers, colored=True)
            self._save_history()
            print("")
            print("Plug devices in, then wait for the next refresh.")
            print("B. Back")
            print("")
            answer = self._timed_input("Waiting 5 seconds: ", 5)
            if answer is not None and answer.strip().lower() == "b":
                break
            try:
                self._refresh_controllers()
            except Exception as error:
                print("Refresh failed: {}".format(error))
                self.utils.request_input()
                break

    def select_ports(self):
        if not self.controllers_historical:
            self.utils.head("Select Ports and Build Kext")
            print("")
            print("No ports yet. Use Discover Ports first.")
            print("")
            self.utils.request_input()
            return False

        while True:
            by_port = self._assign_selection_indexes()
            self._save_history()
            self.utils.head("Select Ports and Build UTBMap.kext")
            print("")
            self._print_selection(by_port)
            print("Companion binding is {}.".format("on" if self.settings["auto_bind_companions"] else "off"))
            print("")
            print("K. Build UTBMap.kext (requires USBToolBox.kext)")
            print("A. Select All")
            print("N. Select None")
            print("P. Enable All Populated Ports")
            print("D. Disable All Empty Ports")
            print("T. Show Connector Types")
            print("G. Toggle Companion Binding")
            print("")
            print("B. Back")
            print("")
            print("- Toggle ports with a comma-separated list (example: 1,2,3)")
            print("- Set types with T:1,2,3:t where t is the type number")
            print("- Set a comment with C:1:Left rear")
            print("")
            output = self.utils.request_input("Select an option: ").strip()
            if not output:
                continue
            command = output.upper()
            if command == "B":
                return False
            if command == "K":
                if self._validate_and_build():
                    return True
                continue
            if command in ("A", "N"):
                for port in by_port:
                    port["selected"] = command == "A"
                continue
            if command == "P":
                for port in by_port:
                    if self._port_is_populated(port):
                        port["selected"] = True
                continue
            if command == "D":
                for port in by_port:
                    if not self._port_is_populated(port):
                        port["selected"] = False
                continue
            if command == "T":
                self._print_types()
                continue
            if command == "G":
                self.settings["auto_bind_companions"] = not self.settings["auto_bind_companions"]
                continue
            if output[0].upper() == "T" and ":" in output:
                self._set_types(output, by_port)
                continue
            if output[0].upper() == "C" and ":" in output:
                self._set_comments(output, by_port)
                continue
            self._toggle_ports(output, by_port)

    def _validate_and_build(self):
        if not any(port.get("selected") for controller in self.controllers_historical for port in controller.get("ports", [])):
            self.utils.head("Selection Validation")
            print("")
            print("No ports are selected.")
            print("")
            self.utils.request_input()
            return False

        missing = []
        over_limit = []
        for controller in self.controllers_historical:
            selected = [port for port in controller.get("ports", []) if port.get("selected")]
            if len(selected) > 15:
                over_limit.append((controller.get("name") or "Controller", len(selected)))
            for port in selected:
                if port.get("type") is None and port.get("guessed") is None:
                    missing.append(port.get("selection_index"))

        if missing:
            self.utils.head("Selection Validation")
            print("")
            print("These ports need a connector type: {}".format(", ".join(str(item) for item in missing)))
            print("Set one with T:port:type, for example T:1:3")
            print("")
            self.utils.request_input()
            return False

        if over_limit:
            self.utils.head("Selection Validation")
            print("")
            print("macOS only uses 15 ports on a controller. These controllers have more selected:")
            for name, count in over_limit:
                print("- {} ({} ports)".format(name, count))
            print("")
            answer = self.utils.request_input("Build the map anyway? (yes/No): ").strip().lower()
            if answer != "yes":
                return False

        empty = [controller for controller in self.controllers_historical if not any(port.get("selected") for port in controller.get("ports", []))]
        ignore_empty = True
        if empty:
            self.utils.head("Selection Validation")
            print("")
            print("These controllers have no enabled ports:")
            for controller in empty:
                print("- {}".format(controller.get("name") or "Controller"))
            print("")
            print("I. Ignore them and leave them out of the map")
            print("D. Include them with every port disabled")
            print("")
            answer = self.utils.request_input("Select an option (default: I): ").strip().lower()
            ignore_empty = answer != "d"

        try:
            self.build_kext(ignore_empty=ignore_empty)
        except Exception as error:
            self.utils.head("Building UTBMap.kext")
            print("")
            print("Could not build UTBMap.kext.")
            print(str(error))
            print("")
            self.utils.request_input()
            return False

        self.utils.head("Building UTBMap.kext")
        print("")
        print("Saved UTBMap.kext to:")
        print("  {}".format(self.kext_path))
        print("")
        self.utils.request_input()
        return True

    def build_kext(self, ignore_empty=True, output_path=None):
        template = copy.deepcopy(INFO_PLIST_TEMPLATE)
        for controller in self.controllers_historical or []:
            selected_ports = [port for port in controller.get("ports", []) if port.get("selected")]
            if not selected_ports and ignore_empty:
                continue

            personality_name = self._personality_name(controller)
            personality = {
                "CFBundleIdentifier": "com.dhinakg.USBToolBox.kext",
                "IOClass": "USBToolBox",
                "IOProviderClass": "IOPCIDevice",
                "IOMatchCategory": "USBToolBox",
            }
            personality.update(self._matching_key(controller))
            personality["IOProviderMergeProperties"] = {"ports": {}, "port-count": port_data(0)}

            port_name_index = {}
            highest_index = 0
            for port in selected_ports:
                port_index = int(port["index"])
                if port_index > highest_index:
                    highest_index = port_index

                if controller.get("class") == USB_XHCI and port.get("class") == USB_SUPER:
                    prefix = "SS"
                elif controller.get("class") == USB_XHCI and port.get("class") == USB_HIGH:
                    prefix = "HS"
                else:
                    prefix = "PRT"

                name_index = port_name_index.get(prefix, 1)
                port_name = prefix + str(name_index).zfill(4 - len(prefix))
                port_name_index[prefix] = name_index + 1

                connector = port.get("type")
                if connector is None:
                    connector = port.get("guessed")
                entry = {
                    "port": port_data(port_index),
                    "UsbConnector": int(connector),
                }
                if self.settings["add_comments_to_map"] and port.get("comment"):
                    entry["#comment"] = port["comment"]
                personality["IOProviderMergeProperties"]["ports"][port_name] = entry

            personality["IOProviderMergeProperties"]["port-count"] = port_data(highest_index)
            template["IOKitPersonalities"][personality_name] = personality

        if not template["IOKitPersonalities"]:
            raise Exception("The map has no controllers.")

        template["OSBundleLibraries"] = {"com.dhinakg.USBToolBox.kext": "1.0.0"}
        destination = output_path or self.kext_path
        if os.path.isdir(destination):
            shutil.rmtree(destination)
        contents_dir = os.path.join(destination, "Contents")
        os.makedirs(contents_dir)
        with open(os.path.join(contents_dir, "Info.plist"), "wb") as handle:
            plistlib.dump(template, handle, sort_keys=True)
        return destination

    def _refresh_controllers(self):
        controllers = self._read_controllers()
        self._enrich_controllers(controllers)
        self.controllers = controllers
        if not self.controllers_historical:
            self.controllers_historical = copy.deepcopy(controllers)
        else:
            self._merge_controllers(self.controllers_historical, controllers)

    def _read_controllers(self):
        command = [self.usbdump_path]
        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "nt":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        completed = subprocess.run(command, **kwargs)
        raw = completed.stdout or b""
        if completed.returncode not in (0, None) and not raw.strip():
            detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
            raise Exception(detail or "usbdump.exe exited with code {}.".format(completed.returncode))
        try:
            info = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            detail = raw.decode("utf-8", "replace")[:500]
            raise Exception("usbdump.exe did not return USB controller JSON. {}".format(detail))

        hub_map = {}
        controllers = []
        for controller in info:
            if not controller.get("RootHub"):
                continue
            properties = controller.get("UsbDeviceProperties") or {}
            controller_info = {
                "name": properties.get("DeviceDesc") or "USB Controller",
                "identifiers": {
                    "instance_id": properties.get("DeviceId"),
                },
                "class": USB_CONTROLLER_UNKNOWN,
            }
            controller_info.update(self._serialize_hub(controller["RootHub"], hub_map))

            vendor = controller.get("VendorID")
            device = controller.get("DeviceID")
            if vendor not in (None, 0, 0xFFFF) and device not in (None, 0, 0xFFFF):
                controller_info["identifiers"]["pci_id"] = [self._pci_hex(vendor), self._pci_hex(device)]
                subsystem = controller.get("SubSysID")
                if subsystem not in (None, 0, 0xFFFFFFFF):
                    subsystem_hex = self._pci_hex(subsystem, width=8)
                    controller_info["identifiers"]["pci_id"].extend((subsystem_hex[:4], subsystem_hex[4:]))

            revision = (controller.get("ControllerInfo") or {}).get("PciRevision", 0)
            if revision not in (0, 0xFF, None):
                controller_info["identifiers"]["pci_revision"] = int(revision)

            if controller.get("BusDeviceFunctionValid"):
                controller_info["identifiers"]["bdf"] = [
                    controller.get("BusNumber"),
                    controller.get("BusDevice"),
                    controller.get("BusFunction"),
                ]

            controllers.append(controller_info)

        self._guess_ports(hub_map)
        for controller in controllers:
            if any(port.get("class") == USB_SUPER for port in controller.get("ports", [])):
                controller["class"] = USB_XHCI
        return controllers

    def _serialize_hub(self, hub, hub_map):
        descriptor = (((hub.get("HubInfo") or {}).get("HubInformation") or {}).get("HubDescriptor") or {})
        hub_info = {
            "hub_name": hub.get("HubName"),
            "port_count": descriptor.get("bNumberOfPorts") or 0,
            "ports": [],
        }
        for index, port in enumerate(hub.get("HubPorts") or []):
            if not port:
                continue
            connection = port.get("ConnectionInfo") or {}
            status = self._connection_status(connection.get("ConnectionStatus"))
            port_info = {
                "index": self._connection_index(port, index),
                "comment": None,
                "class": USB_SPEED_UNKNOWN,
                "status": status,
                "type": None,
                "guessed": None,
                "devices": [],
                "companion_info": {"port": "", "hub": "", "multiple_companions": False},
                "type_c": False,
                "user_connectable": True,
            }
            port_info["name"] = "Port {}".format(port_info["index"])
            if not self._is_device_connected(status):
                if status not in ("NoDeviceConnected", "", None):
                    port_info["devices"] = [{"error": status or "Device connected to port errored."}]
                hub_info["ports"].append(port_info)
                continue

            port_info["class"] = self._port_speed(port)
            connector = port.get("PortConnectorProps") or {}
            properties = connector.get("UsbPortProperties") or {}
            port_info["companion_info"] = {
                "port": connector.get("CompanionPortNumber") or "",
                "hub": connector.get("CompanionHubSymbolicLinkName") or "",
                "multiple_companions": bool(properties.get("PortHasMultipleCompanions", False)),
            }
            port_info["type_c"] = bool(properties.get("PortConnectorIsTypeC", False))
            port_info["user_connectable"] = bool(properties.get("PortIsUserConnectable", True))

            if self._is_device_connected(status):
                device_info = {
                    "name": self._device_name(port),
                    "instance_id": (port.get("UsbDeviceProperties") or {}).get("DeviceId"),
                    "devices": [],
                }
                if port.get("DeviceInfoType") == "ExternalHubInfo":
                    external_hub = self._serialize_hub(port, hub_map)
                    device_info["speed"] = self._device_speed(port)
                    device_info["devices"] = [
                        item
                        for item in itertools.chain.from_iterable(hub_port.get("devices") or [] for hub_port in external_hub.get("ports", []))
                        if item
                    ]
                else:
                    device_info["speed"] = self._device_speed(port)
                port_info["devices"].append(device_info)

            hub_info["ports"].append(port_info)

        hub_info["ports"].sort(key=lambda item: item["index"])
        if hub_info.get("hub_name"):
            hub_map[hub_info["hub_name"]] = hub_info
        return hub_info

    def _guess_ports(self, hub_map):
        def companion(port):
            info = port.get("companion_info") or {}
            hub = hub_map.get(info.get("hub") or "", {})
            matches = [item for item in hub.get("ports", []) if item.get("index") == info.get("port")]
            return matches[0] if matches else None

        for hub in hub_map.values():
            for port in hub.get("ports", []):
                if not self._is_device_connected(port.get("status")):
                    port["guessed"] = None
                    continue
                other = companion(port)
                if port.get("type_c") or (other and other.get("type_c")):
                    port["guessed"] = 9
                elif not port.get("user_connectable", True):
                    port["guessed"] = 255
                elif other and (
                    (port.get("class") == USB_SUPER and other.get("class") == USB_HIGH)
                    or (port.get("class") == USB_HIGH and other.get("class") == USB_SUPER)
                ):
                    port["guessed"] = 3
                elif port.get("class") == USB_SUPER and not (port.get("companion_info") or {}).get("port"):
                    port["guessed"] = 255
                else:
                    port["guessed"] = 0

    def _enrich_controllers(self, controllers):
        instance_ids = [controller.get("identifiers", {}).get("instance_id") for controller in controllers]
        instance_ids = [item for item in instance_ids if item]
        details = self._query_pnp(instance_ids)
        for controller in controllers:
            info = details.get(controller.get("identifiers", {}).get("instance_id")) or {}
            if info.get("friendly"):
                controller["name"] = info["friendly"]
            if info.get("acpi_path"):
                controller["identifiers"]["acpi_path"] = info["acpi_path"]
            controller_class = info.get("interface")
            if controller_class in CONTROLLER_NAMES and controller_class != USB_CONTROLLER_UNKNOWN:
                controller["class"] = controller_class
            elif info.get("service") in SERVICE_TO_CLASS:
                controller["class"] = SERVICE_TO_CLASS[info["service"]]

    def _query_pnp(self, instance_ids):
        if os.name != "nt" or not instance_ids:
            return {}
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
        try:
            json.dump(instance_ids, handle)
            handle.close()
            script = r"""
$ids = Get-Content -Raw -Path $env:OCS_USB_IDS | ConvertFrom-Json
$out = @()
foreach ($id in $ids) {
  $item = [ordered]@{ instance_id = [string]$id; friendly = $null; service = $null; interface = $null; acpi_path = $null }
  $map = @{
    friendly = "DEVPKEY_Device_FriendlyName"
    service = "DEVPKEY_Device_Service"
    interface = "DEVPKEY_PciDevice_ProgIf"
    acpi_path = "DEVPKEY_Device_BiosDeviceName"
  }
  foreach ($name in $map.Keys) {
    try {
      $prop = Get-PnpDeviceProperty -InstanceId $id -KeyName $map[$name] -ErrorAction Stop
      $item[$name] = $prop.Data
    } catch {}
  }
  $out += [pscustomobject]$item
}
$out | ConvertTo-Json -Depth 5 -Compress
"""
            environment = os.environ.copy()
            environment["OCS_USB_IDS"] = handle.name
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                creationflags=CREATE_NO_WINDOW,
                timeout=90,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        finally:
            try:
                os.remove(handle.name)
            except OSError:
                pass

        text = (completed.stdout or b"").decode("utf-8-sig", "replace").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except ValueError:
            return {}
        if isinstance(payload, dict):
            payload = [payload]
        details = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            interface = item.get("interface")
            if isinstance(interface, list):
                interface = interface[0] if interface else None
            try:
                interface = int(interface) if interface is not None and interface != "" else None
            except (TypeError, ValueError):
                interface = None
            service = item.get("service")
            if isinstance(service, list):
                service = service[0] if service else None
            if isinstance(service, str):
                service = service.lower()
            acpi_path = item.get("acpi_path")
            if isinstance(acpi_path, list):
                acpi_path = acpi_path[0] if acpi_path else None
            friendly = item.get("friendly")
            if isinstance(friendly, list):
                friendly = friendly[0] if friendly else None
            details[item.get("instance_id")] = {
                "friendly": friendly,
                "service": service,
                "interface": interface,
                "acpi_path": acpi_path,
            }
        return details

    def _matching_key(self, controller):
        identifiers = controller.get("identifiers") or {}
        acpi_path = identifiers.get("acpi_path")
        if acpi_path and self._acpi_name_is_unique(controller):
            return {"IONameMatch": acpi_path.replace("/", "\\").rpartition(".")[2]}
        if identifiers.get("bdf"):
            return {"IOPropertyMatch": {"pcidebug": ":".join(str(part) for part in identifiers["bdf"])}}
        pci_id = identifiers.get("pci_id") or []
        if len(pci_id) >= 2 and self._pci_id_is_unique(controller):
            match = {"IOPCIPrimaryMatch": "0x{}{}".format(str(pci_id[1]).zfill(4), str(pci_id[0]).zfill(4))}
            if len(pci_id) > 3:
                match["IOPCISecondaryMatch"] = "0x{}{}".format(str(pci_id[3]).zfill(4), str(pci_id[2]).zfill(4))
            return match
        if len(pci_id) >= 2:
            return {"IOPCIPrimaryMatch": "0x{}{}".format(str(pci_id[1]).zfill(4), str(pci_id[0]).zfill(4))}
        raise Exception("No matching key available for {}.".format(controller.get("name") or "a USB controller"))

    def _personality_name(self, controller):
        identifiers = controller.get("identifiers") or {}
        acpi_path = identifiers.get("acpi_path")
        if acpi_path:
            if self._acpi_name_is_unique(controller):
                return acpi_path.replace("/", "\\").rpartition(".")[2] or "USB"
            return acpi_path.replace("/", "\\").lstrip("\\")
        if identifiers.get("bdf"):
            return ":".join(str(part) for part in identifiers["bdf"])
        return controller.get("name") or "USB"

    def _acpi_name_is_unique(self, controller):
        acpi_path = (controller.get("identifiers") or {}).get("acpi_path")
        if not acpi_path:
            return False
        name = acpi_path.rpartition(".")[2]
        matches = [
            item for item in self.controllers_historical or []
            if ((item.get("identifiers") or {}).get("acpi_path") or "").rpartition(".")[2] == name
        ]
        return len(matches) == 1

    def _pci_id_is_unique(self, controller):
        pci_id = (controller.get("identifiers") or {}).get("pci_id")
        if not pci_id:
            return False
        matches = [
            item for item in self.controllers_historical or []
            if (item.get("identifiers") or {}).get("pci_id") == pci_id
        ]
        return len(matches) == 1

    def _assign_selection_indexes(self):
        by_port = []
        selection_index = 1
        for controller in self.controllers_historical:
            for port in controller.get("ports", []):
                if "selected" not in port:
                    populated = bool(self._connected_devices(port))
                    companion = self._companion_port(port)
                    if companion and self._connected_devices(companion):
                        populated = True
                    port["selected"] = populated
                port["selection_index"] = selection_index
                selection_index += 1
                by_port.append(port)
        return by_port

    def _print_selection(self, by_port):
        width = len(str(len(by_port)))
        for controller in self.controllers_historical:
            selected_count = sum(1 for port in controller.get("ports", []) if port.get("selected"))
            count_text = "{}/{}".format(selected_count, len(controller.get("ports", [])))
            color = "91" if selected_count > 15 else "92"
            print("{} | {} | \033[{}m{}\033[0m ports".format(
                controller.get("name") or "USB Controller",
                CONTROLLER_NAMES.get(controller.get("class"), "Unknown"),
                color,
                count_text,
            ))
            for port in controller.get("ports", []):
                marker = "#" if port.get("selected") else " "
                line = "[{}]  {}.{}{}".format(marker, port["selection_index"], " " * (width - len(str(port["selection_index"])) + 1), self._port_to_str(port))
                companion = self._companion_port(port)
                if companion and companion.get("selection_index"):
                    line += " | Companion to {}".format(companion["selection_index"])
                if port.get("selected"):
                    print("\033[1;32m{}\033[0m".format(line))
                else:
                    print(line)
                if port.get("comment"):
                    print(" " * (6 + width) + "\033[1;34m{}\033[0m".format(port["comment"]))
                for device in port.get("devices") or []:
                    self._print_device(device, indentation="      ")
            print("")

    def _print_controllers(self, controllers, colored=False):
        if not controllers:
            print("No USB controllers found.")
            return
        for controller in controllers:
            print("{} | {} | {} ports".format(
                controller.get("name") or "USB Controller",
                CONTROLLER_NAMES.get(controller.get("class"), "Unknown"),
                len(controller.get("ports", [])),
            ))
            for port in controller.get("ports", []):
                line = "  " + self._port_to_str(port)
                if colored and self._connected_devices(port):
                    print("\033[1;32m{}\033[0m".format(line))
                else:
                    print(line)
                for device in self._connected_devices(port):
                    self._print_device(device)

    def _print_device(self, device, indentation="    "):
        if not isinstance(device, dict):
            print("{}- {}".format(indentation, device))
            return
        if device.get("error"):
            message = device["error"] if isinstance(device["error"], str) else "Device connected to port errored."
            print("{}- {}".format(indentation, message))
            return
        speed = SPEED_NAMES.get(device.get("speed"), "")
        suffix = " - operating at {}".format(speed) if speed else ""
        print("{}- {}{}".format(indentation, (device.get("name") or "Unknown Device").strip(), suffix))
        for child in device.get("devices") or []:
            self._print_device(child, indentation + "  ")

    def _print_types(self):
        self.utils.head("USB Connector Types")
        print("")
        for number in sorted(PORT_TYPE_NAMES):
            print("{}: {}".format(number, PORT_TYPE_NAMES[number]))
        print("")
        print("Type 9 has a switch: flipping a USB-C plug keeps the device on the same ports.")
        print("Type 10 has no switch: flipping the plug moves the device to the companion ports.")
        print("Pictures: https://github.com/USBToolBox/tool/blob/master/TYPES.md")
        print("")
        self.utils.request_input()

    def _port_to_str(self, port):
        if port.get("type") is not None:
            port_type = self._type_label(port.get("type"))
        elif port.get("guessed") is not None:
            port_type = self._type_label(port.get("guessed")) + " (guessed)"
        else:
            port_type = "Unknown"
        return "{} | {} | {}".format(
            port.get("name") or "Port {}".format(port.get("index")),
            SPEED_NAMES.get(port.get("class"), "Unknown"),
            port_type,
        )

    def _type_label(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return str(value)
        if self.settings["show_friendly_types"]:
            return PORT_TYPE_NAMES.get(value, str(value))
        return str(value)

    def _connected_devices(self, port):
        return [device for device in (port.get("devices") or []) if isinstance(device, dict) and not device.get("error")]

    def _port_is_populated(self, port):
        if self._connected_devices(port):
            return True
        companion = self._companion_port(port)
        return bool(companion and self._connected_devices(companion))

    def _companion_port(self, port):
        info = port.get("companion_info") or {}
        if not info.get("hub") or not info.get("port"):
            return None
        hubs = [controller for controller in self.controllers_historical or [] if controller.get("hub_name") == info.get("hub")]
        if not hubs:
            return None
        matches = [item for item in hubs[0].get("ports", []) if item.get("index") == info.get("port")]
        return matches[0] if matches else None

    def _toggle_ports(self, output, by_port):
        self._edit_ports(output, by_port, action="toggle")

    def _set_types(self, output, by_port):
        parts = output.split(":")
        if len(parts) != 3:
            return
        try:
            port_type = int(parts[2])
        except ValueError:
            return
        if port_type not in PORT_TYPE_NAMES:
            return
        self._edit_ports(parts[1], by_port, action="type", port_type=port_type)

    def _set_comments(self, output, by_port):
        parts = output.split(":", 2)
        if len(parts) < 2:
            return
        comment = parts[2].strip() if len(parts) == 3 else ""
        if comment.lower() == "none":
            comment = ""
        self._edit_ports(parts[1], by_port, action="comment", comment=comment)

    def _edit_ports(self, number_text, by_port, action, port_type=None, comment=None):
        numbers = []
        for piece in number_text.replace(" ", "").split(","):
            if piece and piece not in numbers:
                numbers.append(piece)
        skip = set()
        for piece in numbers:
            if piece in skip:
                continue
            try:
                index = int(piece) - 1
            except ValueError:
                continue
            if index not in range(len(by_port)):
                continue
            port = by_port[index]
            companion = self._companion_port(port) if self.settings["auto_bind_companions"] and action in ("toggle", "type") else None
            if action == "toggle":
                port["selected"] = not port.get("selected")
                if companion is not None:
                    companion["selected"] = port["selected"]
            elif action == "type":
                port["type"] = port_type
                if companion is not None:
                    companion["type"] = port_type
            elif action == "comment":
                port["comment"] = comment or None
            if companion is not None and companion.get("selection_index"):
                skip.add(str(companion["selection_index"]))

    def _timed_input(self, prompt, timeout):
        print(prompt, end="", flush=True)
        if os.name != "nt":
            return self.utils.request_input("")
        try:
            import msvcrt
        except ImportError:
            return self.utils.request_input("")

        typed = []
        started = time.time()
        while time.time() - started < timeout:
            if msvcrt.kbhit():
                character = msvcrt.getwch()
                if character in ("\r", "\n"):
                    print("")
                    return "".join(typed)
                if character == "\x03":
                    raise KeyboardInterrupt
                if character == "\b":
                    if typed:
                        typed.pop()
                        print("\b \b", end="", flush=True)
                    continue
                typed.append(character)
                print(character, end="", flush=True)
            else:
                time.sleep(0.05)
        print("")
        return "".join(typed)

    @staticmethod
    def _is_device_connected(status):
        status = "" if status is None else str(status)
        return status == "DeviceConnected" or (status.endswith("DeviceConnected") and not status.endswith("NoDeviceConnected"))

    @staticmethod
    def _connection_status(status):
        if isinstance(status, int):
            return CONNECTION_STATUS_NAMES.get(status, str(status))
        return "" if status is None else str(status)

    @staticmethod
    def _connection_index(port, fallback):
        for key in ("PortConnectorProps", "ConnectionInfo", "ConnectionInfoV2"):
            value = (port.get(key) or {}).get("ConnectionIndex")
            if value:
                return value
        return fallback + 1

    @staticmethod
    def _port_speed(port):
        protocols = (port.get("ConnectionInfoV2") or {}).get("SupportedUsbProtocols") or {}
        if protocols.get("Usb300"):
            return USB_SUPER
        if protocols.get("Usb200") and protocols.get("Usb110"):
            return USB_HIGH
        if protocols.get("Usb110"):
            return USB_FULL
        return USB_SPEED_UNKNOWN

    @staticmethod
    def _device_speed(port):
        connection = port.get("ConnectionInfo") or {}
        speed = connection.get("Speed")
        flags = (port.get("ConnectionInfoV2") or {}).get("Flags") or {}
        if speed == USB_SUPER and flags.get("DeviceIsOperatingAtSuperSpeedPlusOrHigher"):
            return USB_SUPER_PLUS
        if speed in SPEED_NAMES and speed != USB_SPEED_UNKNOWN:
            return speed
        return USB_SPEED_UNKNOWN

    @staticmethod
    def _device_name(port):
        properties = port.get("UsbDeviceProperties") or {}
        node = port.get("DeviceInfoNode") or {}
        descriptor = (port.get("ConnectionInfo") or {}).get("DeviceDescriptor") or {}
        product_index = descriptor.get("iProduct")
        if product_index:
            for string_desc in port.get("StringDescs") or []:
                if string_desc.get("DescriptorIndex") == product_index:
                    strings = string_desc.get("StringDescriptor") or []
                    if strings and strings[0].get("bString"):
                        return strings[0]["bString"]
        return properties.get("DeviceDesc") or node.get("DeviceDescName") or "Unknown Device"

    @staticmethod
    def _pci_hex(value, width=4):
        return format(int(value) & ((1 << (width * 4)) - 1), "0{}X".format(width))

    @staticmethod
    def _same_controller(left, right):
        left_ids = left.get("identifiers") or {}
        right_ids = right.get("identifiers") or {}
        shared = [key for key in left_ids if left_ids.get(key) and key in right_ids and right_ids.get(key)]
        if not shared:
            return False
        for key in shared:
            if key in ("instance_id", "location_id"):
                continue
            if len(shared) == 1 and key == "pci_revision":
                return False
            if left_ids.get(key) != right_ids.get(key):
                return False
        compared = [key for key in shared if key not in ("instance_id", "location_id")]
        return bool(compared)

    def _merge_controllers(self, base, new):
        for controller in new:
            current = next((item for item in base if self._same_controller(controller, item)), None)
            if current is None:
                base.append(copy.deepcopy(controller))
                continue
            for key, value in controller.items():
                if key == "ports" or value in (None, "", [], {}):
                    continue
                if key == "identifiers":
                    current.setdefault("identifiers", {}).update({item: data for item, data in value.items() if data})
                else:
                    current[key] = value
            self._merge_ports(current, controller)

    @staticmethod
    def _merge_ports(base_controller, new_controller):
        for port in new_controller.get("ports", []):
            current = next((item for item in base_controller.get("ports", []) if item.get("index") == port.get("index")), None)
            if current is None:
                base_controller.setdefault("ports", []).append(copy.deepcopy(port))
                continue
            for key, value in port.items():
                if key == "devices":
                    continue
                if value is None and key in ("type", "comment", "guessed"):
                    continue
                current[key] = value
            USBMapper._merge_devices(current, port)
        base_controller["ports"].sort(key=lambda item: item.get("index") or 0)

    @staticmethod
    def _merge_devices(base_port, new_port):
        base_devices = [device for device in (base_port.get("devices") or []) if isinstance(device, dict) and not device.get("error")]
        for device in new_port.get("devices") or []:
            if not isinstance(device, dict) or device.get("error"):
                continue
            existing = next((item for item in base_devices if item.get("name") == device.get("name")), None)
            if existing is None:
                base_devices.append(copy.deepcopy(device))
                continue
            for child in device.get("devices") or []:
                if child not in (existing.get("devices") or []):
                    existing.setdefault("devices", []).append(copy.deepcopy(child))
        base_port["devices"] = base_devices

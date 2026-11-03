"""Download the macOS Recovery image for the version already chosen in OpCore-Ready.

Apple's recovery service picks the image from a Mac board identifier. The
board list shipped with OpenCore's macrecovery.py records which macOS release
each board receives. This module selects a board for the chosen release and
runs that script.
"""

import json
import os
import subprocess
import sys

from Scripts.datasets import os_data


def darwin_to_macos_major(darwin_major):
    """Return (major, minor) for a Darwin major version.

    17 is macOS 10.13, 20 is macOS 11, and 25 is macOS 26.
    """
    darwin_major = int(darwin_major)
    if darwin_major <= 19:
        return (10, darwin_major - 4)
    if darwin_major <= 24:
        return (darwin_major - 9, 0)
    return (darwin_major + 1, 0)


def macos_version_key(version):
    parts = [int(part) for part in str(version).split(".") if part.isdigit()]
    if not parts:
        return None
    if parts[0] == 10:
        return (10, parts[1] if len(parts) > 1 else 0)
    return (parts[0], 0)


def version_sort_key(version):
    return [int(part) for part in str(version).split(".") if part.isdigit()]


class RecoveryDownloader:
    def __init__(self, utils):
        self.utils = utils
        self.root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    def macrecovery_path(self):
        return os.path.join(self.root_dir, "Scripts", "macrecovery", "macrecovery.py")

    def board_for_darwin(self, darwin_version):
        script = self.macrecovery_path()
        database_path = os.path.join(os.path.dirname(script), "boards.json")
        if not os.path.isfile(database_path):
            raise Exception("boards.json was not found next to macrecovery.py.")

        with open(database_path, "r", encoding="utf-8") as handle:
            boards = json.load(handle)

        wanted = darwin_to_macos_major(str(darwin_version).split(".")[0])
        matches = []
        for board_id, version in boards.items():
            if macos_version_key(version) == wanted:
                matches.append((version_sort_key(version), version, board_id))
        if not matches:
            return None

        matches.sort()
        version, board_id = matches[-1][1], matches[-1][2]
        return board_id, version

    def output_directory(self, darwin_version):
        name = os_data.get_macos_name_by_darwin(darwin_version) or "macOS {}".format(darwin_version)
        safe_name = "".join(character if character.isalnum() or character in (" ", "-", "_", ".") else "_" for character in name).strip()
        return os.path.join(self.root_dir, "Recovery", safe_name, "com.apple.recovery.boot")

    def download(self, darwin_version):
        self.utils.head("Download macOS Recovery")
        print("")
        name = os_data.get_macos_name_by_darwin(darwin_version) or darwin_version
        script = self.macrecovery_path()
        if not os.path.isfile(script):
            print("macrecovery.py was not found:")
            print("  {}".format(script))
            print("")
            self.utils.request_input()
            return False

        try:
            match = self.board_for_darwin(darwin_version)
        except Exception as error:
            print(str(error))
            print("")
            self.utils.request_input()
            return False

        if not match:
            print("macrecovery has no board identifier for {}.".format(name))
            print("Apple's recovery catalog in this OpenCore release does not offer that version.")
            print("")
            self.utils.request_input()
            return False

        board_id, served_version = match
        outdir = self.output_directory(darwin_version)
        print("Selected version: {}".format(name))
        print("Recovery image:   macOS {}".format(served_version))
        print("Board identifier: {}".format(board_id))
        print("Script:           {}".format(script))
        print("Save to:          {}".format(outdir))
        print("")
        print("This downloads Apple's Recovery image for that macOS release.")
        print("It is the image used to start the installer. It is not a full offline installer.")
        print("")

        existing = os.path.isfile(os.path.join(outdir, "BaseSystem.dmg")) and os.path.isfile(os.path.join(outdir, "BaseSystem.chunklist"))
        if existing:
            answer = self.utils.request_input("A Recovery image is already there. Download it again? (yes/No): ").strip().lower()
            if answer != "yes":
                self.utils.open_folder(outdir)
                return True

        self.utils.create_folder(outdir)
        print("")
        print("Running macrecovery.py. This can take a while.")
        print("")
        completed = subprocess.run(
            [sys.executable, script, "download", "-b", board_id, "-os", "latest", "-o", outdir],
            cwd=os.path.dirname(script),
        )
        print("")
        if completed.returncode != 0:
            print("macrecovery.py did not finish the download.")
            print("")
            self.utils.request_input()
            return False

        print("Recovery image saved to:")
        print("  {}".format(outdir))
        print("")
        print("Copy the com.apple.recovery.boot folder to the USB installer when you build the install media.")
        print("")
        self.utils.request_input()
        self.utils.open_folder(outdir)
        return True

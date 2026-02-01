# 🚀 OPCore-Ready

[![License](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Version](https://img.shields.io/badge/Version-v0.1--beta-orange.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)]()

**OPCore-Ready** is an all-in-one automation tool designed to streamline the OpenCore EFI creation process. It bridges the gap between creating a bootable USB, building an EFI, and the tedious process of USB mapping.

> [!IMPORTANT]
> OPCore-Ready includes the built-in **USB2EFI** script (developed by @theccraft-git), which automatically patches your `config.plist` and injects your `UTBMap.kext` after mapping. No more manual Plist editing!

---

## 📸 Screenshots

| Startup Screen 
| :--- | :--- |
| <img width="1470" height="692" alt="image" src="https://github.com/user-attachments/assets/74fd7f29-0da3-49b9-8b16-e764d65a3181" />
 <img width="1222" height="690" alt="image" src="https://github.com/user-attachments/assets/e8aa3375-2dc7-483f-a21f-eb0cf34638c0" />



---

## ✨ Features

* **One-Click Downloads:** Automatically fetches the latest Rufus, OpCore-Simplify, USBToolBox, and OCAT.
* **Guided Workflow:** Step-by-step instructions for Rufus formatting and OpenCore building.
* **Integrated USB2EFI:** * Replaces `UTBDefault` with your custom `UTBMap`.
    * Fixes kernel architecture strings.
    * Automates the file move process.
* **macOS Recovery Downloader:** Directly downloads recovery images for macOS Big Sur through **macOS Tahoe (26)**.
* **Auto-Cleanup:** Option to wipe the temporary workspace after your EFI is ready.

---

## 🛠️ How to Use

1.  **Download:** Clone this repo or download the `OPCore-Ready.bat`.
2.  **Run:** `OPCore-Ready.bat`.
3.  **Follow the Steps:**
    * **Part 1:** Format your USB with Rufus (Settings: Non-bootable, GPT, FAT32).
    * **Part 2:** Build your base EFI using OpCore-Simplify.
    * **Part 3:** Map your USB ports with USBToolBox.
    * **Part 4:** Let **USB2EFI** automatically merge everything.
    * **Part 5:** Choose your macOS version to download the recovery files.
4.  **Deploy:** Copy the final output folder content to your USB drive.

---

## 📦 Tools Included

| Tool | Purpose | License |
| :--- | :--- | :--- |
| **OpCore-Simplify** | EFI Base Generation | BSD-3 |
| **OpenCorePkg** | Bootloader Core | BSD-3 |
| **USBToolBox** | Port Mapping | MIT |
| **Rufus** | USB Formatting | GPLv3 |
| **OCAuxiliaryTools** | EFI Fine-tuning | MIT |

---

## ⚖️ License & Credits

* **Developer:** [@theccraft-git](https://github.com/theccraft-git)
* **USB2EFI Logic:** [@theccraft-git](https://github.com/theccraft-git)
* **License:** This project is licensed under the [BSD 3-Clause License](LICENSE).

### Disclaimer
*This tool is provided "as is". Hackintoshing involves modifying system files; I am not responsible for any damage to your hardware or loss of data. Use responsibly.*

---

## 🤝 Contributing

Found a bug? Have a suggestion for this project? 
1. Fork the project.
2. Create your Feature Branch.
3. Open a Pull Request!

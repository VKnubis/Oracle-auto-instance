# Oracle Auto Instance

Windows-friendly Oracle Cloud Infrastructure automation for launching compute instances and retrying when capacity is unavailable.

It is designed for OCI users who want to create instances from their own PC using Oracle's official Python SDK. It does not use Cloud Shell or browser automation.

## Start Here

If you want the GUI version, double-click:

```text
run_gui_windows.bat
```

If you want the command-line version, double-click:

```text
run_once_windows.bat
```

## What It Does

- Launches OCI compute instances from your PC.
- Auto-picks the newest compatible image when `OCI_IMAGE_ID` is blank.
- Injects your SSH public key into new instances.
- Treats `Out of host capacity` as a normal retry case.
- Waits for a launched instance to become `RUNNING`.
- Terminates an instance if OCI reports it failed before reaching `RUNNING`.
- Can run in the background with Windows Task Scheduler.

## Quick Start On Windows

1. Install Python 3.
2. Copy `config/config.example.env` to `.env`.
3. Fill `.env` with your OCI values.
4. Create an OCI API key and config file at:

```text
C:\Users\<you>\.oci\config
```

5. Check your OCI API login:

```text
check_oci_config.bat
```

6. Test one launch:

```text
run_once_windows.bat
```

7. Start automatic retries:

```text
start_auto_windows.bat
```

8. Stop automatic retries:

```text
stop_auto_windows.bat
```

Your PC must stay awake for the scheduled task to keep running.

## How It Works

The launcher reads values from `.env`, loads your OCI SDK config from `OCI_CONFIG_FILE`, and submits a compute launch request with your chosen compartment, subnet, shape, and image settings.

If `OCI_IMAGE_ID` is blank, the script asks OCI for the newest image that matches `OCI_IMAGE_OS`, `OCI_IMAGE_OS_VERSION`, and `OCI_SHAPE`.

This means you can use it with different operating systems and shapes by changing environment variables rather than changing code.

Examples:
- Ubuntu on Arm: `OCI_IMAGE_OS=Canonical Ubuntu`, `OCI_IMAGE_OS_VERSION=24.04`, `OCI_SHAPE=VM.Standard.A1.Flex`
- Oracle Linux on Intel: `OCI_IMAGE_OS=Oracle Linux`, `OCI_IMAGE_OS_VERSION=8`, `OCI_SHAPE=VM.Standard.E2.1.Micro`
- Custom image: set `OCI_IMAGE_ID` to a specific image OCID and leave the OS filters alone

## Required `.env` Values

```text
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..your_value
OCI_SUBNET_ID=ocid1.subnet.oc1..your_value
OCI_IMAGE_ID=
OCI_IMAGE_OS=Canonical Ubuntu
OCI_IMAGE_OS_VERSION=24.04
OCI_AVAILABILITY_DOMAIN=your_ad

OCI_SHAPE=VM.Standard.A1.Flex
OCI_OCPUS=1
OCI_MEMORY_GB=6

OCI_CONFIG_FILE=C:\Users\<you>\.oci\config
OCI_PROFILE=DEFAULT

INSTANCE_NAME_PREFIX=auto-instance
ASSIGN_PUBLIC_IP=true
SSH_PUBLIC_KEY=ssh-ed25519 or ssh-rsa public key here

DELETE_FAILED_INSTANCE=true
INSTANCE_WAIT_SECONDS=900
CAPACITY_RETRY_SUCCESS_EXIT=true
```

Leave `OCI_IMAGE_ID` blank unless you want to force a specific image OCID.

Use `OCI_IMAGE_OS`, `OCI_IMAGE_OS_VERSION`, and `OCI_SHAPE` together to match the image family you want. If you already know the exact image OCID, set `OCI_IMAGE_ID` and the OS filters are no longer needed.

Good starting points:
- `Canonical Ubuntu` + `24.04`
- `Oracle Linux` + `8`
- `Oracle Linux` + `9`
- `VM.Standard.A1.Flex` for Arm shapes
- `VM.Standard.E2.1.Micro` for a small Intel test shape

## Where To Find IDs

Use these as a checklist when filling in `.env` or `settings.env`.

| Value | Where to find it |
| --- | --- |
| `OCI_COMPARTMENT_ID` | OCI Console, open the compartment you want to launch into, then copy the compartment OCID from the compartment details page. |
| `OCI_SUBNET_ID` | OCI Console, go to `Networking` -> `Virtual Cloud Networks` -> your VCN -> `Subnets`, then copy the subnet OCID from the subnet details page. |
| `OCI_IMAGE_ID` | OCI Console, go to `Compute` -> `Custom Images` for a custom image, or leave it blank so the app auto-picks a compatible Oracle-provided image. |
| `OCI_IMAGE_OS` | Used only when `OCI_IMAGE_ID` is blank. Pick the OS family you want OCI to search for, such as `Canonical Ubuntu` or `Oracle Linux`. |
| `OCI_IMAGE_OS_VERSION` | Used only when `OCI_IMAGE_ID` is blank. Pick the exact OS version shown in OCI image listings. |
| `OCI_AVAILABILITY_DOMAIN` | OCI Console, region and tenancy details. Copy the exact availability domain name exactly as OCI shows it, including the prefix before the colon, for example `Uocm:EU-STOCKHOLM-1-AD-1`. |
| `OCI_SHAPE` | OCI Console, when creating a compute instance or on the shape picker. Match this to the image family you want. |
| `OCI_OCPUS` and `OCI_MEMORY_GB` | Only needed in the config file for some shapes. The GUI now hides these fields, but the values are still saved in the background. |
| `OCI_CONFIG_FILE` | Your local OCI SDK config file, usually `C:\Users\<you>\.oci\config` on Windows or `~/.oci/config` on Linux. |
| `OCI_PROFILE` | The profile name inside your OCI config file, usually `DEFAULT`. |
| `SSH_PUBLIC_KEY` | Your local SSH public key file, usually `id_ed25519.pub` or `id_rsa.pub`. Copy the full one-line public key contents into the field. |

## E2 Micro Test

Use this to confirm your API key, subnet, compartment, SSH key, and shape/image settings work before running any retry loop.

1. Copy:

```text
config/e2micro.example.env
```

to:

```text
config/.env.e2micro
```

2. Fill the values.
3. Run:

```text
run_e2micro_test.bat
```

## Project Layout

```text
run_gui_windows.bat             Open the GUI from the project root
loop.py                         Main OCI launcher
requirements.txt                Python dependencies
run_once_windows.bat            Run one launch attempt
start_auto_windows.bat          Register Windows scheduled retry task
stop_auto_windows.bat           Remove Windows scheduled retry task
check_oci_config.bat            Test OCI API config
run_e2micro_test.bat            Run one E2 Micro test
config/                         Example env files
scripts/windows/                Windows helper scripts
scripts/tests/                  Test launch helpers
release/OracleAutoInstanceGUI/  GUI version and its launcher files
deploy/linux/                   Optional Linux installer
deploy/systemd/                 Optional systemd units
docs/                           Extra notes
```

## Optional Linux Install

```bash
sudo bash deploy/linux/install_ubuntu.sh
sudo nano /etc/loop-oracle.env
sudo systemctl start loop-oracle.timer
```

## Safety

This can create paid cloud resources. Watch your OCI limits, billing, and running instances. Keep `.env`, OCI private keys, and SSH private keys out of GitHub.

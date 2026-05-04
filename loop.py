import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import oci


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class InstanceConfig:
    compartment_id: str
    subnet_id: str
    image_id: Optional[str]
    image_os: str
    image_os_version: Optional[str]
    shape: str
    ocpus: float
    memory_gb: float
    availability_domain: str
    display_name_prefix: str
    assign_public_ip: bool
    ssh_public_key: Optional[str]
    delete_failed_instance: bool
    instance_wait_seconds: int
    capacity_retry_success_exit: bool
    oci_config_path: str
    oci_profile: str


def env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value or ""


def env_float(name: str, default: str) -> float:
    value = env(name, default)
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got: {value}") from exc


def env_int(name: str, default: str) -> int:
    value = env(name, default)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number, got: {value}") from exc


def env_bool(name: str, default: str) -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "y"}


def load_config() -> InstanceConfig:
    return InstanceConfig(
        compartment_id=env("OCI_COMPARTMENT_ID", required=True),
        subnet_id=env("OCI_SUBNET_ID", required=True),
        image_id=env("OCI_IMAGE_ID") or None,
        image_os=env("OCI_IMAGE_OS", "Oracle Linux"),
        image_os_version=env("OCI_IMAGE_OS_VERSION") or None,
        shape=env("OCI_SHAPE", "VM.Standard.A1.Flex"),
        ocpus=env_float("OCI_OCPUS", "1"),
        memory_gb=env_float("OCI_MEMORY_GB", "6"),
        availability_domain=env("OCI_AVAILABILITY_DOMAIN", required=True),
        display_name_prefix=env("INSTANCE_NAME_PREFIX", "auto-instance"),
        assign_public_ip=env_bool("ASSIGN_PUBLIC_IP", "true"),
        ssh_public_key=env("SSH_PUBLIC_KEY") or None,
        delete_failed_instance=env_bool("DELETE_FAILED_INSTANCE", "true"),
        instance_wait_seconds=env_int("INSTANCE_WAIT_SECONDS", "900"),
        capacity_retry_success_exit=env_bool("CAPACITY_RETRY_SUCCESS_EXIT", "true"),
        oci_config_path=env("OCI_CONFIG_FILE", oci.config.DEFAULT_LOCATION),
        oci_profile=env("OCI_PROFILE", oci.config.DEFAULT_PROFILE),
    )


def get_latest_image_id(compute_client: oci.core.ComputeClient, config: InstanceConfig) -> str:
    if config.image_id:
        return config.image_id

    kwargs = {
        "compartment_id": config.compartment_id,
        "operating_system": config.image_os,
        "shape": config.shape,
        "sort_by": "TIMECREATED",
        "sort_order": "DESC",
    }
    if config.image_os_version:
        kwargs["operating_system_version"] = config.image_os_version

    images = compute_client.list_images(**kwargs).data
    if not images:
        version_hint = f" {config.image_os_version}" if config.image_os_version else ""
        raise ValueError(f"No image found for {config.image_os}{version_hint} and shape {config.shape}")

    image = images[0]
    logging.info("Using image %s (%s %s)", image.id, image.operating_system, image.operating_system_version)
    return image.id


def build_launch_details(config: InstanceConfig, image_id: str) -> oci.core.models.LaunchInstanceDetails:
    metadata = {}
    if config.ssh_public_key:
        metadata["ssh_authorized_keys"] = config.ssh_public_key
    shape_config = None
    if config.shape.endswith(".Flex"):
        shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=config.ocpus,
            memory_in_gbs=config.memory_gb,
        )

    return oci.core.models.LaunchInstanceDetails(
        compartment_id=config.compartment_id,
        availability_domain=config.availability_domain,
        shape=config.shape,
        subnet_id=config.subnet_id,
        display_name=f"{config.display_name_prefix}-{os.getpid()}",
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=image_id,
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            assign_public_ip=config.assign_public_ip,
        ),
        shape_config=shape_config,
        metadata=metadata or None,
    )


def wait_for_launch_result(compute_client: oci.core.ComputeClient, instance_id: str, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_state = "UNKNOWN"

    while time.monotonic() < deadline:
        instance = compute_client.get_instance(instance_id).data
        last_state = instance.lifecycle_state
        logging.info("Instance %s state: %s", instance_id, last_state)

        if last_state == "RUNNING":
            return last_state
        if last_state in {"TERMINATED", "TERMINATING"}:
            return last_state
        if last_state in {"FAILED", "STOPPED"}:
            return last_state

        time.sleep(20)

    logging.warning("Timed out waiting for instance %s; last state was %s", instance_id, last_state)
    return last_state


def terminate_instance(compute_client: oci.core.ComputeClient, instance_id: str) -> None:
    logging.warning("Terminating failed instance %s", instance_id)
    compute_client.terminate_instance(instance_id, preserve_boot_volume=False)


def is_capacity_error(exc: Exception) -> bool:
    if not isinstance(exc, oci.exceptions.ServiceError):
        return False
    message = (exc.message or "").lower()
    return "out of host capacity" in message or exc.code == "InternalError" and "capacity" in message


def launch_instance(config: InstanceConfig) -> str:
    oci_config = oci.config.from_file(config.oci_config_path, config.oci_profile)
    compute_client = oci.core.ComputeClient(oci_config)
    image_id = get_latest_image_id(compute_client, config)
    launch_details = build_launch_details(config, image_id)
    response = compute_client.launch_instance(launch_details)
    instance_id = response.data.id
    logging.info("Launched instance %s named %s", instance_id, launch_details.display_name)
    state = wait_for_launch_result(compute_client, instance_id, config.instance_wait_seconds)
    if state != "RUNNING":
        if config.delete_failed_instance and state not in {"TERMINATED", "TERMINATING"}:
            terminate_instance(compute_client, instance_id)
        raise RuntimeError(f"Instance {instance_id} did not reach RUNNING state; final state: {state}")
    return instance_id


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    try:
        load_dotenv()
        config = load_config()
        launch_instance(config)
        return 0
    except Exception as exc:
        if is_capacity_error(exc):
            logging.warning("Oracle has no A1.Flex capacity right now. No instance was created; the next scheduled run will retry.")
            config = load_config()
            return 0 if config.capacity_retry_success_exit else 1
        logging.exception("Oracle Cloud instance launch failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

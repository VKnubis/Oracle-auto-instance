import sys

import oci


def main() -> int:
    try:
        config = oci.config.from_file()
        oci.config.validate_config(config)
        identity = oci.identity.IdentityClient(config)
        user = identity.get_user(config["user"]).data
        print(f"OCI config works. User: {user.name}")
        return 0
    except Exception as exc:
        print(f"OCI config check failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

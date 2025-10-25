import ipaddress
import logging
import os
import socket
import ssl

import click
import uvicorn
from cryptography import x509
from cryptography.hazmat.backends import default_backend

import dashboard  # noqa
from app import app, logger  # noqa
from app.utils.logger import LOGGING_CONFIG
from config import (
    DEBUG,
    UVICORN_HOST,
    UVICORN_LOOP,
    UVICORN_PORT,
    UVICORN_SSL_CERTFILE,
    UVICORN_SSL_KEYFILE,
    UVICORN_UDS,
    MOREBOT_LICENSE,
    MOREBOT_SECRET,
)


def check_and_modify_ip(ip_address: str) -> str:
    """
    Check if an IP address is private. If not, return localhost.

    IPv4 Private range = [
        "192.168.0.0",
        "192.168.255.255",
        "10.0.0.0",
        "10.255.255.255",
        "172.16.0.0",
        "172.31.255.255"
    ]

    Args:
        ip_address (str): IP address to check

    Returns:
        str: Original IP if private, otherwise localhost

    Raises:
        ValueError: If the provided IP address is invalid, return localhost.
    """
    try:
        # Attempt to resolve hostname to IP address
        resolved_ip = socket.gethostbyname(ip_address)

        # Convert string to IP address object
        ip = ipaddress.ip_address(resolved_ip)

        if ip == ipaddress.ip_address("0.0.0.0"):
            return "localhost"
        elif ip.is_private:
            return ip_address
        else:
            return "localhost"

    except (ValueError, socket.gaierror):
        return "localhost"


def validate_cert_and_key(cert_file_path, key_file_path):
    if not os.path.isfile(cert_file_path):
        raise ValueError(f"SSL certificate file '{cert_file_path}' does not exist.")
    if not os.path.isfile(key_file_path):
        raise ValueError(f"SSL key file '{key_file_path}' does not exist.")

    try:
        context = ssl.create_default_context()
        context.load_cert_chain(certfile=cert_file_path, keyfile=key_file_path)
    except ssl.SSLError as e:
        raise ValueError(f"SSL Error: {e}")

    try:
        with open(cert_file_path, "rb") as cert_file:
            cert_data = cert_file.read()
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        if cert.issuer == cert.subject:
            raise ValueError("The certificate is self-signed and not issued by a trusted CA.")

    except Exception as e:
        raise ValueError(f"Certificate verification failed: {e}")


if __name__ == "__main__":
    # Do NOT change workers count for now
    # multi-workers support isn't implemented yet for APScheduler and XRay module

    if not MOREBOT_SECRET or not MOREBOT_LICENSE:
        raise ValueError("MOREBOT_SECRET and MOREBOT_LICENSE must be set in environment variables.")

    bind_args = {}

    if UVICORN_SSL_CERTFILE and UVICORN_SSL_KEYFILE:
        validate_cert_and_key(UVICORN_SSL_CERTFILE, UVICORN_SSL_KEYFILE)

        bind_args["ssl_certfile"] = UVICORN_SSL_CERTFILE
        bind_args["ssl_keyfile"] = UVICORN_SSL_KEYFILE

        if UVICORN_UDS:
            bind_args["uds"] = UVICORN_UDS
        else:
            bind_args["host"] = UVICORN_HOST
            bind_args["port"] = UVICORN_PORT

    else:
        if UVICORN_UDS:
            bind_args["uds"] = UVICORN_UDS
        else:
            ip = check_and_modify_ip(UVICORN_HOST)

            logger.warning(f"""
{click.style("IMPORTANT!", blink=True, bold=True, fg="yellow")}
You're running PasarGuard without specifying {click.style("UVICORN_SSL_CERTFILE", italic=True, fg="magenta")} and {click.style("UVICORN_SSL_KEYFILE", italic=True, fg="magenta")}.
The application will only be accessible through localhost. This means that {click.style("PasarGuard and subscription URLs will not be accessible externally", bold=True)}.

If you need external access, please provide the SSL files to allow the server to bind to 0.0.0.0. Alternatively, you can run the server on localhost or a Unix socket and use a reverse proxy, such as Nginx or Caddy, to handle SSL termination and provide external access.

If you wish to continue without SSL, you can use SSH port forwarding to access the application from your machine. note that in this case, subscription functionality will not work. 

Use the following command:

{click.style(f"ssh -L {UVICORN_PORT}:localhost:{UVICORN_PORT} user@server", italic=True, fg="cyan")}

Then, navigate to {click.style(f"http://{ip}:{UVICORN_PORT}", bold=True)} on your computer.
            """)

            bind_args["host"] = ip
            bind_args["port"] = UVICORN_PORT

    if DEBUG:
        bind_args["uds"] = None
        bind_args["host"] = "0.0.0.0"

    log_level = logging.DEBUG if DEBUG else logging.INFO
    LOGGING_CONFIG["loggers"]["uvicorn"]["level"] = log_level
    LOGGING_CONFIG["loggers"]["uvicorn.error"]["level"] = log_level
    LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"] = log_level

    try:
        uvicorn.run(
            "main:app",
            **bind_args,
            workers=1,
            reload=DEBUG,
            log_config=LOGGING_CONFIG,
            loop=UVICORN_LOOP,
        )
    except FileNotFoundError:  # to prevent error on removing unix sock
        pass

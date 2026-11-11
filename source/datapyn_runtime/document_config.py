"""Validate SDK connection settings without opening a network connection."""

from urllib.parse import parse_qsl, urlsplit

from .database_capabilities import DOCUMENT_DATABASES


def normalize_document_config(config):
    result = dict(config)
    kind = str(result.get("db_type", "")).lower()
    if kind not in DOCUMENT_DATABASES:
        return result
    if not isinstance(result.get("automatic_transactions", True), bool):
        raise ValueError("automatic_transactions must be a boolean")
    if (result.get("ssh") or {}).get("enabled") or result.get("ssh_tunnel_id"):
        raise ValueError("SSH tunnels are unavailable for document databases and HTTP endpoints")
    result["db_type"] = kind
    if "ssl_ca" in result:
        if result["ssl_ca"]:
            result["ca_certificate"] = result["ssl_ca"]
        else:
            result.pop("ca_certificate", None)
    result["schema"] = ""
    if kind == "cosmosdb":
        api = str(result.get("cosmos_api") or "nosql").lower()
        if api not in {"nosql", "mongodb"}:
            raise ValueError("Choose Cosmos DB API for NoSQL or MongoDB")
        result["cosmos_api"] = api
    mongo = kind == "mongodb" or kind == "cosmosdb" and result["cosmos_api"] == "mongodb"
    if mongo:
        uri = str(result.get("mongodb_uri") or "").strip()
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("Enter a mongodb:// or mongodb+srv:// URI")
        authority = uri.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
        if not authority or "@" in authority:
            raise ValueError("The saved MongoDB URI must contain only hosts; enter username and password in their fields")
        if any(ord(char) < 32 for char in uri) or len(uri) > 8192:
            raise ValueError("Invalid MongoDB URI")
        parsed_uri = urlsplit(uri)
        if parsed_uri.fragment:
            raise ValueError("MongoDB URI fragments are not supported; enter credentials separately")
        options = parse_qsl(parsed_uri.query, keep_blank_values=True)
        secret_options = {"password", "tlscertificatekeyfilepassword", "authmechanismproperties", "proxypassword", "proxyusername"}
        if any(key.casefold() in secret_options for key, _ in options):
            raise ValueError("MongoDB URI contains a credential option; enter credentials separately")
        result["mongodb_uri"] = uri
        result.pop("container", None)
    else:
        endpoint = str(result.get("endpoint") or "").strip().rstrip("/")
        parsed = urlsplit(endpoint)
        try:
            valid_port = parsed.port
        except ValueError:
            raise ValueError("Invalid endpoint port") from None
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(ord(char) < 33 for char in endpoint)):
            raise ValueError("Enter an HTTP(S) endpoint without credentials, query parameters or fragments")
        if kind == "cosmosdb" and parsed.scheme != "https":
            raise ValueError("Cosmos DB requires an HTTPS endpoint")
        result["endpoint"] = endpoint
        result["host"] = parsed.hostname
        result["port"] = valid_port or (443 if parsed.scheme == "https" else 80)
        modes = {"basic", "api_key"} if kind == "elasticsearch" else {"key", "entra"}
        result["auth_mode"] = str(result.get("auth_mode") or ("basic" if kind == "elasticsearch" else "key"))
        if result["auth_mode"] not in modes:
            raise ValueError("Unsupported authentication mode for this database")
        if kind == "cosmosdb":
            result["container"] = str(result.get("container") or "")
    result["database"] = str(result.get("database") or "")
    return result

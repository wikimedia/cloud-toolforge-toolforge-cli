"""Originally copied from https://github.com/wikimedia/cloud-toolforge-jobs-framework-api/blob/main/common/k8sclient.py"""
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

import requests
import urllib3
import yaml
from cryptography import x509
from cryptography.hazmat.backends import default_backend

# T253412: Disable warnings about unverifed TLS certs when talking to the
# Kubernetes API endpoint
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

StatusCode = int


class NotFound(Exception):
    pass


class BadConfig(Exception):
    pass


class K8sAPIClient:
    KIND_TO_VERSION = {
        "pods": "v1",
        "pipelineruns": "tekton.dev/v1beta1",
    }

    @classmethod
    def from_file(cls, kubeconfig: Path, namespace: Optional[str] = None) -> "K8sAPIClient":
        """Create a client from a kubeconfig file."""
        with kubeconfig.expanduser().open() as f:
            config = yaml.safe_load(f.read())
        try:
            return cls(config=config, namespace=namespace)
        except Exception as error:
            raise BadConfig(f"Got an error parsing the config {kubeconfig}") from error

    @staticmethod
    def _get_context_to_use(contexts: List[Dict[str, Any]], current_context_name: str) -> Dict[str, Any]:
        """Prefer the toolforge context over anything else, fallback to the configured current context."""
        current_context = None
        for context in contexts:
            if context["name"] == "toolforge":
                return context["context"]
            elif context["name"] == current_context_name:
                current_context = context

        if current_context is None:
            raise BadConfig(
                f"Unable to find a 'toolforge' context or current context '{current_context}' context in the kubectl config."
            )

        return current_context["context"]

    @staticmethod
    def _get_user_from_cert(cert_path: Path) -> str:
        # we have to pass a backend for backwards compatibility with cryptography<3.1 shipped with buster
        mycert = x509.load_pem_x509_certificate(cert_path.read_bytes(), backend=default_backend())
        response = mycert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return response[0].value

    def __init__(self, config: Dict[str, Any], timeout_s: int = 10, namespace: Optional[str] = None):
        self.config = config
        self.timeout_s = timeout_s

        self.context = self._get_context_to_use(
            contexts=self.config["contexts"], current_context_name=self.config.get("current-context", "default")
        )
        self.cluster = cast(Dict[str, Any], self._find_object_in_config("clusters", self.context["cluster"]))
        self.server = cast(str, self.cluster["server"])
        self.namespace = namespace or cast(str, self.context["namespace"])
        self.kubectl_user = cast(Dict[str, Any], self._find_object_in_config("users", self.context["user"]))
        if "client-certificate" not in self.kubectl_user:
            raise BadConfig(
                f"Currently only certificate based authorization is supported, but none found for user {self.kubectl_user['name']}."
            )

        self.user = self._get_user_from_cert(cert_path=Path(self.kubectl_user["client-certificate"]))
        self.session = requests.Session()
        self.session.cert = (self.kubectl_user["client-certificate"], self.kubectl_user["client-key"])
        # T253412: We are deliberately not validating the api endpoint's TLS
        # certificate. The only way to do this with a self-signed cert is to
        # pass the path to a CA bundle. We actually *can* do that, but with
        # python2 we have seen the associated clean up code fail and leave
        # /tmp full of orphan files.
        # TODO: review for python3
        self.session.verify = False

    def _find_object_in_config(self, kind: str, name: str) -> Any:
        for obj in self.config[kind]:
            if obj["name"] == name:
                return obj[kind[:-1]]
        raise KeyError(f"Name {name} not found in {kind} section of config")

    def _make_requests_kwargs(self, url: str, **kwargs) -> Dict[str, Any]:
        version = cast(str, kwargs.pop("version", "v1"))
        if version == "v1":
            root = "api"
        else:
            root = "apis"
        kwargs["url"] = f"{self.server}/{root}/{version}/namespaces/{self.namespace}/{url}"
        name = cast(Optional[str], kwargs.pop("name", None))
        if name is not None:
            kwargs["url"] = f"{kwargs['url']}/{name}"
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout_s
        return kwargs

    def _get(self, url: str, **kwargs) -> Dict[str, Any]:
        response = self.session.get(**self._make_requests_kwargs(url, **kwargs))
        response.raise_for_status()
        return response.json()

    def _post(self, url, **kwargs) -> requests.Response:
        response = self.session.post(**self._make_requests_kwargs(url, **kwargs))
        if response.status_code == 400:
            raise Exception(f"Bad request: {response.text}")
        response.raise_for_status()
        return response

    def _delete(self, url: str, **kwargs) -> StatusCode:
        response = self.session.delete(**self._make_requests_kwargs(url, **kwargs))
        response.raise_for_status()
        return response.status_code

    def get_objects(self, kind: str, selector: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._get(
            url=kind,
            params={"labelSelector": selector},
            version=K8sAPIClient.KIND_TO_VERSION[kind],
        )["items"]

    def get_object(self, kind: str, name: Optional[str] = None) -> Dict[str, Any]:
        try:
            return self._get(
                url=kind,
                name=name,
                version=K8sAPIClient.KIND_TO_VERSION[kind],
            )
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404:
                raise NotFound(f"Unable to find an object with name '{name}' of kind '{kind}'") from error

            raise

    def delete_objects(self, kind: str, selector: Optional[str] = None) -> List[StatusCode]:
        status_codes = []
        if kind == "services":
            # Service does not have a Delete Collection option
            for svc in self.get_objects(kind, selector):
                status_codes.append(
                    self._delete(
                        url=kind,
                        name=svc["metadata"]["name"],
                        version=K8sAPIClient.KIND_TO_VERSION[kind],
                    )
                )
        else:
            status_codes.append(
                self._delete(
                    url=kind,
                    params={"labelSelector": selector},
                    version=K8sAPIClient.KIND_TO_VERSION[kind],
                )
            )
        return status_codes

    def create_object(self, kind: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        return self._post(
            url=kind,
            json=spec,
            version=K8sAPIClient.KIND_TO_VERSION[kind],
        ).json()

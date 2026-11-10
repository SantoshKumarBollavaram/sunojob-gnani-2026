"""Small provider schema, separate from strict local Pydantic validation.

Inline local references and send only basic JSON-schema keywords. Provider
constraints assist generation; the original domain model remains authoritative.
"""

from copy import deepcopy


def generation_schema(schema):
    root = deepcopy(schema)

    def expand(node, stack=()):
        if not isinstance(node, dict):
            raise ValueError("Schema nodes must be objects")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise ValueError("Only local JSON-schema references are supported")
            if ref in stack:
                raise ValueError("Recursive schemas are not supported by this adapter")
            target = root
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise ValueError("Unresolved local JSON-schema reference") from None
            return expand(target, stack + (ref,))

        kind = node.get("type")
        if kind not in {"object", "array", "string", "integer", "number", "boolean"}:
            raise ValueError("Unsupported schema shape; do not silently drop type semantics")
        result = {"type": kind}
        if "enum" in node:
            result["enum"] = deepcopy(node["enum"])
        if kind == "object":
            result["properties"] = {
                name: expand(child, stack) for name, child in node.get("properties", {}).items()
            }
            if "required" in node:
                result["required"] = list(node["required"])
        if kind == "array":
            result["items"] = expand(node["items"], stack)
        return result

    return expand(root)
